# (©) @Hybrid_Vamp - https://github.com/hybridvamp

from pymongo import MongoClient
import config
from datetime import datetime, timezone, timedelta
from hybrid.plugins.func import get_current_datetime

client = MongoClient(config.DB_URI)
db = client["userdb"]
users_col = db["users"]
admins_col = db["admins"]
number_col = db["numbers"]
lang_col = db["languages"]
numbers_col = db["numbers"]
rules_col = db["rules"]
rental_col = db["rentals"]
delaccol = db["deletions"]
toncol = db["ton_tx"]
restrictedcol = db["restricted_numbers"]
rest_toggle_col = db["restricted_toggle"]
payment_col = db["payment_methods"]


# ========= USER NUMBERS =========
def save_number(number: str, user_id: int, hours: int, date: datetime =  get_current_datetime(), extend: bool = False):
    """Save or extend a number for a user.

    - If the number exists and extend=False → return False, "ALREADY"
    - If the number exists and extend=True → update hours → return True, "UPDATED"
    - If the number doesn't exist → insert → return True, "SAVED"
    """
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    existing = users_col.find_one(
        {"user_id": user_id, "numbers.number": number}
    )

    if existing:
        if not extend:
            return False, "ALREADY"
        # ✅ update existing hours
        users_col.update_one(
            {"user_id": user_id, "numbers.number": number},
            {"$set": {"numbers.$.hours": hours, "numbers.$.date": date}}
        )
        return True, "UPDATED"

    now = date
    users_col.update_one(
        {"user_id": user_id},
        {"$push": {"numbers": {"number": number, "hours": hours, "date": now}}},
        upsert=True
    )
    return True, "SAVED"

def get_user_by_number(number: str):
    """Get user_id, hours, date by number."""
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    record = users_col.find_one(
        {"numbers.number": number},
        {"user_id": 1, "numbers.$": 1}
    )
    if record and "numbers" in record:
        num = record["numbers"][0]
        return record["user_id"], num["hours"], num["date"]
    return False

def get_numbers_by_user(user_id: int):
    record = users_col.find_one({"user_id": user_id}, {"numbers": 1})
    if not record:
        return []
    return [n["number"] if isinstance(n, dict) and "number" in n else str(n) for n in record.get("numbers", [])]

def remove_number(number: str, user_id: int):
    """Remove a number from a user's list."""
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    result = users_col.update_one(
        {"user_id": user_id},
        {"$pull": {"numbers": {"number": number}}}
    )
    return (True, "REMOVED") if result.modified_count else (False, "NOT_FOUND")

