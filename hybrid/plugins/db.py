# (©) @Hybrid_Vamp - https://github.com/hybridvamp
# Redis-only database

import json
import os
import ssl
import redis
import config
from datetime import datetime, timezone, timedelta

def _now():
    return datetime.now(timezone.utc)

# --- Redis ---
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
    client = redis.Redis.from_url(_redis_uri, **_kwargs)
else:
    client = redis.Redis.from_url(_redis_uri, decode_responses=True)

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
def _norm_num(n):
    s = str(n or "").strip().replace(" ", "").replace("-", "")
    if s.startswith("+888") and len(s) >= 12:
        return s
    if s.startswith("888") and len(s) >= 11:
        return "+" + s
    return s if s.startswith("+888") else None

def save_number(number: str, user_id: int, hours: int, date: datetime = None, extend: bool = False):
    if date is None:
        date = _now()
    number = _norm_num(number) or number

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
    number = _norm_num(number) or number

    for uid in client.smembers("users:all"):
        key = f"user:{uid}"
        numbers_raw = client.hget(key, "numbers")
        if not numbers_raw:
            continue
        numbers = json.loads(numbers_raw)
        for n in numbers:
            if n.get("number") == number:
                date_s = n.get("date")
                return int(uid), n.get("hours", 0), _parse_dt(date_s) if date_s else None
    return False


def get_numbers_by_user(user_id: int):
    key = f"user:{user_id}"
    numbers_raw = client.hget(key, "numbers")
    if not numbers_raw:
        return []
    numbers = json.loads(numbers_raw)
    return [n.get("number", str(n)) for n in numbers if isinstance(n, dict) and "number" in n]


def remove_number(number: str, user_id: int):
    number = _norm_num(number) or number
    num_canon = number

    key = f"user:{user_id}"
    numbers_raw = client.hget(key, "numbers")
    if not numbers_raw:
        return False, "NOT_FOUND"
    numbers = json.loads(numbers_raw)
    new_numbers = []
    for n in numbers:
        stored = n.get("number")
        if not stored:
            new_numbers.append(n)
            continue
        stored_norm = _norm_num(stored) or stored
        if stored_norm == num_canon or stored == number:
            continue  # skip - removing this one
        new_numbers.append(n)
    if len(new_numbers) == len(numbers):
        return False, "NOT_FOUND"
    client.hset(key, "numbers", json.dumps(new_numbers))
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
    number = _norm_num(number) or str(number or "").strip().replace(" ", "").replace("-", "")
    if number.startswith("888") and not number.startswith("+888") and len(number) >= 11:
        number = "+" + number
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


def _normalize_for_lookup(s):
    """Normalize number for lookup; returns +888 form or None."""
    if s is None:
        return None
    s = str(s).strip().replace(" ", "").replace("-", "").replace("\ufeff", "")
    s = s.lstrip("\u002b\u066b\u066c\u2393\uff0b+")  # various plus signs
    if not s or not s.isdigit():
        return None
    if s.startswith("888") and len(s) >= 11:
        return "+" + s
    if s.startswith("888") and len(s) == 8:
        return "+888" + s
    if len(s) == 8 and s.isdigit():
        return "+888" + s
    if s.startswith("+888") and len(s) >= 12:
        return s
    return None


