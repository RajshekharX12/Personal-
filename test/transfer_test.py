import sys
import types
import os

# ensure project root is on sys.path so 'hybrid' package imports work
try:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
except NameError:
    ROOT = os.path.abspath(os.path.join(os.getcwd(), "."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import json
from datetime import datetime, timezone, timedelta


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.sets = {}
        self.zsets = {}

    @classmethod
    def from_url(cls, *args, **kwargs):
        return cls()

    def hset(self, key, *args, **kwargs):
        if kwargs and 'mapping' in kwargs:
            mapping = kwargs['mapping']
            self.hashes.setdefault(key, {})
            for k, v in mapping.items():
                self.hashes[key][k] = v
            return True
        if len(args) == 2:
            field, value = args
            self.hashes.setdefault(key, {})
            self.hashes[key][field] = value
            return True
        return False

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}) or {})

    def sadd(self, key, member):
        s = self.sets.setdefault(key, set())
        s.add(member)
        return True

    def srem(self, key, member):
        s = self.sets.setdefault(key, set())
        if member in s:
            s.remove(member)
            return True
        return False

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def exists(self, key):
        return key in self.hashes or key in self.sets or key in self.zsets

    def zadd(self, key, mapping):
        z = self.zsets.setdefault(key, {})
        for member, score in mapping.items():
            z[member] = float(score)
        return True

    def zrangebyscore(self, key, min_s, max_s):
        out = []
        for member, score in (self.zsets.get(key) or {}).items():
            if score >= float(min_s) and score <= float(max_s):
                out.append(member)
        return out

    def keys(self, pattern=None):
        # support simple prefix pattern like "rental:*"
        if not pattern or pattern == '*':
            return list(self.hashes.keys())
        if pattern.endswith('*'):
            prefix = pattern[:-1]
            return [k for k in list(self.hashes.keys()) if k.startswith(prefix)]
        return [k for k in list(self.hashes.keys()) if k == pattern]

    def zrem(self, key, member):
        z = self.zsets.get(key, {})
        if member in z:
            del z[member]
            return True
        return False

    def delete(self, key):
        self.hashes.pop(key, None)
        return True

    def pipeline(self):
        parent = self

        class Pipe:
            def __init__(self, p):
                self.p = p
                self.ops = []

            def delete(self, key):
                self.ops.append(('delete', key))

            def zrem(self, key, member):
                self.ops.append(('zrem', key, member))

            def srem(self, key, member):
                self.ops.append(('srem', key, member))

            def execute(self):
                for op in self.ops:
                    if op[0] == 'delete':
                        parent.delete(op[1])
                    elif op[0] == 'zrem':
                        parent.zrem(op[1], op[2])
                    elif op[0] == 'srem':
                        parent.srem(op[1], op[2])
                return True

        return Pipe(parent)

    def expire(self, *args, **kwargs):
        return True


def setup_fake_redis():
    import sys
    fake_redis_mod = types.ModuleType('redis')
    fake_redis_mod.Redis = FakeRedis
    sys.modules['redis'] = fake_redis_mod


def run_test():
    setup_fake_redis()
    # import after injecting fake redis
    from hybrid.plugins import db

    # create two users and a rental owned by user1
    user1 = 1111
    user2 = 2222
    number = "+88800000001"
    rent_date = datetime.now(timezone.utc) - timedelta(hours=1)
    hours = 48

    # save number in user list and rental store
    db.save_number(number, user1, hours, date=rent_date)
    db.save_number_data(number, user1, rent_date, hours)

    print('Initial owner for', number, '->', db.get_user_by_number(number))
    print('Rented data before transfer ->', db.get_rented_data_for_number(number))

    success, err = db.transfer_number(number, user1, user2)
    print('transfer_number returned:', success, err)

    print('Owner after transfer ->', db.get_user_by_number(number))
    print('Rented data after transfer ->', db.get_rented_data_for_number(number))


if __name__ == '__main__':
    run_test()
