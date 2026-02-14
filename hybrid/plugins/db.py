# (©) @Hybrid_Vamp - https://github.com/hybridvamp
# MongoDB as primary storage + Redis for caching (90% faster reads)

import json
import os
import ssl
import redis
import config
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

def _now():
    return datetime.now(timezone.utc)
from pymongo.errors import PyMongoError

# --- MongoDB ---
MONGO_URI = getattr(config, "MONGO_URI", None) or os.environ.get("MONGO_URI") or os.environ.get("DATABASE_URL", "mongodb://localhost:27017")
DB_NAME = getattr(config, "DB_NAME", None) or os.environ.get("DATABASE_NAME", "rentalbot")
_mongo_client = MongoClient(MONGO_URI)
_db = _mongo_client[DB_NAME]

_users = _db["users"]
_rentals = _db["rentals"]
_numbers_pool = _db["numbers_pool"]
_admins_coll = _db["admins"]
_languages = _db["languages"]
_payment_methods = _db["payment_methods"]
_rules_coll = _db["rules"]
_deletions = _db["deletions"]
_restricted = _db["restricted"]

# --- Redis (Cache Layer) ---
_redis_uri = (getattr(config, "REDIS_URI", None) or os.environ.get("REDIS_URL", "redis://localhost:6379/0")).strip()
if not (_redis_uri.startswith("redis://") or _redis_uri.startswith("rediss://") or _redis_uri.startswith("unix://")):
    _redis_uri = "redis://" + _redis_uri.lstrip("/")
_use_tls_env = os.environ.get("REDIS_USE_TLS", "").lower()
_is_redislabs = "redislabs.com" in _redis_uri or "azure.cloud" in _redis_uri
_use_tls = _use_tls_env in ("1", "true", "yes") if _use_tls_env else (not _is_redislabs)

if not _use_tls and _redis_uri.startswith("rediss://"):
    _redis_uri = "redis://" + _redis_uri[9:]

if _is_redislabs and _use_tls:
    if _redis_uri.startswith("redis://"):
        _redis_uri = "rediss://" + _redis_uri[8:]
    try:
        _tls_v12 = ssl.TLSVersion.TLSv1_2
    except AttributeError:
        _tls_v12 = None
    _kwargs = {"decode_responses": True, "ssl_cert_reqs": ssl.CERT_NONE, "ssl_check_hostname": False}
    if _tls_v12 is not None:
        _kwargs["ssl_min_version"] = _tls_v12
    _redis = redis.Redis.from_url(_redis_uri, **_kwargs)
else:
    _redis = redis.Redis.from_url(_redis_uri, decode_responses=True)

CACHE_TTL = 300  # 5 min for hot data

def _parse_dt(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.replace(tzinfo=timezone.utc) if s.tzinfo is None else s
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ========= USER NUMBERS =========
def save_number(number: str, user_id: int, hours: int, date: datetime = None, extend: bool = False):
    if date is None:
        date = _now()
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    doc = _users.find_one({"user_id": user_id})
    numbers = doc.get("numbers", []) if doc else []

    for i, n in enumerate(numbers):
        if n.get("number") == number:
            if not extend:
                return False, "ALREADY"
            numbers[i]["hours"] = hours
            numbers[i]["date"] = date.isoformat()
            _users.update_one({"user_id": user_id}, {"$set": {"numbers": numbers}})
            _redis.delete(f"user:{user_id}")
            return True, "UPDATED"

    numbers.append({"number": number, "hours": hours, "date": date.isoformat()})
    _users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "balance": doc.get("balance", 0) if doc else 0, "numbers": numbers}},
        upsert=True
    )
    _redis.delete(f"user:{user_id}")
    return True, "SAVED"


def get_user_by_number(number: str):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    for doc in _users.find({"numbers.number": number}):
        for n in doc.get("numbers", []):
            if n.get("number") == number:
                date_s = n.get("date")
                return doc["user_id"], n.get("hours", 0), _parse_dt(date_s)
    return False


def get_numbers_by_user(user_id: int):
    doc = _users.find_one({"user_id": user_id})
    if not doc:
        return []
    return [n.get("number", str(n)) for n in doc.get("numbers", []) if isinstance(n, dict) and "number" in n]


def remove_number(number: str, user_id: int):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    doc = _users.find_one({"user_id": user_id})
    if not doc:
        return False, "NOT_FOUND"
    numbers = [n for n in doc.get("numbers", []) if n.get("number") != number]
    if len(numbers) == len(doc.get("numbers", [])):
        return False, "NOT_FOUND"
    _users.update_one({"user_id": user_id}, {"$set": {"numbers": numbers}})
    _redis.delete(f"user:{user_id}")
    return True, "REMOVED"


