import json
import os
import ssl
import time
import redis.asyncio as redis
import config
from datetime import datetime, timezone, timedelta

# Cache for get_all_rentals() to avoid repeated full scans when multiple callers need it in one request.
# TTL 30 seconds: balances freshness with reducing N+1 calls (get_user_numbers, get_rental_by_owner, etc.).
_RENTALS_CACHE_TTL = 30.0
_rentals_cache = (0.0, [])

def _now():
    return datetime.now(timezone.utc)

# --- Redis ---
_redis_uri = (getattr(config, "REDIS_URI", None) or os.environ.get("REDIS_URL", "redis://localhost:6379/0")).strip()
if not (_redis_uri.startswith("redis://") or _redis_uri.startswith("rediss://") or _redis_uri.startswith("unix://")):
    _redis_uri = "redis://" + _redis_uri.lstrip("/")

# Force non-SSL for Azure Redis (port 18639 doesn't support SSL)
if "azure.cloud.redislabs.com" in _redis_uri and _redis_uri.startswith("rediss://"):
    _redis_uri = "redis://" + _redis_uri[8:]

# Use a connection pool so multiple concurrent requests don't queue on a single connection.
# Avoids blocking under load when many users hit the bot at once.
client = redis.from_url(_redis_uri, decode_responses=True, max_connections=50)

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

async def save_number(number: str, user_id: int, hours: int, date: datetime = None, extend: bool = False):
    """Save rental for user. Stores number in canonical +888 form and updates num_owner for fast lookup."""
    if date is None:
        date = _now()
    number = _norm_num(number) or number

    key = f"user:{user_id}"
    numbers_raw = await client.hget(key, "numbers")
    numbers = json.loads(numbers_raw) if numbers_raw else []

    for i, n in enumerate(numbers):
        if n.get("number") == number:
            if not extend:
                return False, "ALREADY"
            numbers[i]["hours"] = hours
            numbers[i]["date"] = date.isoformat()
            await client.hset(key, "numbers", json.dumps(numbers))
            return True, "UPDATED"

    numbers.append({"number": number, "hours": hours, "date": date.isoformat()})
    if not await client.exists(key):
        await client.hset(key, mapping={"user_id": user_id, "balance": 0, "numbers": json.dumps(numbers)})
        await client.sadd("users:all", user_id)
    else:
        await client.hset(key, "numbers", json.dumps(numbers))
    # Reverse index: number -> user_id so get_user_by_number() is O(1) instead of scanning all users.
    await client.hset("num_owner", number, user_id)
    return True, "SAVED"


async def get_user_by_number(number: str):
    number = _norm_num(number) or number
    uid = await client.hget("num_owner", number)
    if not uid:
        return False
    key = f"user:{uid}"
    numbers_raw = await client.hget(key, "numbers")
    if not numbers_raw:
        return False
    numbers = json.loads(numbers_raw)
    for n in numbers:
        if (_norm_num(n.get("number")) or n.get("number")) == number:
            date_s = n.get("date")
            return int(uid), n.get("hours", 0), _parse_dt(date_s) if date_s else None
    return False


async def get_numbers_by_user(user_id: int):
    key = f"user:{user_id}"
    numbers_raw = await client.hget(key, "numbers")
    if not numbers_raw:
        return []
    numbers = json.loads(numbers_raw)
    return [n.get("number", str(n)) for n in numbers if isinstance(n, dict) and "number" in n]


async def remove_number(number: str, user_id: int):
    number = _norm_num(number) or number
    num_canon = number

    key = f"user:{user_id}"
    numbers_raw = await client.hget(key, "numbers")
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
    await client.hset(key, "numbers", json.dumps(new_numbers))
    await client.hdel("num_owner", num_canon)
    return True, "REMOVED"


async def get_remaining_rent_days(number: str):
    user_data = await get_user_by_number(number)
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
async def save_number_data(number: str, user_id: int, rent_date: datetime, hours: int):
    """
    Store rental by canonical +888 number so get_number_data() fast path (rental:{number}) always hits.
    """
    hours = int(hours)
    number = _norm_num(number) or str(number or "").strip().replace(" ", "").replace("-", "")
    if number.startswith("888") and not number.startswith("+888") and len(number) >= 11:
        number = "+" + number
    expiry_date = rent_date + timedelta(hours=hours)
    key = f"rental:{number}"
    await client.hset(key, mapping={
        "number": number,
        "user_id": user_id,
        "rent_date": rent_date.isoformat(),
        "hours": hours,
        "expiry_date": expiry_date.isoformat(),
    })
    await client.zadd("rentals:expiry", {number: expiry_date.timestamp()})
    await client.sadd("rentals:all", number)
    await client.sadd(f"rentals:user:{user_id}", number)
    await client.expire(key, int(hours * 3600) + 86400)
    global _rentals_cache
    _rentals_cache = (0.0, [])  # Invalidate cache so get_all_rentals() sees new rental


