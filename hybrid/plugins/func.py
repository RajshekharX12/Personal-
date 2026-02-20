#(©) @Hybrid_Vamp - https://github.com/hybridvamp

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
from config import LANGUAGES, D30_RATE, D60_RATE, D90_RATE, API_ID, API_HASH, TON_WALLET


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

async def check_proxy_async(pro_xy: str) -> bool:
    """Check proxy reachability without blocking the event loop (uses httpx)."""
    try:
        import httpx
        async with httpx.AsyncClient(proxy=pro_xy, timeout=10.0) as client:
            response = await client.get("http://httpbin.org/ip")
            return response.status_code == 200
    except Exception:
        return False


def check_proxy(pro_xy):
    """Sync wrapper. Prefer check_proxy_async from async code."""
    import asyncio
    return asyncio.run(check_proxy_async(pro_xy))

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

def _md_to_html(text: str) -> str:
    """Convert Markdown to HTML for parse_mode HTML."""
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    text = re.sub(r'__(.+?)__', r'<i>\1</i>', text)
    return text

def h(text: str) -> str:
    """Convert inline Markdown to HTML. Use for hardcoded messages."""
    return _md_to_html(text)

def t(user_id: int, key: str, **kwargs):
    from hybrid.plugins.db import get_user_language
    import re
    lang = get_user_language(user_id) or "en"
    text = LANGUAGES.get(lang, LANGUAGES["en"]).get(key, key)
    # Replace {{e:key}} with Unicode fallback (premium emoji disabled)
    _emoji_fallback = {"success":"✅","error":"❌","warning":"⚠️","phone":"📞","money":"💰","renew":"🔄","get_code":"📨","back":"⬅️","date":"📅","loading":"⌛","time":"🕒","timeout":"⏰"}
    text = re.sub(r'\{\{e:(\w+)\}\}', lambda m: _emoji_fallback.get(m.group(1), ""), text)
    text = _md_to_html(text)
    if kwargs:
        return text.format(**kwargs)
    return text

from hybrid.plugins.db import get_number_data, get_number_info, save_number_info, save_7day_deletion

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
        status = " 🔴" if number in temp.RENTED_NUMS else " 🟢"
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