def get_number_data(number: str):
    n = str(number or "").strip().replace(" ", "").replace("-", "")
    if not n:
        return None
    if not n.startswith("+888") and n.startswith("888") and len(n) >= 11:
        n = "+" + n
    if n.startswith("+") and not n.startswith("+888"):
        return None
    candidates = [n]
    if n.startswith("+888"):
        candidates.append(n[1:])
    elif n.startswith("888"):
        candidates.append("+" + n)
    data = None
    n_norm = _normalize_for_lookup(n)
    for cand in candidates:
        data = client.hgetall(f"rental:{cand}")
        if data:
            break
    if not data and n_norm:
        for stored in (client.smembers("rentals:all") or []):
            stored = str(stored).strip() if stored else ""
            if _normalize_for_lookup(stored) == n_norm:
                data = client.hgetall(f"rental:{stored}")
                if data:
                    break
    if not data and n_norm:
        for key in (client.keys("rental:*") or []):
            key = key if isinstance(key, str) else key.decode("utf-8", errors="ignore")
            if not key.startswith("rental:"):
                continue
            data = client.hgetall(key)
            if not data:
                continue
            stored_num = (data.get("number") or "")
            if hasattr(stored_num, "decode"):
                stored_num = stored_num.decode("utf-8", errors="ignore")
            stored_num = str(stored_num).strip()
            if _normalize_for_lookup(stored_num) == n_norm:
                break
        else:
            data = None
    if not data and n_norm:
        for doc in get_all_rentals():
            stored_num = (doc.get("number") or "")
            if _normalize_for_lookup(stored_num) == n_norm:
                data = {
                    "number": doc.get("number"),
                    "user_id": str(doc.get("user_id", "")),
                    "hours": str(doc.get("hours", 0)),
                    "rent_date": doc.get("rent_date").isoformat() if doc.get("rent_date") else "",
                    "expiry_date": doc.get("expiry_date").isoformat() if doc.get("expiry_date") else "",
                }
                break
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
    n = _norm_num(number) or str(number or "").strip()
    candidates = [n]
    if n.startswith("+888"):
        candidates.append(n[1:])
    elif n.startswith("888"):
        candidates.append("+" + n)
    for cand in candidates:
        key = f"rental:{cand}"
        if client.exists(key):
            data = client.hgetall(key)
            user_id = data.get("user_id")
            stored = data.get("number") or n
            pipe = client.pipeline()
            pipe.delete(key)
            pipe.zrem("rentals:expiry", n)
            pipe.zrem("rentals:expiry", stored)
            pipe.srem("rentals:all", n)
            pipe.srem("rentals:all", stored)
            if user_id:
                pipe.srem(f"rentals:user:{user_id}", n)
                pipe.srem(f"rentals:user:{user_id}", stored)
            pipe.execute()
            return True, "REMOVED"
    return False, "NOT_FOUND"


def transfer_number(number: str, from_user_id: int, to_user_id: int):
    """Transfer a rented number to another user. Returns (True, None) or (False, error_msg)."""
    try:
        num = _norm_num(number)
        if not num:
            return False, "Invalid number format"
        rented = get_number_data(num)
        if not rented:
            return False, "Number not found"
        if int(rented.get("user_id", 0)) != from_user_id:
            return False, "You do not own this number"
        rent_date = rented.get("rent_date")
        hours = int(rented.get("hours", 0) or 0)
        if not rent_date or not hours:
            return False, "Invalid rental data"
        canon = rented.get("number") or num
        canon = _norm_num(canon) or canon
        remove_number(canon, from_user_id)
        remove_number_data(canon)
        save_number(canon, to_user_id, hours, date=rent_date, extend=False)
        save_number_data(canon, to_user_id, rent_date, hours)
        return True, None
    except Exception as e:
        import logging
        logging.exception("transfer_number error")
        return False, str(e)


def get_expired_numbers():
    now = datetime.now(timezone.utc).timestamp()
    return list(client.zrangebyscore("rentals:expiry", 0, now))


def get_all_rentals():
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

    now = _now()
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
    if "price_30" in kwargs:
        prices = json.loads(client.hget(key, "prices") or "{}")
        prices["30d"] = kwargs["price_30"]
        updates["prices"] = json.dumps(prices)
    if "price_60" in kwargs:
        prices = json.loads(client.hget(key, "prices") or "{}")
        prices["60d"] = kwargs["price_60"]
        updates["prices"] = json.dumps(prices)
    if "price_90" in kwargs:
        prices = json.loads(client.hget(key, "prices") or "{}")
        prices["90d"] = kwargs["price_90"]
        updates["prices"] = json.dumps(prices)
    if "available" in kwargs:
        updates["available"] = str(kwargs["available"]).lower()
    if not updates:
        return False, "NO_CHANGES"
    updates["updated_at"] = _now().isoformat()
    client.hset(key, mapping=updates)
    return True, "UPDATED"


