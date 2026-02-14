import json
import math
import asyncio
import logging
import random
import requests
import traceback
import csv

from os import execvp
from sys import executable
from datetime import datetime, timedelta, timezone


from pyrogram import Client, types
from pyrogram.raw import functions, types
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    SessionPasswordNeeded,
    FloodWait,
    PhoneCodeInvalid,
    PhoneNumberUnoccupied,
    PhoneNumberBanned,
    RPCError
)

from hybrid.plugins.temp import temp
from config import LANGUAGES, D30_RATE, D60_RATE, D90_RATE, API_ID, API_HASH, USDT_ADDRESS


def get_current_datetime():
    return datetime.now(timezone.utc)

def fetch_progress(current, total, length=10):
    if total == 0:
        return "Total cannot be zero."
    percentage = int((current / total) * 100)
    filled_length = int(length * current // total)
    empty_length = length - filled_length
    progress_bar = '▥' * filled_length + '▢' * empty_length
    return f"[{progress_bar}] {percentage}%"

def restart(session_name, m: Message):
    if m:
        restart_handler(session_name, m.id,  m.chat.id)
    execvp(executable, [executable, "-m", "hybrid"])

def check_proxy(pro_xy):
    proxy = {
        "http": f"{pro_xy}",
        "https": f"{pro_xy}"
    }

    url = "http://httpbin.org/ip"

    try:
        response = requests.get(url, proxies=proxy, timeout=10)
        if response.status_code == 200:
            return True
        else:
            return False
    except Exception as e:
        return False

def restart_handler(session_name, msg_id=None, user_id=None):
    try:
        with open("restart.json", "r") as f:
            restart_data = json.load(f)
    except FileNotFoundError:
        restart_data = {}
    except json.JSONDecodeError:
        restart_data = {}

    if msg_id is None or user_id is None:
        if session_name in restart_data:
            return restart_data[session_name]
        else:
            return None

    if session_name not in restart_data:
        restart_data[session_name] = {}
    restart_data[session_name]['message_id'] = msg_id
    restart_data[session_name]['user_id'] = user_id

    with open("restart.json", "w") as f:
        json.dump(restart_data, f, indent=4)
    return restart_data[session_name]

def get_restart_data(session_name):
    try:
        with open("restart.json", "r") as f:
            restart_data = json.load(f)
            msg_id = restart_data.get(session_name, {}).get('message_id')
            user_id = restart_data.get(session_name, {}).get('user_id')
            return msg_id, user_id
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None

def _normalize_hours(total_hours) -> float:
    """Convert total_hours to float safely (int, float, or str)."""
    try:
        return float(total_hours)
    except (TypeError, ValueError):
        return 0.0

def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if dt is None:
        return get_current_datetime()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def format_remaining_time(start_date: datetime, total_hours) -> str:
    """Return remaining time as 'X days Yh Zm'."""
    start_date = _ensure_utc(start_date)
    total_hours = _normalize_hours(total_hours)

    expiry = start_date + timedelta(hours=total_hours)
    now = get_current_datetime().replace(tzinfo=timezone.utc)
    remaining = expiry - now

    if remaining.total_seconds() <= 0:
        return "Expired"

    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} days")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "0m"