def build_number_actions_keyboard(user_id: int, number: str, back_data: str = "my_rentals"):
    """Build keyboard for rented number: Renew, Get Code, Transfer, Back (plain text, no emojis)."""
    n = normalize_phone(number) or number
    keyboard = [
        [
            InlineKeyboardButton(t(user_id, "renew"), callback_data=f"renew_{n}"),
            InlineKeyboardButton(t(user_id, "get_code"), callback_data=f"getcode_{n}"),
        ],
        [InlineKeyboardButton(t(user_id, "transfer"), callback_data=f"transfer_{n}")],
        [InlineKeyboardButton(t(user_id, "back"), callback_data=back_data)],
    ]
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
    keyboard = [
        [InlineKeyboardButton("💳 Pay", url=invoice.bot_invoice_url)],
        [InlineKeyboardButton(t(user_id, "back"), callback_data=payload)],
    ]
    await msg.edit(
        f"💸 **Invoice Created**\n\n"
        f"Amount: `{amount}` USDT\n"
        f"Description: `{description}`\n"
        f"Pay using the button below.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def get_ton_price_usd() -> float:
    """Fetch current TON price in USD. Returns 0 on failure."""
    import requests
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(
            None,
            lambda: requests.get("https://tonapi.io/v2/rates?tokens=ton&currencies=usd", timeout=10)
        )
        if r.status_code != 200:
            return 0.0
        data = r.json()
        return float(data.get("rates", {}).get("TON", {}).get("prices", {}).get("USD", 0) or 0)
    except Exception:
        return 0.0


def create_tonkeeper_link(amount_ton: float, order_ref: str) -> str:
    """Build Tonkeeper TON payment link. Memo (order_ref) auto-filled via text param. No # used (Tonkeeper ignores %23)."""
    from urllib.parse import quote
    if not TON_WALLET:
        return ""
    amount_nano = int(float(amount_ton) * 1_000_000_000)  # 1 TON = 1e9 nanotons
    base = f"https://app.tonkeeper.com/transfer/{TON_WALLET}"
    return f"{base}?amount={amount_nano}&text={quote(order_ref)}"


async def send_tonkeeper_invoice(client: Client, user_id: int, amount_usdt: float, description: str, msg: Message, payload: str):
    """Create Tonkeeper payment screen. Converts USDT to TON, memo auto-filled in Pay link."""
    from hybrid.plugins.db import _gen_order_ref, save_ton_order
    if not TON_WALLET:
        await msg.edit("❌ Tonkeeper payments are not configured. Contact support.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data=payload)]]))
        return
    ton_price = await get_ton_price_usd()
    if not ton_price or ton_price <= 0:
        await msg.edit("❌ Could not fetch TON price. Please try again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data=payload)]]))
        return
    amount_ton = amount_usdt / ton_price
    order_ref = _gen_order_ref()
    save_ton_order(order_ref, user_id, amount_usdt, amount_ton, payload, msg.id, msg.chat.id)
    pay_url = create_tonkeeper_link(amount_ton, order_ref)
    if not pay_url:
        await msg.edit("❌ Failed to create Tonkeeper link.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data=payload)]]))
        return
    keyboard = [
        [InlineKeyboardButton("💳 Pay", url=pay_url)],
        [InlineKeyboardButton(t(user_id, "back"), callback_data=payload)],
    ]
    await msg.edit(
        f"💸 **Tonkeeper Payment**\n\n"
        f"• Amount: {amount_usdt} USDT (~{amount_ton:.4f} TON)\n"
        f"• Description: {description}\n"
        f"• Order ID (memo): `{order_ref}`\n\n"
        f"Memo is pre-filled when you tap Pay. Payment is checked automatically.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def _ton_addresses_match(addr1: str, addr2: str) -> bool:
    """Compare TON addresses - EQ vs UQ same wallet have different checksums, must decode to raw."""
    if not addr1 or not addr2:
        return False
    try:
        from pytoniq_core import Address
        a1 = Address(addr1.strip())
        a2 = Address(addr2.strip())
        return a1 == a2 or str(a1) == str(a2)
    except Exception:
        s1 = str(addr1).replace("-", "").replace("_", "").replace(" ", "").lower()
        s2 = str(addr2).replace("-", "").replace("_", "").replace(" ", "").lower()
        return s1 == s2


def _extract_comment(in_msg: dict) -> str:
    """Extract comment from TON in_msg per asset-processing. Handles msg.dataText and msg.dataRaw (BOC)."""
    import base64
    msg_data = in_msg.get("msg_data") or {}
    comment = (msg_data.get("message") or "").strip()
    if comment:
        return comment
    text_b64 = msg_data.get("text")
    if text_b64:
        try:
            raw = base64.b64decode(text_b64)
            if len(raw) >= 4 and raw[:4] == b"\x00\x00\x00\x00":
                return raw[4:].decode("utf-8", errors="ignore").strip()
            return raw.decode("utf-8", errors="ignore").strip()
        except Exception:
            pass
    body = msg_data.get("body")
    if body:
        try:
            from pytoniq_core import Cell
            cell = Cell.one_from_boc(base64.b64decode(body))
            return cell.begin_parse().load_snake_string().replace("\x00", "").strip()
        except Exception:
            try:
                raw = base64.b64decode(body)
                for start in range(min(20, len(raw))):
                    try:
                        s = raw[start:].decode("utf-8", errors="strict").strip().replace("\x00", "")
                        if 4 <= len(s) <= 64 and s.isprintable():
                            return s
                    except (UnicodeDecodeError, ValueError):
                        continue
            except Exception:
                pass
    return ""


# Tonkeeper payment checker (TonCenter API v2 - TON asset processing)
async def check_tonkeeper_payments(client, get_user_balance, save_user_balance, delete_ton_order,
                                   get_all_pending_ton_orders, t, TON_WALLET):
    """Poll TonCenter getTransactions, parse in_msg comment and value. Credit on match. Same flow as CryptoBot."""
    if not TON_WALLET:
        return
    pending = get_all_pending_ton_orders()
    if not pending:
        return
    try:
        from urllib.parse import quote
        addr_param = quote(TON_WALLET.strip(), safe="")
        url = f"https://toncenter.com/api/v2/getTransactions?address={addr_param}&limit=50"
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: requests.get(url, timeout=8))
        if r.status_code != 200:
            return
        data = r.json()
        if not data.get("ok") or "result" not in data:
            return
        txs = data.get("result") or []
        for order_ref, order in pending:
            memo_needle = order_ref
            amount_ton = order.get("amount_ton") or (float(order["amount"]) / 5.0)
            amount_nano_min = int(float(amount_ton) * 1_000_000_000 * 0.98)
            for tx in txs:
                in_msg = tx.get("in_msg")
                if not in_msg:
                    continue
                dest = in_msg.get("destination") or ""
                if not _ton_addresses_match(TON_WALLET, dest):
                    continue
                try:
                    amt = int(in_msg.get("value") or 0)
                except (ValueError, TypeError):
                    amt = 0
                if amt < amount_nano_min:
                    continue
                comment = _extract_comment(in_msg)
                if memo_needle not in comment and (comment or "").strip() != memo_needle:
                    continue
                user_id = order["user_id"]
                payload = (order.get("payload") or "").strip()
                try:
                    await client.edit_message_text(order["chat_id"], order["msg_id"], "⌛")
                except Exception:
                    pass
                current_bal = get_user_balance(user_id) or 0.0
                new_bal = current_bal + float(order["amount"])
                save_user_balance(user_id, new_bal)
                if payload.startswith("rentpay:"):
                    parts = payload.split(":")
                    if len(parts) >= 3:
                        _, number, hours = parts[0], parts[1], parts[2]
                        keyboard = InlineKeyboardMarkup([[
                            InlineKeyboardButton(t(user_id, "confirm"), callback_data=f"confirmrent:{number}:{hours}")
                        ]])
                    else:
                        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]])
                elif payload.startswith("numinfo:"):
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data=payload)]])
                else:
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]])
                try:
                    await client.edit_message_text(
                        order["chat_id"], order["msg_id"],
                        t(user_id, "payment_confirmed"),
                        reply_markup=keyboard
                    )
                except Exception:
                    pass
                delete_ton_order(order_ref)
                break
    except Exception as e:
        logging.error(f"Tonkeeper check error: {e}")