def get_number_info(number: str) -> dict | bool:
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    key = f"number:{number}"
    data = client.hgetall(key)
    if not data:
        return False
    return {
        "number": data.get("number"),
        "prices": json.loads(data.get("prices") or "{}"),
        "hours": json.loads(data.get("hours") or "{}"),
        "available": data.get("available", "true").lower() == "true",
        "updated_at": _parse_dt(data.get("updated_at")),
    }


def get_all_pool_numbers():
    keys = client.keys("number:*")
    return [k.replace("number:", "", 1) for k in (keys or [])]


# ===================== language =====================
def save_user_language(user_id: int, lang: str):
    client.hset(f"lang:{user_id}", "language", lang)


def get_user_language(user_id: int):
    return client.hget(f"lang:{user_id}", "language")


# ========= User Payment Method =========
def save_user_payment_method(user_id: int, method: str):
    client.set(f"payment:{user_id}", method)


def get_user_payment_method(user_id: int):
    method = client.get(f"payment:{user_id}") or "cryptobot"
    return method if method != "tron" else "cryptobot"


# ========= TONKEEPER ORDERS =========
USDT_JETTON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"  # USDT on TON mainnet


def _gen_order_ref() -> str:
    """Generate unique alphanumeric order ref (e.g. PayEFoT3YAg). No # to avoid URL encoding issues."""
    import random
    import string
    chars = string.ascii_letters + string.digits
    for _ in range(10):
        ref = "Pay" + "".join(random.choices(chars, k=8))
        if not client.exists(f"ton_order:{ref}"):
            return ref
    return "Pay" + "".join(random.choices(chars, k=8)) + str(_now().timestamp())[-4:]


def save_ton_order(order_ref: str, user_id: int, amount_usdt: float, amount_ton: float, payload: str, msg_id: int, chat_id: int, created_at=None):
    """order_ref: unique alphanumeric (e.g. PayEFoT3YAg). No # in memo for Tonkeeper compatibility."""
    if created_at is None:
        created_at = _now()
    data = {
        "user_id": user_id,
        "amount": str(amount_usdt),
        "amount_ton": str(amount_ton),
        "payload": payload,
        "msg_id": msg_id,
        "chat_id": chat_id,
        "created_at": created_at.isoformat(),
    }
    client.hset(f"ton_order:{order_ref}", mapping=data)
    client.zadd("ton_orders:pending", {order_ref: created_at.timestamp()})


def get_ton_order(order_ref: str):
    data = client.hgetall(f"ton_order:{order_ref}")
    if not data:
        return None
    return {
        "user_id": int(data["user_id"]),
        "amount": float(data["amount"]),
        "amount_ton": float(data.get("amount_ton") or data["amount"]),
        "payload": data["payload"],
        "msg_id": int(data["msg_id"]),
        "chat_id": int(data["chat_id"]),
        "created_at": _parse_dt(data.get("created_at")),
    }


def get_all_pending_ton_orders(max_age_seconds=1800):
    """Return pending orders. Expired ones (>max_age_seconds) are removed."""
    now = _now().timestamp()
    refs = client.zrange("ton_orders:pending", 0, -1)
    orders = []
    for ref in refs:
        try:
            o = get_ton_order(ref)
            if not o:
                delete_ton_order(ref)
                continue
            created = o.get("created_at")
            if created and (now - created.timestamp()) > max_age_seconds:
                delete_ton_order(ref)
                continue
            orders.append((ref, o))
        except (ValueError, TypeError):
            pass
    return orders


def delete_ton_order(order_ref: str):
    client.delete(f"ton_order:{order_ref}")
    client.zrem("ton_orders:pending", order_ref)


# ========= RULES =========
def save_rules(rules: str, lang: str = "en"):
    client.hset(f"rules:{lang}", mapping={"text": rules, "language": lang})


def get_rules(lang: str = "en") -> str:
    text = client.hget(f"rules:{lang}", "text")
    return text if text else "No rules set."


# ========= DELETE ACCOUNT =========
def save_7day_deletion(number: str, date: datetime):
    client.hset(f"deletion:{number}", "deletion_date", date.isoformat())
    client.zadd("deletions:expiry", {number: date.timestamp()})


def get_7day_deletions():
    now = _now().timestamp()
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


# ========= RESTRICTED NOTIFY =========
def save_restricted_number(number: str, date=None):
    if date is None:
        date = _now()
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