def get_remaining_rent_days(number: str):
    """Return remaining rent days for a number, or None if not found."""
    user_data = get_user_by_number(number)
    if not user_data:
        return None

    user_id, hours, rented_date = user_data
    now = get_current_datetime()
    elapsed = now - rented_date
    elapsed_hours = elapsed.total_seconds() / 3600
    remaining_hours = hours - elapsed_hours
    return max(0, int(remaining_hours // 24)), max(0, int(remaining_hours % 24))


# =========== Number Rent Data ============
def save_number_data(number: str, user_id: int, rent_date: datetime, hours: int):
    """
    Save or update rental data for a number.
    """
    hours = int(hours)
    expiry_date = rent_date + timedelta(hours=hours)
    rental_col.update_one(
        {"number": number},
        {"$set": {
            "user_id": user_id,
            "rent_date": rent_date,
            "hours": hours,
            "expiry_date": expiry_date
        }},
        upsert=True
    )

def get_number_data(number: str):
    """
    Get saved data for a number.
    Returns None if not rented.
    """
    return rental_col.find_one({"number": number})

def get_user_numbers(user_id: int):
    """
    Returns list of numbers rented by a user.
    """
    rented = rental_col.find({"user_id": user_id})
    return [doc["number"] for doc in rented if "number" in doc]

def remove_number_data(number: str):
    """
    Remove rental data for a number.
    """
    result = rental_col.delete_one({"number": number})
    return (True, "REMOVED") if result.deleted_count else (False, "NOT_FOUND")


# ========= USER IDS =========
def save_user_id(user_id: int):
    if users_col.find_one({"user_id": user_id}):
        return False, "EXISTS"
    users_col.insert_one({"user_id": user_id, "numbers": [], "balance": 0})
    return True, "SAVED"

def get_all_user_ids():
    """Return all user IDs in DB."""
    return users_col.distinct("user_id")


# ========= BALANCES =========
def save_user_balance(user_id: int, balance: float | int):
    """
    Replace the user's balance with a new value.
    Always overwrites the old balance.
    """
    result = users_col.update_one(
        {"user_id": user_id},
        {"$set": {"balance": balance}},
        upsert=True
    )
    return "CREATED" if result.matched_count == 0 else "UPDATED"

def get_user_balance(user_id: int):
    """Get a user's balance."""
    record = users_col.find_one({"user_id": user_id}, {"balance": 1})
    return record.get("balance") if record else None

def get_total_balance():
    """
    Return the total balance of all users combined
    and the number of users who have a balance field.
    """
    pipeline = [
        {"$match": {"balance": {"$exists": True}}},
        {"$group": {"_id": None, "total_balance": {"$sum": "$balance"}, "user_count": {"$sum": 1}}}
    ]

    result = list(users_col.aggregate(pipeline))
    if result:
        return result[0]["total_balance"], result[0]["user_count"]
    return 0.0, 0


# ========= ADMINS =========
def add_admin(user_id: int):
    if admins_col.find_one({"user_id": user_id}):
        return False, "ALREADY"
    admins_col.insert_one({"user_id": user_id})
    return True, "ADDED"

def remove_admin(user_id: int):
    result = admins_col.delete_one({"user_id": user_id})
    return (True, "REMOVED") if result.deleted_count else (False, "NOT_FOUND")

def is_admin(user_id: int):
    return admins_col.find_one({"user_id": user_id}) is not None

def get_all_admins():
    admins = admins_col.find({}, {"_id": 0, "user_id": 1})
    return [a["user_id"] for a in admins]


# ========= NUMBERS POOL =========
def save_number_info(number: str, price_30: float, price_60: float, price_90: float, available: bool = True):
    """Create or update number details with rates & hours for 30/60/90 days."""
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    data = {
        "number": number,
        "prices": {
            "30d": price_30,
            "60d": price_60,
            "90d": price_90
        },
        "hours": {
            "30d": 30 * 24,
            "60d": 60 * 24,
            "90d": 90 * 24
        },
        "available": available,
        "updated_at": get_current_datetime()
    }

    result = number_col.update_one(
        {"number": number},
        {"$set": data},
        upsert=True
    )
    return "CREATED" if result.matched_count == 0 else "UPDATED"

def edit_number_info(number: str, **kwargs):
    """
    Edit specific details of a number.
    Example: edit_number_info("+88812345", price_30=120, available=False)
    """
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    updates = {}
    if "price_30" in kwargs:
        updates["prices.30d"] = kwargs["price_30"]
    if "price_60" in kwargs:
        updates["prices.60d"] = kwargs["price_60"]
    if "price_90" in kwargs:
        updates["prices.90d"] = kwargs["price_90"]
    if "available" in kwargs:
        updates["available"] = kwargs["available"]

    if not updates:
        return False, "NO_CHANGES"

    updates["updated_at"] = get_current_datetime()

    number_col.update_one({"number": number}, {"$set": updates})
    return True, "UPDATED"

def get_number_info(number: str) -> dict | bool:
    """Return all data for a given number, or False if not found."""
    if not number.startswith("+888"):
        number = "+888" + number.lstrip("+")

    record = number_col.find_one({"number": number}, {"_id": 0})  # exclude _id
    return record if record else False


# ===================== language db ===================== #
def save_user_language(user_id: int, lang: str):
    lang_col.update_one({"user_id": user_id}, {"$set": {"language": lang}}, upsert=True)

def get_user_language(user_id: int):
    user = lang_col.find_one({"user_id": user_id})
    return user.get("language") if user else None


# ========= User Payment Method =========
def save_user_payment_method(user_id: int, method: str):
    payment_col.update_one({"user_id": user_id}, {"$set": {"payment_method": method}}, upsert=True)

def get_user_payment_method(user_id: int):
    user = payment_col.find_one({"user_id": user_id})
    return user.get("payment_method") if user else "cryptobot"

# ========= RULES =========
def save_rules(rules: str, lang: str = "en"):
    """Save or update the rules text for a specific language."""
    rules_col.update_one(
        {"_id": f"rules_{lang}"},
        {"$set": {"text": rules, "language": lang}},
        upsert=True
    )

def get_rules(lang: str = "en") -> str:
    """Get the saved rules text for a specific language."""
    record = rules_col.find_one({"_id": f"rules_{lang}"})
    return record.get("text") if record else "No rules set."


# ========= DELETE ACCOUNT DB =========
def save_7day_deletion(number: str, date: datetime):
    """Mark a number as scheduled for deletion in 7 days."""
    delaccol.update_one(
        {"number": number},
        {"$set": {"deletion_date": date}},
        upsert=True
    )

def get_7day_deletions():
    """Return list of numbers scheduled for deletion."""
    now = get_current_datetime()
    deletions = delaccol.find({"deletion_date": {"$lte": now}})
    return [doc["number"] for doc in deletions if "number" in doc]

def remove_7day_deletion(number: str):
    """Remove the deletion_date field for a number."""
    result = delaccol.update_one(
        {"number": number},
        {"$unset": {"deletion_date": ""}}
    )
    return result.modified_count > 0

def get_7day_date(number: str):
    """Get the scheduled deletion date for a number."""
    record = delaccol.find_one({"number": number}, {"deletion_date": 1})
    return record.get("deletion_date") if record and "deletion_date" in record else None


# ======== TON TRANSACTION HASH DB ===========
def save_ton_tx_hash(tx_hash: str, user_id: int):
    if toncol.find_one({"tx_hash": tx_hash}):
        return False, "ALREADY"
    toncol.insert_one({
        "tx_hash": tx_hash,
        "user_id": user_id,
    })
    return True, "SAVED"

def get_ton_tx_hash(tx_hash: str) -> dict | bool:
    """Get a TON transaction hash."""
    return toncol.find_one({"tx_hash": tx_hash}, {"_id": 0})

def remove_ton_tx_hash(tx_hash: str):
    result = toncol.delete_one({"tx_hash": tx_hash})
    return (True, "REMOVED") if result.deleted_count else (False, "NOT_FOUND")

# ========= RESTRICTED NOTIFY =========
def save_restricted_number(number: str, date = get_current_datetime()):
    if restrictedcol.find_one({"number": number}):
        return False, "ALREADY"
    restrictedcol.insert_one({"number": number, "date": date})
    return True, "SAVED"

def get_restricted_numbers():
    restricted = restrictedcol.find({}, {"_id": 0, "number": 1})
    return [r["number"] for r in restricted if "number" in r]

def remove_restricted_number(number: str):
    result = restrictedcol.delete_one({"number": number})
    return (True, "REMOVED") if result.deleted_count else (False, "NOT_FOUND")

def get_rest_num_date(number: str):
    record = restrictedcol.find_one({"number": number}, {"date": 1})
    return record.get("date") if record and "date" in record else None

def restricted_del_toggle():
    """Toggle for Delete restricted numbers older than 3 days."""
    toggle = rest_toggle_col.find_one({"_id": "rest_del_toggle"})
    if toggle:
        new_state = not toggle.get("enabled", False)
        rest_toggle_col.update_one({"_id": "rest_del_toggle"}, {"$set": {"enabled": new_state}})
        return new_state
    else:
        rest_toggle_col.insert_one({"_id": "rest_del_toggle", "enabled": True})
        return True

def is_restricted_del_enabled():
    toggle = rest_toggle_col.find_one({"_id": "rest_del_toggle"})
    return toggle.get("enabled", False) if toggle else False
    


# ========= MAINTENANCE =========
def delete_all_data():
    users_col.delete_many({})
    admins_col.delete_many({})
    number_col.delete_many({})
    lang_col.delete_many({})
    numbers_col.delete_many({})
    rules_col.delete_many({})
    rental_col.delete_many({})
    delaccol.delete_many({})
    toncol.delete_many({})
    restrictedcol.delete_many({})
    rest_toggle_col.delete_many({})
    payment_col.delete_many({})
    return True, "ALL DATA DELETED"