async def run_7day_deletion_scheduler(app: Client):
    from hybrid.plugins.db import get_7day_deletions, remove_7day_deletion
    logging.info("7-day deletion scheduler started.")
    while True:
        try:
            due_numbers = get_7day_deletions()
            for number in due_numbers:
                logging.info("7-day window passed for %s. Re-attempting deletion...", number)
                remove_7day_deletion(number)
                try:
                    success, reason = await delete_account(number, app, two_fa_password=None)
                    logging.info("Re-deletion result for %s: success=%s reason=%s", number, success, reason)
                except Exception as e:
                    logging.error("Re-deletion failed for %s: %s", number, e)
        except Exception as e:
            logging.error("7-day scheduler error: %s", e)
        await asyncio.sleep(3600)


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

        # Step 3: Fetch OTP from Fragment (async to avoid blocking the event loop)
        from hybrid.plugins.fragment import get_login_code_async
        otp = None
        for attempt in range(6):
            try:
                otp = await get_login_code_async(number)
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
                save_7day_deletion(number, datetime.now(timezone.utc) + timedelta(days=7))
                return True, "7Days"
            # Account already scheduled for deletion
            if "ACCOUNT_DELETE_SCHEDULED" in error_text:
                logging.info("Account deletion already scheduled.")
                save_7day_deletion(number, datetime.now(timezone.utc) + timedelta(days=7))
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

def normalize_phone(number) -> str | None:
    """Normalize to +888XXXXXXXX. Returns None if invalid."""
    if number is None:
        return None
    s = str(number).strip().replace(" ", "").replace("-", "")
    if not s:
        return None
    if s.startswith("+888") and len(s) >= 12:
        return s
    if s.startswith("888") and len(s) >= 11:
        return "+" + s
    if s.isdigit() and len(s) == 8:
        return "+888" + s
    return None

def format_number(number) -> str:
    """Format phone to +888 XXXX XXXX. Never raises - returns safe fallback for invalid input."""
    clean = normalize_phone(number)
    if clean and len(clean) >= 12:
        return f"{clean[:4]} {clean[4:8]} {clean[8:]}"
    s = str(number or "").strip().replace(" ", "")
    if (s.startswith("+888") or s.startswith("888")) and len(s) >= 11:
        pref = s[:4] if s.startswith("+") else "+" + s[:3]
        rest = s[4:] if s.startswith("+") else s[3:]
        if len(rest) >= 8:
            return f"{pref} {rest[:4]} {rest[4:]}"
    return s if s else "N/A"

def format_date(date_str) -> str:
    """Parse date string (ISO, strptime formats) and return DD/MM/YY."""
    if date_str is None:
        return "N/A"
    s = str(date_str).strip()
    if not s:
        return "N/A"
    # Strip timezone to avoid parse errors (e.g. .512189+00:00)
    if "+" in s or s.endswith("Z"):
        s = s.replace("Z", "").split("+")[0].rstrip("-").rstrip()
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return s[:10] if len(s) >= 10 else s
    return dt.strftime("%d/%m/%y")

from hybrid.plugins.db import get_user_balance, get_number_data, get_rented_data_for_number, get_all_rentals

try:
    from hybrid.plugins.db import get_all_pool_numbers
except ImportError:
    get_all_pool_numbers = None


def export_numbers_csv(filename: str = "numbers_export.csv"):
    """
    Export all numbers with rental details to a CSV file.
    Includes pool numbers + rented numbers (admin-assigned may not be in pool).
    """
    pool = set(get_all_pool_numbers()) if get_all_pool_numbers else set()
    pool = pool or set(temp.NUMBE_RS or [])
    rented_numbers = {doc.get("number") for doc in get_all_rentals() if doc.get("number")}
    all_numbers = sorted(pool | rented_numbers)
    rows = []

    now = datetime.now(timezone.utc)
    for number in all_numbers:
        rented_data = get_rented_data_for_number(number)

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
    rows = [[InlineKeyboardButton("CryptoBot (@send)", callback_data="set_payment_cryptobot")]]
    if TON_WALLET:
        rows.append([InlineKeyboardButton("Tonkeeper", callback_data="set_payment_tonkeeper")])
    rows.append([InlineKeyboardButton(t(user_id, "back"), callback_data="profile")])
    keyboard = InlineKeyboardMarkup(rows)
    await msg.reply(
        t(user_id, "choose_payment_method"),
        reply_markup=keyboard
    )