def get_remaining_rent_days(number: str):
    user_data = get_user_by_number(number)
    if not user_data:
        return None
    user_id, hours, rented_date = user_data
    now = _now()
    if rented_date and rented_date.tzinfo is None:
        rented_date = rented_date.replace(tzinfo=timezone.utc)
    elapsed = now - rented_date
    elapsed_hours = elapsed.total_seconds() / 3600
    remaining_hours = hours - elapsed_hours
    return max(0, int(remaining_hours // 24)), max(0, int(remaining_hours % 24))


# =========== Number Rent Data ============
def save_number_data(number: str, user_id: int, rent_date: datetime, hours: int):
    hours = int(hours)
    expiry_date = rent_date + timedelta(hours=hours)
    _rentals.update_one(
        {"number": number},
        {"$set": {
            "number": number,
            "user_id": user_id,
            "rent_date": rent_date,
            "hours": hours,
            "expiry_date": expiry_date,
        }},
        upsert=True
    )
    _redis.delete(f"rental:{number}")
    _redis.sadd("rentals:all", number)
    _redis.sadd(f"rentals:user:{user_id}", number)


def get_number_data(number: str):
    cached = _redis.hgetall(f"rental:{number}")
    if cached:
        out = {
            "number": cached.get("number"),
            "user_id": int(cached["user_id"]) if cached.get("user_id") else None,
            "hours": int(cached["hours"]) if cached.get("hours") else None,
        }
        if cached.get("rent_date"):
            out["rent_date"] = _parse_dt(cached["rent_date"])
        if cached.get("expiry_date"):
            out["expiry_date"] = _parse_dt(cached["expiry_date"])
        return out

    doc = _rentals.find_one({"number": number})
    if not doc:
        return None
    out = {
        "number": doc.get("number"),
        "user_id": doc.get("user_id"),
        "hours": doc.get("hours"),
    }
    if doc.get("rent_date"):
        out["rent_date"] = doc["rent_date"] if isinstance(doc["rent_date"], datetime) else _parse_dt(doc["rent_date"])
    if doc.get("expiry_date"):
        out["expiry_date"] = doc["expiry_date"] if isinstance(doc["expiry_date"], datetime) else _parse_dt(doc["expiry_date"])
    # cache
    _cache_rental(number, out)
    return out


def _cache_rental(number: str, data: dict):
    m = {"number": data.get("number"), "user_id": str(data.get("user_id", "")), "hours": str(data.get("hours", ""))}
    if data.get("rent_date"):
        m["rent_date"] = data["rent_date"].isoformat()
    if data.get("expiry_date"):
        m["expiry_date"] = data["expiry_date"].isoformat()
    _redis.hset(f"rental:{number}", mapping=m)
    _redis.expire(f"rental:{number}", CACHE_TTL)


def get_user_numbers(user_id: int):
    members = _redis.smembers(f"rentals:user:{user_id}")
    if members:
        return list(members)
    nums = [r["number"] for r in _rentals.find({"user_id": user_id}, {"number": 1})]
    for n in nums:
        _redis.sadd(f"rentals:user:{user_id}", n)
    return nums


def remove_number_data(number: str):
    doc = _rentals.find_one({"number": number})
    if not doc:
        return False, "NOT_FOUND"
    user_id = doc.get("user_id")
    _rentals.delete_one({"number": number})
    _redis.delete(f"rental:{number}")
    _redis.srem("rentals:all", number)
    if user_id:
        _redis.srem(f"rentals:user:{user_id}", number)
    return True, "REMOVED"


def get_expired_numbers():
    now = datetime.now(timezone.utc)
    nums = []
    for r in _rentals.find({"expiry_date": {"$lte": now}}, {"number": 1}):
        nums.append(r["number"])
    return nums


def get_all_rentals():
    out = []
    for doc in _rentals.find({}):
        d = {"number": doc.get("number"), "user_id": doc.get("user_id")}
        rd = doc.get("rent_date")
        ed = doc.get("expiry_date")
        d["rent_date"] = rd if isinstance(rd, datetime) else _parse_dt(rd)
        d["expiry_date"] = ed if isinstance(ed, datetime) else _parse_dt(ed)
        d["hours"] = doc.get("hours", 0)
        out.append(d)
    return out


# ========= USER IDS =========
def save_user_id(user_id: int):
    if _users.find_one({"user_id": user_id}):
        return False, "EXISTS"
    _users.insert_one({"user_id": user_id, "numbers": [], "balance": 0})
    return True, "SAVED"


def get_all_user_ids():
    return [d["user_id"] for d in _users.find({}, {"user_id": 1})]


# ========= BALANCES =========
def save_user_balance(user_id: int, balance: float | int):
    _cache_key = f"bal:{user_id}"
    _redis.delete(_cache_key)
    doc = _users.find_one({"user_id": user_id})
    if not doc:
        _users.insert_one({"user_id": user_id, "balance": balance, "numbers": []})
        return "CREATED"
    _users.update_one({"user_id": user_id}, {"$set": {"balance": balance}})
    return "UPDATED"


def get_user_balance(user_id: int):
    cached = _redis.get(f"bal:{user_id}")
    if cached is not None:
        return float(cached)
    doc = _users.find_one({"user_id": user_id}, {"balance": 1})
    bal = float(doc["balance"]) if doc and "balance" in doc else None
    if bal is not None:
        _redis.setex(f"bal:{user_id}", CACHE_TTL, str(bal))
    return bal


def get_total_balance():
    total = 0.0
    count = 0
    for doc in _users.find({}, {"balance": 1}):
        b = doc.get("balance")
        if b is not None:
            total += float(b)
            count += 1
    return total, count


# ========= ADMINS =========
def add_admin(user_id: int):
    if _admins_coll.find_one({"user_id": user_id}):
        return False, "ALREADY"
    _admins_coll.insert_one({"user_id": user_id})
    _redis.delete("admins:all")
    return True, "ADDED"


def remove_admin(user_id: int):
    r = _admins_coll.delete_one({"user_id": user_id})
    _redis.delete("admins:all")
    return (True, "REMOVED") if r.deleted_count else (False, "NOT_FOUND")


def is_admin(user_id: int):
    cached = _redis.sismember("admins:all", str(user_id))
    if cached:
        return True
    doc = _admins_coll.find_one({"user_id": user_id})
    if doc:
        _redis.sadd("admins:all", str(user_id))
        return True
    return False


def get_all_admins():
    cached = _redis.smembers("admins:all")
    if cached:
        return [int(x) for x in cached]
    admins = [d["user_id"] for d in _admins_coll.find({}, {"user_id": 1})]
    for a in admins:
        _redis.sadd("admins:all", str(a))
    _redis.expire("admins:all", CACHE_TTL)
    return admins


# ========= NUMBERS POOL =========
def save_number_info(number: str, price_30: float, price_60: float, price_90: float, available: bool = True):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    now = _now()
    data = {
        "number": number,
        "prices": {"30d": price_30, "60d": price_60, "90d": price_90},
        "hours": {"30d": 30 * 24, "60d": 60 * 24, "90d": 90 * 24},
        "available": available,
        "updated_at": now,
    }
    existed = _numbers_pool.find_one({"number": number})
    _numbers_pool.update_one({"number": number}, {"$set": data}, upsert=True)
    _redis.delete(f"number:{number}")
    return "UPDATED" if existed else "CREATED"


def edit_number_info(number: str, **kwargs):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    doc = _numbers_pool.find_one({"number": number})
    if not doc:
        return False, "NO_CHANGES"

    updates = {}
    if "price_30" in kwargs:
        updates["prices.30d"] = kwargs["price_30"]
    if "price_60" in kwargs:
        updates["prices.60d"] = kwargs["price_60"]
    if "price_90" in kwargs:
        updates["prices.90d"] = kwargs["price_90"]
    if "available" in kwargs:
        updates["available"] = kwargs["available"]
    updates["updated_at"] = _now()

    if not updates:
        return False, "NO_CHANGES"
    _numbers_pool.update_one({"number": number}, {"$set": updates})
    _redis.delete(f"number:{number}")
    return True, "UPDATED"


def get_number_info(number: str) -> dict | bool:
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    cached = _redis.hgetall(f"number:{number}")
    if cached:
        return {
            "number": cached.get("number"),
            "prices": json.loads(cached.get("prices", "{}")),
            "hours": json.loads(cached.get("hours", "{}")),
            "available": cached.get("available", "true").lower() == "true",
            "updated_at": _parse_dt(cached.get("updated_at")),
        }

    doc = _numbers_pool.find_one({"number": number})
    if not doc:
        return False
    out = {
        "number": doc.get("number"),
        "prices": doc.get("prices", {}),
        "hours": doc.get("hours", {}),
        "available": doc.get("available", True),
        "updated_at": doc.get("updated_at"),
    }
    if isinstance(out["updated_at"], str):
        out["updated_at"] = _parse_dt(out["updated_at"])
    _redis.hset(f"number:{number}", mapping={
        "number": out["number"],
        "prices": json.dumps(out["prices"]),
        "hours": json.dumps(out["hours"]),
        "available": str(out["available"]).lower(),
        "updated_at": out["updated_at"].isoformat() if out["updated_at"] else "",
    })
    _redis.expire(f"number:{number}", CACHE_TTL)
    return out


def get_all_pool_numbers():
    return [d["number"] for d in _numbers_pool.find({}, {"number": 1})]


# ===================== language =====================
def save_user_language(user_id: int, lang: str):
    _languages.update_one({"user_id": user_id}, {"$set": {"language": lang}}, upsert=True)
    _redis.delete(f"lang:{user_id}")


def get_user_language(user_id: int):
    cached = _redis.get(f"lang:{user_id}")
    if cached:
        return cached
    doc = _languages.find_one({"user_id": user_id}, {"language": 1})
    lang = doc.get("language") if doc else None
    if lang:
        _redis.setex(f"lang:{user_id}", CACHE_TTL, lang)
    return lang


# ========= User Payment Method =========
def save_user_payment_method(user_id: int, method: str):
    _payment_methods.update_one({"user_id": user_id}, {"$set": {"method": method}}, upsert=True)
    _redis.delete(f"payment:{user_id}")


def get_user_payment_method(user_id: int):
    cached = _redis.get(f"payment:{user_id}")
    if cached:
        return cached if cached != "tron" else "cryptobot"  # migrate tron -> cryptobot
    doc = _payment_methods.find_one({"user_id": user_id}, {"method": 1})
    method = doc.get("method", "cryptobot") if doc else "cryptobot"
    if method == "tron":
        method = "cryptobot"
    _redis.setex(f"payment:{user_id}", CACHE_TTL, method)
    return method


# ========= RULES =========
def save_rules(rules: str, lang: str = "en"):
    _rules_coll.update_one({"language": lang}, {"$set": {"text": rules, "language": lang}}, upsert=True)
    _redis.delete(f"rules:{lang}")


def get_rules(lang: str = "en") -> str:
    cached = _redis.get(f"rules:{lang}")
    if cached:
        return cached
    doc = _rules_coll.find_one({"language": lang}, {"text": 1})
    text = doc.get("text", "No rules set.") if doc else "No rules set."
    _redis.setex(f"rules:{lang}", CACHE_TTL, text)
    return text


# ========= DELETE ACCOUNT =========
def save_7day_deletion(number: str, date: datetime):
    _deletions.update_one({"number": number}, {"$set": {"deletion_date": date}}, upsert=True)
    _redis.zadd("deletions:expiry", {number: date.timestamp()})


def get_7day_deletions():
    now = _now().timestamp()
    return list(_redis.zrangebyscore("deletions:expiry", 0, now))


def remove_7day_deletion(number: str):
    r = _deletions.delete_one({"number": number})
    _redis.zrem("deletions:expiry", number)
    return r.deleted_count > 0


def get_7day_date(number: str):
    doc = _deletions.find_one({"number": number}, {"deletion_date": 1})
    if not doc:
        return None
    d = doc.get("deletion_date")
    return d if isinstance(d, datetime) else _parse_dt(d)


# ========= RESTRICTED NOTIFY =========
def save_restricted_number(number: str, date=None):
    if date is None:
        date = _now()
    if _redis.sismember("restricted:all", number):
        return False, "ALREADY"
    _restricted.update_one({"number": number}, {"$set": {"number": number, "date": date}}, upsert=True)
    _redis.sadd("restricted:all", number)
    _redis.set(f"restricted:{number}", date.isoformat())
    return True, "SAVED"


def get_restricted_numbers():
    return list(_redis.smembers("restricted:all") or [])


def remove_restricted_number(number: str):
    if not _redis.sismember("restricted:all", number):
        return False, "NOT_FOUND"
    _restricted.delete_one({"number": number})
    _redis.srem("restricted:all", number)
    _redis.delete(f"restricted:{number}")
    return True, "REMOVED"


def get_rest_num_date(number: str):
    raw = _redis.get(f"restricted:{number}")
    if raw:
        return _parse_dt(raw)
    doc = _restricted.find_one({"number": number}, {"date": 1})
    if not doc:
        return None
    d = doc.get("date")
    return d if isinstance(d, datetime) else _parse_dt(d)


def restricted_del_toggle():
    key = "rest_toggle"
    raw = _redis.get(key)
    if raw is not None:
        new_state = not (raw == "1")
        _redis.set(key, "1" if new_state else "0")
        return new_state
    _redis.set(key, "1")
    return True


def is_restricted_del_enabled():
    return _redis.get("rest_toggle") == "1"


# ========= MAINTENANCE =========
def delete_all_data():
    try:
        _users.delete_many({})
        _rentals.delete_many({})
        _numbers_pool.delete_many({})
        _admins_coll.delete_many({})
        _languages.delete_many({})
        _payment_methods.delete_many({})
        _rules_coll.delete_many({})
        _deletions.delete_many({})
        _restricted.delete_many({})
        for key in _redis.scan_iter("*"):
            _redis.delete(key)
    except Exception:
        pass
    return True, "ALL DATA DELETED"