def _normalize_for_lookup(s):
    """Normalize number for lookup; returns +888 form or None."""
    if s is None:
        return None
    s = str(s).strip().replace(" ", "").replace("-", "").replace("\ufeff", "")
    s = s.lstrip("\u002b\u066b\u066c\u2393\uff0b+")  # various plus signs
    # Convert fullwidth Unicode digits (０-９, ٠-٩, etc.) to ASCII
    _tbl = str.maketrans("０１２３４５６７８９٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    s = s.translate(_tbl)
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


async def get_number_data(number: str):
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
        data = await client.hgetall(f"rental:{cand}")
        if data:
            break
    if not data and n_norm:
        for stored in (await client.smembers("rentals:all") or []):
            stored = str(stored).strip() if stored else ""
            if _normalize_for_lookup(stored) == n_norm:
                data = await client.hgetall(f"rental:{stored}")
                if data:
                    break
    # Avoid client.keys("rental:*") — it's a full Redis scan and blocks under load.
    # All writes use canonical number (save_number_data), so fast path above should hit.
    # Only fall back to full rental scan via get_all_rentals() for legacy/migrated data.
    if not data and n_norm:
        for doc in await get_all_rentals():
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


async def get_rented_data_for_number(number: str):
    """Get rental data - tries get_number_data first, then get_all_rentals (same as admin export)."""
    data = await get_number_data(number)
    if data:
        return data
    n_norm = _normalize_for_lookup(number)
    if not n_norm:
        return None
    for doc in await get_all_rentals():
        if _normalize_for_lookup(doc.get("number")) == n_norm:
            return doc
    return None


async def get_rental_by_owner(user_id: int, number: str):
    """Find rental for this user+number. Uses get_all_rentals only - same source as admin export."""
    uid = int(user_id)
    num_clean = str(number or "").strip().replace(" ", "").replace("-", "")
    if not num_clean:
        return None
    # First try the tolerant lookup which checks rental keys and normalizes forms
    rented = await get_rented_data_for_number(num_clean)
    if rented and int(rented.get("user_id") or 0) == uid:
        return rented

    # normalize lookup form for comparisons
    num_norm = _normalize_for_lookup(num_clean)
    for doc in await get_all_rentals():
        if int(doc.get("user_id") or 0) != uid:
            continue
        doc_num = (doc.get("number") or "").strip()
        if not doc_num:
            continue
        # direct match (handles exact stored format)
        if doc_num == num_clean:
            return doc
        # try normalized comparison (handles +/no+ and formatting differences)
        doc_norm = _normalize_for_lookup(doc_num)
        if doc_norm and num_norm and doc_norm == num_norm:
            return doc
        # fallback: tolerant string compare removing + sign
        if doc_num.lstrip("+") == num_clean.lstrip("+"):
            return doc
    return None


async def get_user_numbers(user_id: int):
    """Return numbers rented by user. Uses rentals:user when present; fallback to get_all_rentals for legacy data."""
    members = await client.smembers(f"rentals:user:{user_id}")
    if members:
        return list(members)
    uid = int(user_id)
    return [
        doc.get("number") for doc in await get_all_rentals()
        if int(doc.get("user_id") or 0) == uid and doc.get("number")
    ]


async def remove_number_data(number: str):
    n = _norm_num(number) or str(number or "").strip()
    candidates = [n]
    if n.startswith("+888"):
        candidates.append(n[1:])
    elif n.startswith("888"):
        candidates.append("+" + n)
    for cand in candidates:
        key = f"rental:{cand}"
        if await client.exists(key):
            data = await client.hgetall(key)
            user_id = data.get("user_id")
            stored = data.get("number") or n
            async with client.pipeline() as pipe:
                pipe.delete(key)
                pipe.zrem("rentals:expiry", n)
                pipe.zrem("rentals:expiry", stored)
                pipe.srem("rentals:all", n)
                pipe.srem("rentals:all", stored)
                pipe.hdel("num_owner", n)
                pipe.hdel("num_owner", stored)
                if user_id:
                    pipe.srem(f"rentals:user:{user_id}", n)
                    pipe.srem(f"rentals:user:{user_id}", stored)
                await pipe.execute()
            global _rentals_cache
            _rentals_cache = (0.0, [])  # Invalidate cache after removal
            return True, "REMOVED"
    return False, "NOT_FOUND"


async def transfer_number(number: str, from_user_id: int, to_user_id: int):
    """Transfer a rented number to another user. Uses Redis lock to prevent concurrent transfer/rent races. Returns (True, None) or (False, error_msg)."""
    canon = _norm_num(number) or number
    acquired = await lock_number_for_rent(canon, from_user_id, ttl=60)
    if not acquired:
        return False, "Number is busy; try again in a moment."
    try:
        rented = await get_rental_by_owner(from_user_id, number)
        if not rented:
            return False, "Number not found"
        canon = _norm_num(rented.get("number") or number) or (rented.get("number") or number)
        rent_date = rented.get("rent_date")
        hours = int(rented.get("hours", 0) or 0)
        if not rent_date or not hours:
            return False, "Invalid rental data"
        await remove_number(canon, from_user_id)
        await remove_number_data(canon)
        await save_number(canon, to_user_id, hours, date=rent_date, extend=False)
        await save_number_data(canon, to_user_id, rent_date, hours)
        await append_transfer_history(canon, from_user_id, to_user_id)
        return True, None
    except Exception as e:
        import logging
        logging.exception("transfer_number error")
        return False, str(e)
    finally:
        await unlock_number_for_rent(canon)


async def get_expired_numbers():
    now = datetime.now(timezone.utc).timestamp()
    return list(await client.zrangebyscore("rentals:expiry", 0, now))


async def get_all_rentals():
    """
    Return all rentals. Cached for 30s so get_user_numbers(), get_rental_by_owner(), get_rented_data_for_number()
    don't each trigger a full rentals:all scan + N hgetalls in the same request.
    """
    global _rentals_cache
    now = time.monotonic()
    if now - _rentals_cache[0] < _RENTALS_CACHE_TTL and _rentals_cache[1]:
        return _rentals_cache[1]
    numbers = list(await client.smembers("rentals:all") or [])
    if not numbers:
        _rentals_cache = (now, [])
        return []
    async with client.pipeline() as pipe:
        for number in numbers:
            pipe.hgetall(f"rental:{number}")
        results = await pipe.execute()
    out = []
    for number, data in zip(numbers, results):
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
    _rentals_cache = (now, out)
    return out


# ========= USER IDS =========
async def save_user_id(user_id: int):
    key = f"user:{user_id}"
    if await client.exists(key):
        return False, "EXISTS"
    await client.hset(key, mapping={"user_id": user_id, "numbers": "[]", "balance": 0})
    await client.sadd("users:all", user_id)
    return True, "SAVED"


async def get_all_user_ids():
    members = await client.smembers("users:all")
    return [int(x) for x in (members or [])]


# ========= BALANCES =========
async def save_user_balance(user_id: int, balance: float | int):
    key = f"user:{user_id}"
    if not await client.exists(key):
        await client.hset(key, mapping={"user_id": user_id, "balance": balance, "numbers": "[]"})
        await client.sadd("users:all", user_id)
        return "CREATED"
    await client.hset(key, "balance", balance)
    return "UPDATED"


async def get_user_balance(user_id: int):
    balance = await client.hget(f"user:{user_id}", "balance")
    return float(balance) if balance is not None else None


async def get_total_balance():
    """
    Sum of all user balances. Uses a single Redis pipeline instead of N round-trips (one per user).
    """
    uids = list(await client.smembers("users:all") or [])
    if not uids:
        return 0.0, 0
    async with client.pipeline() as pipe:
        for uid in uids:
            pipe.hget(f"user:{uid}", "balance")
        results = await pipe.execute()
    total = 0.0
    count = 0
    for b in results:
        if b is not None:
            total += float(b)
            count += 1
    return total, count


# ========= ADMINS =========
async def add_admin(user_id: int):
    added = await client.sadd("admins:all", user_id)
    return (True, "ADDED") if added else (False, "ALREADY")


async def remove_admin(user_id: int):
    removed = await client.srem("admins:all", user_id)
    return (True, "REMOVED") if removed else (False, "NOT_FOUND")


async def is_admin(user_id: int):
    return await client.sismember("admins:all", user_id)


async def get_all_admins():
    members = await client.smembers("admins:all")
    return [int(x) for x in (members or [])]


# ========= NUMBERS POOL =========
async def save_number_info(number: str, price_30: float, price_60: float, price_90: float, available: bool = True):
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
    existed = await client.exists(key)
    await client.hset(key, mapping={
        "number": number,
        "prices": json.dumps(data["prices"]),
        "hours": json.dumps(data["hours"]),
        "available": str(available).lower(),
        "updated_at": data["updated_at"],
    })
    await client.sadd("pool:numbers", number)
    return "UPDATED" if existed else "CREATED"


async def edit_number_info(number: str, **kwargs):
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")
    key = f"number:{number}"
    if not await client.exists(key):
        return False, "NO_CHANGES"
    prices = json.loads(await client.hget(key, "prices") or "{}")
    updates = {}
    if "price_30" in kwargs:
        prices["30d"] = kwargs["price_30"]
    if "price_60" in kwargs:
        prices["60d"] = kwargs["price_60"]
    if "price_90" in kwargs:
        prices["90d"] = kwargs["price_90"]
    if "price_30" in kwargs or "price_60" in kwargs or "price_90" in kwargs:
        updates["prices"] = json.dumps(prices)
    if "available" in kwargs:
        updates["available"] = str(kwargs["available"]).lower()
    if not updates:
        return False, "NO_CHANGES"
    updates["updated_at"] = _now().isoformat()
    await client.hset(key, mapping=updates)
    return True, "UPDATED"


async def get_number_info(number: str) -> dict | bool:
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    key = f"number:{number}"
    data = await client.hgetall(key)
    if not data:
        return False
    return {
        "number": data.get("number"),
        "prices": json.loads(data.get("prices") or "{}"),
        "hours": json.loads(data.get("hours") or "{}"),
        "available": data.get("available", "true").lower() == "true",
        "updated_at": _parse_dt(data.get("updated_at")),
    }


async def get_all_pool_numbers():
    members = await client.smembers("pool:numbers")
    return list(members or [])


# ===================== language =====================
async def save_user_language(user_id: int, lang: str):
    await client.hset(f"lang:{user_id}", "language", lang)


async def get_user_language(user_id: int):
    return await client.hget(f"lang:{user_id}", "language")


# ========= User Payment Method =========
async def save_user_payment_method(user_id: int, method: str):
    await client.set(f"payment:{user_id}", method)


async def get_user_payment_method(user_id: int):
    method = await client.get(f"payment:{user_id}") or "cryptobot"
    return method if method != "tron" else "cryptobot"


# ========= TONKEEPER ORDERS =========
USDT_JETTON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"  # USDT on TON mainnet


async def _gen_order_ref() -> str:
    """Generate unique alphanumeric order ref (e.g. PayEFoT3YAg). No # to avoid URL encoding issues."""
    import random
    import string
    chars = string.ascii_letters + string.digits
    for _ in range(10):
        ref = "Pay" + "".join(random.choices(chars, k=8))
        if not await client.exists(f"ton_order:{ref}"):
            return ref
    return "Pay" + "".join(random.choices(chars, k=8)) + str(_now().timestamp())[-4:]


async def save_ton_order(order_ref: str, user_id: int, amount_usdt: float, amount_ton: float, payload: str, msg_id: int, chat_id: int, created_at=None):
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
    await client.hset(f"ton_order:{order_ref}", mapping=data)
    await client.zadd("ton_orders:pending", {order_ref: created_at.timestamp()})


async def get_ton_order(order_ref: str):
    data = await client.hgetall(f"ton_order:{order_ref}")
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


async def get_all_pending_ton_orders(max_age_seconds=1800):
    """Return pending orders. Expired ones (>max_age_seconds) are removed."""
    now = _now().timestamp()
    refs = list(await client.zrange("ton_orders:pending", 0, -1) or [])
    if not refs:
        return []
    async with client.pipeline() as pipe:
        for ref in refs:
            pipe.hgetall(f"ton_order:{ref}")
        results = await pipe.execute()
    orders = []
    for ref, data in zip(refs, results):
        try:
            if not data:
                await delete_ton_order(ref)
                continue
            o = {
                "user_id": int(data["user_id"]),
                "amount": float(data["amount"]),
                "amount_ton": float(data.get("amount_ton") or data["amount"]),
                "payload": data["payload"],
                "msg_id": int(data["msg_id"]),
                "chat_id": int(data["chat_id"]),
                "created_at": _parse_dt(data.get("created_at")),
            }
            created = o.get("created_at")
            if created and (now - created.timestamp()) > max_age_seconds:
                await delete_ton_order(ref)
                continue
            orders.append((ref, o))
        except (ValueError, TypeError, KeyError):
            await delete_ton_order(ref)
    return orders


async def delete_ton_order(order_ref: str):
    await client.delete(f"ton_order:{order_ref}")
    await client.zrem("ton_orders:pending", order_ref)


# ========= RULES =========
async def save_rules(rules: str, lang: str = "en"):
    await client.hset(f"rules:{lang}", mapping={"text": rules, "language": lang})


async def get_rules(lang: str = "en") -> str:
    text = await client.hget(f"rules:{lang}", "text")
    return text if text else "No rules set."


# ========= DELETE ACCOUNT =========
async def save_7day_deletion(number: str, date: datetime):
    await client.hset(f"deletion:{number}", "deletion_date", date.isoformat())
    await client.zadd("deletions:expiry", {number: date.timestamp()})


async def get_7day_deletions():
    now = _now().timestamp()
    return list(await client.zrangebyscore("deletions:expiry", 0, now))


async def remove_7day_deletion(number: str):
    key = f"deletion:{number}"
    if not await client.exists(key):
        return False
    await client.delete(key)
    await client.zrem("deletions:expiry", number)
    return True


async def get_7day_date(number: str):
    raw = await client.hget(f"deletion:{number}", "deletion_date")
    return _parse_dt(raw) if raw else None


# ========= RESTRICTED NOTIFY =========
async def save_restricted_number(number: str, date=None):
    if date is None:
        date = _now()
    if await client.sismember("restricted:all", number):
        return False, "ALREADY"
    await client.sadd("restricted:all", number)
    await client.set(f"restricted:{number}", date.isoformat())
    return True, "SAVED"


async def get_restricted_numbers():
    return list(await client.smembers("restricted:all") or [])


async def remove_restricted_number(number: str):
    if not await client.sismember("restricted:all", number):
        return False, "NOT_FOUND"
    await client.srem("restricted:all", number)
    await client.delete(f"restricted:{number}")
    return True, "REMOVED"


async def get_rest_num_date(number: str):
    raw = await client.get(f"restricted:{number}")
    return _parse_dt(raw) if raw else None


async def restricted_del_toggle():
    key = "rest_toggle"
    raw = await client.get(key)
    if raw is not None:
        new_state = not (raw == "1")
        await client.set(key, "1" if new_state else "0")
        return new_state
    await client.set(key, "1")
    return True


async def is_restricted_del_enabled():
    return await client.get("rest_toggle") == "1"


async def save_rental_atomic(user_id: int, number: str, new_balance: float, rent_date, new_hours: int):
    """Atomically deduct balance and save rental in a single Redis transaction. Also updates user:{user_id} numbers list."""
    if isinstance(rent_date, str):
        rent_date = _parse_dt(rent_date) or _now()
    elif rent_date is None:
        rent_date = _now()
    expiry = rent_date + timedelta(hours=new_hours)
    number = _norm_num(number) or str(number).strip()
    numbers_raw = await client.hget(f"user:{user_id}", "numbers")
    numbers = json.loads(numbers_raw) if numbers_raw else []
    if not any(n.get("number") == number for n in numbers):
        numbers.append({"number": number, "hours": new_hours, "date": rent_date.isoformat()})
    async with client.pipeline(transaction=True) as pipe:
        pipe.hset(f"user:{user_id}", "balance", new_balance)
        pipe.hset(f"user:{user_id}", "numbers", json.dumps(numbers))
        pipe.hset(f"rental:{number}", mapping={
            "number": number,
            "user_id": user_id,
            "rent_date": rent_date.isoformat(),
            "hours": new_hours,
            "expiry_date": expiry.isoformat(),
        })
        pipe.zadd("rentals:expiry", {number: expiry.timestamp()})
        pipe.sadd("rentals:all", number)
        pipe.sadd(f"rentals:user:{user_id}", number)
        pipe.hset("num_owner", number, user_id)
        await pipe.execute()
    global _rentals_cache
    _rentals_cache = (0.0, [])


async def lock_number_for_rent(number: str, user_id: int, ttl: int = 60) -> bool:
    """
    Acquire a short-lived lock on a number during checkout.
    Returns True if lock acquired, False if already locked by someone else.
    """
    key = f"renting:{number}"
    result = await client.set(key, str(user_id), nx=True, ex=ttl)
    return result is True


async def unlock_number_for_rent(number: str):
    """Release the checkout lock on a number."""
    await client.delete(f"renting:{number}")


async def get_number_lock_owner(number: str):
    """Returns user_id who holds the lock, or None."""
    val = await client.get(f"renting:{number}")
    return int(val) if val else None


async def append_transfer_history(number: str, from_user_id: int, to_user_id: int):
    """Append an immutable transfer record for a number (audit trail)."""
    number = _norm_num(number) or number
    key = f"transfer_history:{number}"
    entry = json.dumps({
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "timestamp": _now().isoformat(),
    })
    await client.rpush(key, entry)
    await client.ltrim(key, -1000, -1)  # Keep last 1000 entries per number


async def get_transfer_history(number: str, limit: int = 50):
    """Return recent transfer history for a number (newest last)."""
    number = _norm_num(number) or number
    key = f"transfer_history:{number}"
    raw = await client.lrange(key, -limit, -1)
    out = []
    for s in (raw or []):
        try:
            out.append(json.loads(s))
        except (json.JSONDecodeError, TypeError):
            pass
    return out


# ========= RATE LIMITING =========
async def check_rate_limit(user_id: int, action: str, max_per_window: int, window_secs: int) -> bool:
    """Returns True if allowed (under limit), False if rate limited."""
    key = f"ratelimit:{user_id}:{action}"
    async with client.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window_secs)
        results = await pipe.execute()
    count = results[0]
    return count <= max_per_window