def get_remaining_hours(start_date: datetime, total_hours) -> int:
    """Return remaining hours as integer."""
    start_date = _ensure_utc(start_date)
    total_hours = _normalize_hours(total_hours)

    expiry = start_date + timedelta(hours=total_hours)
    now = get_current_datetime()
    remaining = expiry - now

    if remaining.total_seconds() <= 0:
        return 0

    return max(0, int(remaining.total_seconds() // 3600))

def get_numbers_page(page: int = 1, per_page: int = 10):
    total = len(temp.NUMBE_RS)
    pages = math.ceil(total / per_page)
    start = (page - 1) * per_page
    end = start + per_page
    return temp.NUMBE_RS[start:end], pages

async def show_numbers(query, page: int = 1):
    numbers, pages = get_numbers_page(page)
    kb = []

    for num in numbers:
        kb.append([InlineKeyboardButton(num, callback_data=f"admin_number_{num}_{page}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_numbers_page_{page-1}"))
    if page < pages:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"admin_numbers_page_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("Back to Admin Menu", callback_data="admin_panel")])

    await query.message.edit_text(
        f"📞 **Available Numbers** (Page {page}/{pages})",
        reply_markup=InlineKeyboardMarkup(kb)
    )

def t(user_id: int, key: str, **kwargs):
    from hybrid.plugins.db import get_user_language
    lang = get_user_language(user_id) or "en"
    text = LANGUAGES.get(lang, LANGUAGES["en"]).get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text

from hybrid.plugins.db import get_number_data, get_number_info, save_number_info

NUMBERS_PER_PAGE = 8

def build_rentnum_keyboard(user_id: int, page: int = 0):
    filtered_numbers = temp.AVAILABLE_NUM
    filtered_numbers = [num for num in filtered_numbers if num not in temp.UN_AV_NUMS]
    seen = set()
    filtered_numbers = [x for x in filtered_numbers if not (x in seen or seen.add(x))]

    available_nums = [n for n in filtered_numbers if n not in temp.RENTED_NUMS]
    rented_nums = [n for n in filtered_numbers if n in temp.RENTED_NUMS]

    ordered_numbers = available_nums + rented_nums

    start = page * NUMBERS_PER_PAGE
    end = start + NUMBERS_PER_PAGE
    numbers_page = ordered_numbers[start:end]

    keyboard = []

    for number in numbers_page:
        if number in temp.RENTED_NUMS:
            status = " 🔴"  # rented/unavailable
        else:
            status = " 🟢"  # available

        keyboard.append([
            InlineKeyboardButton(f"{number} {status}", callback_data=f"numinfo:{number}:{page}")
        ])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(t(user_id, "back"), callback_data=f"rentnum_page:{page-1}"))
        nav_row.append(InlineKeyboardButton(f"Page {page+1}/{math.ceil(len(ordered_numbers) / NUMBERS_PER_PAGE)}", callback_data="pagenumber"))
    if end < len(ordered_numbers):
        if page == 0:
            nav_row.append(InlineKeyboardButton(f"Page {page+1}/{math.ceil(len(ordered_numbers) / NUMBERS_PER_PAGE)}", callback_data="pagenumber"))
        nav_row.append(InlineKeyboardButton(t(user_id, "next"), callback_data=f"rentnum_page:{page+1}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton(t(user_id, "back_home"), callback_data="back_home")])

    return InlineKeyboardMarkup(keyboard)


async def send_cp_invoice(cp, client: Client, user_id: int, amount: float, description: str, msg: Message, payload: str):
    invoice = await cp.create_invoice(
        amount=amount,
        asset="USDT",
        description=description,
        paid_btn_name="openBot",
        paid_btn_url="https://t.me/{}".format((await client.get_me()).username),
        expires_in=1800,
        payload=payload
    )
    inv_id = invoice.invoice_id
    await msg.edit(
        f"💸 **Invoice Created**\n\n"
        f"Amount: `{amount}` USDT\n"
        f"Description: `{description}`\n"
        f"Pay using the button below.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay Now", url=invoice.bot_invoice_url)],
            [InlineKeyboardButton(t(user_id, "i_paid"), callback_data=f"check_payment_{inv_id}")],
        ])
    )


