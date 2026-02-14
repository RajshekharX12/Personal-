# (©) @Hybrid_Vamp - https://github.com/hybridvamp

import json
import ssl
import redis
import config
from datetime import datetime, timezone, timedelta
from hybrid.plugins.func import get_current_datetime

# Redis client (Redis Labs / Azure require SSL: use rediss:// in REDIS_URL)
_redis_uri = config.REDIS_URI
if "redislabs.com" in _redis_uri or "azure.cloud" in _redis_uri:
    if _redis_uri.startswith("redis://"):
        _redis_uri = "rediss://" + _redis_uri[8:]
    client = redis.Redis.from_url(
        _redis_uri,
        decode_responses=True,
        ssl_cert_reqs=ssl.CERT_NONE,
    )
else:
    client = redis.Redis.from_url(
        _redis_uri,
        decode_responses=True,
    )

# --- Helpers ---
def _parse_dt(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.replace(tzinfo=timezone.utc) if s.tzinfo is None else s
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ========= USER NUMBERS =========
def save_number(number: str, user_id: int, hours: int, date: datetime = None, extend: bool = False):
    if date is None:
        date = get_current_datetime()
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    key = f"user:{user_id}"
    numbers_raw = client.hget(key, "numbers")
    numbers = json.loads(numbers_raw) if numbers_raw else []

    for i, n in enumerate(numbers):
        if n.get("number") == number:
            if not extend:
                return False, "ALREADY"
            numbers[i]["hours"] = hours
            numbers[i]["date"] = date.isoformat()
            client.hset(key, "numbers", json.dumps(numbers))
            return True, "UPDATED"

    numbers.append({"number": number, "hours": hours, "date": date.isoformat()})
    if not client.exists(key):
        client.hset(key, mapping={"user_id": user_id, "balance": 0, "numbers": json.dumps(numbers)})
        client.sadd("users:all", user_id)
    else:
        client.hset(key, "numbers", json.dumps(numbers))
    return True, "SAVED"


def get_user_by_number(number: str):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    for uid in client.smembers("users:all"):
        key = f"user:{uid}"
        numbers_raw = client.hget(key, "numbers")
        if not numbers_raw:
            continue
        numbers = json.loads(numbers_raw)
        for n in numbers:
            if n.get("number") == number:
                hours = n.get("hours", 0)
                date_s = n.get("date")
                date = _parse_dt(date_s) if date_s else None
                return int(uid), hours, date
    return False


def get_numbers_by_user(user_id: int):
    key = f"user:{user_id}"
    numbers_raw = client.hget(key, "numbers")
    if not numbers_raw:
        return []
    numbers = json.loads(numbers_raw)
    return [n.get("number", str(n)) for n in numbers if isinstance(n, dict) and "number" in n]


def remove_number(number: str, user_id: int):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    key = f"user:{user_id}"
    numbers_raw = client.hget(key, "numbers")
    if not numbers_raw:
        return False, "NOT_FOUND"
    numbers = json.loads(numbers_raw)
    new_numbers = [n for n in numbers if n.get("number") != number]
    if len(new_numbers) == len(numbers):
        return False, "NOT_FOUND"
    client.hset(key, "numbers", json.dumps(new_numbers))
    return True, "REMOVED"


def get_remaining_rent_days(number: str):
    user_data = get_user_by_number(number)
    if not user_data:
        return None
    user_id, hours, rented_date = user_data
    now = get_current_datetime()
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
    key = f"rental:{number}"
    client.hset(key, mapping={
        "number": number,
        "user_id": user_id,
        "rent_date": rent_date.isoformat(),
        "hours": hours,
        "expiry_date": expiry_date.isoformat(),
    })
    client.zadd("rentals:expiry", {number: expiry_date.timestamp()})
    client.sadd("rentals:all", number)
    client.sadd(f"rentals:user:{user_id}", number)
    client.expire(key, int(hours * 3600) + 86400)


def get_number_data(number: str):
    key = f"rental:{number}"
    data = client.hgetall(key)
    if not data:
        return None
    out = {
        "number": data.get("number"),
        "user_id": int(data["user_id"]) if data.get("user_id") else None,
        "hours": int(data["hours"]) if data.get("hours") else None,
    }
    if data.get("rent_date"):
        out["rent_date"] = _parse_dt(data["rent_date"])
    if data.get("expiry_date"):
        out["expiry_date"] = _parse_dt(data["expiry_date"])
    return out


def get_user_numbers(user_id: int):
    members = client.smembers(f"rentals:user:{user_id}")
    return list(members) if members else []


def remove_number_data(number: str):
    key = f"rental:{number}"
    data = client.hgetall(key) if client.exists(key) else {}
    user_id = data.get("user_id")
    pipe = client.pipeline()
    pipe.delete(key)
    pipe.zrem("rentals:expiry", number)
    pipe.srem("rentals:all", number)
    if user_id:
        pipe.srem(f"rentals:user:{user_id}", number)
    pipe.execute()
    return (True, "REMOVED") if data else (False, "NOT_FOUND")


def get_expired_numbers():
    now = datetime.now(timezone.utc).timestamp()
    return list(client.zrangebyscore("rentals:expiry", 0, now))


def get_all_rentals():
    """Return list of rental dicts (number, user_id, expiry_date, hours, rent_date) for all current rentals."""
    numbers = client.smembers("rentals:all")
    out = []
    for number in numbers or []:
        key = f"rental:{number}"
        data = client.hgetall(key)
        if not data:
            continue
        doc = {
            "number": data.get("number"),
            "user_id": int(data["user_id"]) if data.get("user_id") else None,
        }
        if data.get("rent_date"):
            doc["rent_date"] = _parse_dt(data["rent_date"])
        if data.get("expiry_date"):
            doc["expiry_date"] = _parse_dt(data["expiry_date"])
        doc["hours"] = int(data["hours"]) if data.get("hours") else 0
        out.append(doc)
    return out


# ========= USER IDS =========
def save_user_id(user_id: int):
    key = f"user:{user_id}"
    if client.exists(key):
        return False, "EXISTS"
    client.hset(key, mapping={"user_id": user_id, "numbers": "[]", "balance": 0})
    client.sadd("users:all", user_id)
    return True, "SAVED"


def get_all_user_ids():
    members = client.smembers("users:all")
    return [int(x) for x in (members or [])]


# ========= BALANCES =========
def save_user_balance(user_id: int, balance: float | int):
    key = f"user:{user_id}"
    if not client.exists(key):
        client.hset(key, mapping={"user_id": user_id, "balance": balance, "numbers": "[]"})
        client.sadd("users:all", user_id)
        return "CREATED"
    client.hset(key, "balance", balance)
    return "UPDATED"


def get_user_balance(user_id: int):
    balance = client.hget(f"user:{user_id}", "balance")
    return float(balance) if balance is not None else None


def get_total_balance():
    total = 0.0
    count = 0
    for uid in client.smembers("users:all") or []:
        b = client.hget(f"user:{uid}", "balance")
        if b is not None:
            total += float(b)
            count += 1
    return total, count


# ========= ADMINS =========
def add_admin(user_id: int):
    added = client.sadd("admins:all", user_id)
    return (True, "ADDED") if added else (False, "ALREADY")


def remove_admin(user_id: int):
    removed = client.srem("admins:all", user_id)
    return (True, "REMOVED") if removed else (False, "NOT_FOUND")


def is_admin(user_id: int):
    return client.sismember("admins:all", user_id)


def get_all_admins():
    members = client.smembers("admins:all")
    return [int(x) for x in (members or [])]


# ========= NUMBERS POOL =========
def save_number_info(number: str, price_30: float, price_60: float, price_90: float, available: bool = True):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    now = get_current_datetime()
    data = {
        "number": number,
        "prices": {"30d": price_30, "60d": price_60, "90d": price_90},
        "hours": {"30d": 30 * 24, "60d": 60 * 24, "90d": 90 * 24},
        "available": available,
        "updated_at": now.isoformat(),
    }
    key = f"number:{number}"
    existed = client.exists(key)
    client.hset(key, mapping={
        "number": number,
        "prices": json.dumps(data["prices"]),
        "hours": json.dumps(data["hours"]),
        "available": str(available).lower(),
        "updated_at": data["updated_at"],
    })
    return "UPDATED" if existed else "CREATED"


def edit_number_info(number: str, **kwargs):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    key = f"number:{number}"
    if not client.exists(key):
        return False, "NO_CHANGES"

    updates = {}
    price_keys = ("price_30", "price_60", "price_90")
    if any(k in kwargs for k in price_keys):
        prices = json.loads(client.hget(key, "prices") or "{}")
        if "price_30" in kwargs:
            prices["30d"] = kwargs["price_30"]
        if "price_60" in kwargs:
            prices["60d"] = kwargs["price_60"]
        if "price_90" in kwargs:
            prices["90d"] = kwargs["price_90"]
        updates["prices"] = json.dumps(prices)
    if "available" in kwargs:
        updates["available"] = str(kwargs["available"]).lower()

    if not updates:
        return False, "NO_CHANGES"
    updates["updated_at"] = get_current_datetime().isoformat()
    client.hset(key, mapping=updates)
    return True, "UPDATED"


def get_number_info(number: str) -> dict | bool:
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    key = f"number:{number}"
    data = client.hgetall(key)
    if not data:
        return False
    out = {
        "number": data.get("number"),
        "prices": json.loads(data.get("prices") or "{}"),
        "hours": json.loads(data.get("hours") or "{}"),
        "available": data.get("available", "true").lower() == "true",
        "updated_at": _parse_dt(data.get("updated_at")),
    }
    return out


def get_all_pool_numbers():
    """Return list of all number strings in the pool (Redis keys number:*)."""
    keys = client.keys("number:*")
    return [k.replace("number:", "", 1) for k in (keys or [])]


# ===================== language db =====================
def save_user_language(user_id: int, lang: str):
    client.hset(f"lang:{user_id}", "language", lang)


def get_user_language(user_id: int):
    return client.hget(f"lang:{user_id}", "language")


# ========= User Payment Method =========
def save_user_payment_method(user_id: int, method: str):
    client.set(f"payment:{user_id}", method)


def get_user_payment_method(user_id: int):
    return client.get(f"payment:{user_id}") or "cryptobot"


# ========= RULES =========
def save_rules(rules: str, lang: str = "en"):
    client.hset(f"rules:{lang}", mapping={"text": rules, "language": lang})


def get_rules(lang: str = "en") -> str:
    text = client.hget(f"rules:{lang}", "text")
    return text if text else "No rules set."


# ========= DELETE ACCOUNT DB =========
def save_7day_deletion(number: str, date: datetime):
    client.hset(f"deletion:{number}", "deletion_date", date.isoformat())
    client.zadd("deletions:expiry", {number: date.timestamp()})


def get_7day_deletions():
    now = get_current_datetime().timestamp()
    return list(client.zrangebyscore("deletions:expiry", 0, now))


def remove_7day_deletion(number: str):
    key = f"deletion:{number}"
    if not client.exists(key):
        return False
    client.delete(key)
    client.zrem("deletions:expiry", number)
    return True


def get_7day_date(number: str):
    raw = client.hget(f"deletion:{number}", "deletion_date")
    return _parse_dt(raw) if raw else None


# ======== TRON TRANSACTION HASH DB ===========
def save_tron_tx_hash(tx_hash: str, user_id: int):
    key = f"tron:tx:{tx_hash}"
    if client.exists(key):
        return False, "ALREADY"
    client.hset(key, mapping={"tx_hash": tx_hash, "user_id": user_id})
    return True, "SAVED"


def get_tron_tx_hash(tx_hash: str) -> dict | bool:
    data = client.hgetall(f"tron:tx:{tx_hash}")
    return data if data else False


def remove_tron_tx_hash(tx_hash: str):
    key = f"tron:tx:{tx_hash}"
    if not client.exists(key):
        return False, "NOT_FOUND"
    client.delete(key)
    return True, "REMOVED"


# ========= RESTRICTED NOTIFY =========
def save_restricted_number(number: str, date=None):
    if date is None:
        date = get_current_datetime()
    if client.sismember("restricted:all", number):
        return False, "ALREADY"
    client.sadd("restricted:all", number)
    client.set(f"restricted:{number}", date.isoformat())
    return True, "SAVED"


def get_restricted_numbers():
    return list(client.smembers("restricted:all") or [])


def remove_restricted_number(number: str):
    if not client.sismember("restricted:all", number):
        return False, "NOT_FOUND"
    client.srem("restricted:all", number)
    client.delete(f"restricted:{number}")
    return True, "REMOVED"


def get_rest_num_date(number: str):
    raw = client.get(f"restricted:{number}")
    return _parse_dt(raw) if raw else None


def restricted_del_toggle():
    key = "rest_toggle"
    raw = client.get(key)
    if raw is not None:
        new_state = not (raw == "1")
        client.set(key, "1" if new_state else "0")
        return new_state
    client.set(key, "1")
    return True


def is_restricted_del_enabled():
    return client.get("rest_toggle") == "1"


# ========= MAINTENANCE =========
def delete_all_data():
    for key in client.scan_iter("*"):
        client.delete(key)
    return True, "ALL DATA DELETED"