# ========= PAYMENT REPLAY PROTECTION =========
_PROCESSED_TTL = 365 * 24 * 3600  # 1 year


async def is_payment_processed_crypto(inv_id: str) -> bool:
    """True if this CryptoBot invoice was already processed (replay protection)."""
    return await client.exists(f"processed_crypto:{inv_id}")


async def mark_payment_processed_crypto(inv_id: str):
    await client.set(f"processed_crypto:{inv_id}", "1", ex=_PROCESSED_TTL)


async def is_payment_processed_ton(order_ref: str) -> bool:
    """True if this TON order was already processed (replay protection)."""
    return await client.exists(f"processed_ton:{order_ref}")


async def mark_payment_processed_ton(order_ref: str):
    await client.set(f"processed_ton:{order_ref}", "1", ex=_PROCESSED_TTL)


# ========= ADMIN AUDIT LOG =========
async def log_admin_action(admin_id: int, action: str, target: str, details: str = None):
    """Append an immutable admin action log entry."""
    entry = json.dumps({
        "admin_id": admin_id,
        "action": action,
        "target": str(target),
        "timestamp": _now().isoformat(),
        "details": details or "",
    })
    await client.rpush("admin_audit_log", entry)
    await client.ltrim("admin_audit_log", -50000, -1)  # Keep last 50k entries


async def record_revenue(user_id: int, number: str, amount: float, hours: int):
    """Record a completed rental payment for revenue tracking."""
    now = _now()
    entry = {
        "user_id": user_id,
        "number": number,
        "amount": str(amount),
        "hours": hours,
        "timestamp": now.isoformat(),
    }
    key = f"revenue:{now.strftime('%Y%m')}:{user_id}:{now.timestamp()}"
    await client.hset(key, mapping=entry)
    await client.zadd("revenue:all", {key: now.timestamp()})
    # Increment total
    await client.incrbyfloat("revenue:total", amount)


async def get_total_revenue() -> float:
    """Get total revenue across all time."""
    val = await client.get("revenue:total")
    return float(val) if val else 0.0


# ========= MAINTENANCE =========
async def delete_all_data():
    async for key in client.scan_iter("*"):
        await client.delete(key)
    return True, "ALL DATA DELETED"