# NOTE: return type changed to (bool, str) to preserve reason strings used elsewhere.
async def delete_account(number: str, app: Client, two_fa_password: str = None) -> tuple[bool, str]:
    """
    Delete Telegram account linked to `number`.

    Logic:
    - If code type is not FRAGMENT_SMS but next_type is → force one resend to switch to Fragment.
    - Wait up to 30s for OTP from Fragment helper.
    - Handle 2FA (immediate deletion if password provided, else scheduled).
    - Manage all known errors, retry on FloodWait.
    """
    session_name = f"delete-{number.replace('+', '')}"
    client = Client(session_name, api_id=API_ID, api_hash=API_HASH)
    logging.info("=== delete_account START ===")
    logging.info(f"Starting deletion process for {number} (session='{session_name}')")

    def _type_name(x):
        if x is None:
            return "None"
        return getattr(x, "name", str(x))

    try:
        logging.info("Connecting pyrogram client...")
        await client.connect()
        logging.info(f"Connected to Telegram for {number} (is_connected={getattr(client, 'is_connected', False)})")

        # Step 1: Send login code
        logging.info("Requesting login code using client.send_code(...)")
        try:
            sent_code = await client.send_code(number)
        except FloodWait as e:
            logging.warning("FloodWait %s seconds during send_code. Sleeping and retrying...", e.value)
            await asyncio.sleep(e.value + 1)
            return await delete_account(number, app, two_fa_password)

        logging.info(
            "SentCode: phone_code_hash=%s, type=%s, next_type=%s, timeout=%s",
            getattr(sent_code, "phone_code_hash", None),
            _type_name(getattr(sent_code, "type", None)),
            _type_name(getattr(sent_code, "next_type", None)),
            getattr(sent_code, "timeout", None),
        )

        # Step 2: Resend if needed
        type_str = _type_name(getattr(sent_code, "type", None)).upper()
        next_type_str = _type_name(getattr(sent_code, "next_type", None)).upper()

        if type_str != "FRAGMENT_SMS" and next_type_str == "FRAGMENT_SMS":
            logging.info("First code is %s, next_type is FRAGMENT_SMS → resending to force Fragment.", type_str)
            try:
                sent_code = await client.resend_code(number, phone_code_hash=sent_code.phone_code_hash)
                logging.info(
                    "After resend: type=%s, next_type=%s",
                    _type_name(getattr(sent_code, "type", None)),
                    _type_name(getattr(sent_code, "next_type", None)),
                )
            except Exception as e:
                logging.error("Resend failed: %s", e)
                return False, "ResendError"
        elif type_str == "FRAGMENT_SMS":
            logging.info("Code already sent via Fragment SMS.")
        else:
            logging.warning("No Fragment type available (type=%s, next_type=%s). Proceeding anyway.", type_str, next_type_str)

        # Step 3: Fetch OTP from Fragment
        from hybrid.plugins.fragment import get_login_code
        otp = None
        for attempt in range(6):
            try:
                otp = get_login_code(number)
            except Exception as e:
                logging.error("get_login_code failed: %s", e)
                otp = None

            if otp:
                logging.info("Received OTP: %s", otp)
                break
            logging.info("No OTP yet. Waiting 5s (attempt %d/6).", attempt + 1)
            await asyncio.sleep(5)

        if not otp:
            logging.error("No OTP received for %s", number)
            return False, "OTP"

        # Step 4: Sign in
        try:
            await client.sign_in(
                phone_number=number,
                phone_code_hash=sent_code.phone_code_hash,
                phone_code=otp,
            )
            logging.info("Signed in successfully.")
        except PhoneNumberUnoccupied:
            logging.info("No account exists for this number.")
            return True, "NoAccount"
        except PhoneCodeInvalid:
            logging.error("Invalid OTP.")
            return False, "InvalidOTP"
        except SessionPasswordNeeded:
            if two_fa_password:
                try:
                    await client.check_password(two_fa_password)
                    logging.info("2FA password accepted.")
                except Exception as e:
                    logging.error("2FA password failed: %s", e)
                    return False, "Invalid2FAPassword"
            else:
                # CRITICAL: Don't return early. Still attempt deletion to trigger Telegram's 7-day period.
                logging.info("2FA enabled, no password. Attempting deletion anyway to trigger 7-day wait...")
        except PhoneNumberBanned:
            logging.error("Number banned.")
            return False, "Banned"
        except FloodWait as e:
            logging.warning("FloodWait %s during sign_in. Retrying...", e.value)
            await asyncio.sleep(e.value + 1)
            return await delete_account(number, app, two_fa_password)
        except Exception as e:
            logging.error("Unexpected sign_in error: %s", e)
            return False, "SignInError"

        # Step 5: Delete account (ALWAYS attempt, even with 2FA — triggers 7-day period if needed)
        try:
            await client.invoke(functions.account.DeleteAccount(reason="Cleanup"))
            logging.info("Account deleted immediately.")
            return True, "Deleted"
        except RPCError as e:
            error_text = str(e).upper()
            # 2FA without password = 7 day waiting period
            if "2FA_CONFIRM_WAIT" in error_text or "SESSION_PASSWORD_NEEDED" in error_text:
                logging.info("2FA detected - Telegram scheduled deletion in 7 days.")
                return True, "7Days"
            # Account already scheduled for deletion
            if "ACCOUNT_DELETE_SCHEDULED" in error_text:
                logging.info("Account deletion already scheduled.")
                return True, "7Days"
            logging.error("DeleteAccount RPCError: %s", e)
            return False, "DeleteError"
        except Exception as e:
            logging.error("Unexpected DeleteAccount error: %s", e)
            return False, "DeleteError"

    except Exception as e:
        logging.error("Top-level error: %s", e)
        return False, "Error"
    finally:
        if getattr(client, "is_connected", False):
            await client.disconnect()
            logging.info("Disconnected client.")
        logging.info("=== delete_account END ===")


async def check_number_conn(number: str) -> bool:
    from hybrid.plugins.fragment import fragment_api
    return await fragment_api.check_is_number_free(number)

def format_number(number) -> str:
    """
    Format a phone number from +88869696069 (int or str) to +888 6969 6069
    """
    number = str(number)

    if number.startswith("+888"):
        clean_number = number
    elif number.startswith("888"):
        clean_number = "+" + number
    else:
        raise ValueError("Number must start with +888")

    prefix = clean_number[:4]        # +888
    first_block = clean_number[4:8]  # 6969
    second_block = clean_number[8:]  # 6069

    return f"{prefix} {first_block} {second_block}"

def format_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %Z")
    return dt.strftime("%d/%m/%y")

def add_random_fraction(amount: float) -> float:
    fraction = random.uniform(0.01, 0.49)
    return round(amount + fraction, 2)

def get_tron_tx(tx_hash: str):
    url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()

    to_address = None
    human_amount = None
    symbol = "TRX"

    # TRC20 token transfer
    if "trc20TransferInfo" in data and data["trc20TransferInfo"]:
        t = data["trc20TransferInfo"][0]
        to_address = t.get("to_address")
        raw_amount = int(t.get("amount_str", "0"))
        decimals = int(t.get("decimals", 6))
        symbol = t.get("symbol", "TRC20")
        human_amount = raw_amount / (10 ** decimals)

    # TRC10 or TRX transfer
    elif "contractData" in data and "amount" in data["contractData"]:
        c = data["contractData"]
        to_address = c.get("to_address")
        raw_amount = c.get("amount")
        token_info = c.get("tokenInfo", {})
        decimals = int(token_info.get("tokenDecimal", 6))
        symbol = token_info.get("tokenAbbr", "TRX")
        human_amount = raw_amount / (10 ** decimals)

    return to_address, human_amount, symbol


from hybrid.plugins.db import (
    get_all_pool_numbers,
    get_user_balance,
    get_number_data,
)

def export_numbers_csv(filename: str = "numbers_export.csv"):
    """
    Export all numbers with rental details to a CSV file.

    Columns: Number, Rented, User ID, Balance, Rent Date, Expiry Date, Days Left, Hours Left, Rented Amount
    """
    all_numbers = get_all_pool_numbers()
    rows = []

    now = datetime.now(timezone.utc)
    for number in all_numbers:
        rented_data = get_number_data(number)

        if rented_data and rented_data.get("user_id"):
            user_id = rented_data.get("user_id")
            balance = get_user_balance(user_id) or 0.0
            rent_date = rented_data.get("rent_date")
            expiry_date = rented_data.get("expiry_date")
            hours = rented_data.get("hours", 0)
            rent_date_str = rent_date.strftime("%Y-%m-%d %H:%M:%S") if rent_date else ""
            expiry_date_str = expiry_date.strftime("%Y-%m-%d %H:%M:%S") if expiry_date else ""
            if expiry_date and rent_date:
                remaining = expiry_date - now
                days_left = max(0, remaining.days)
                hours_left = max(0, remaining.seconds // 3600)
            else:
                days_left = hours_left = 0

            rows.append({
                "Number": number,
                "Rented": "Yes",
                "User ID": user_id,
                "Balance": balance,
                "Rent Date": rent_date_str,
                "Expiry Date": expiry_date_str,
                "Days Left": days_left,
                "Hours Left": hours_left,
                "Rented Amount (Hours)": hours
            })
        else:
            rows.append({
                "Number": number,
                "Rented": "No",
                "User ID": "",
                "Balance": "",
                "Rent Date": "",
                "Expiry Date": "",
                "Days Left": "",
                "Hours Left": "",
                "Rented Amount (Hours)": ""
            })

    fieldnames = ["Number", "Rented", "User ID", "Balance", "Rent Date", "Expiry Date", "Days Left", "Hours Left", "Rented Amount (Hours)"]
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return filename

async def give_payment_option(client, msg: Message, user_id: int):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("@send", callback_data="set_payment_cryptobot")],
        [InlineKeyboardButton("USDT TRC-20", callback_data="set_payment_tron")]
    ])
    await msg.reply(
        t(user_id, "choose_payment_method"),
        reply_markup=keyboard
    )

async def send_tron_invoice(client: Client, user_id: int, amount: float, msg: Message):
    tron_address = USDT_ADDRESS
    final_amount = add_random_fraction(amount)
    await msg.edit(t(user_id, "pay_amount", amount=amount, address=tron_address), reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(t(user_id, "i_paid"), callback_data=f"check_payment_TRON_{final_amount}")]
    ]))

