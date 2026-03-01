#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import sys
import logging
import asyncio

from config import *
from aiosend import CryptoPay
from datetime import timedelta, timezone

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

from datetime import datetime
from logging.handlers import RotatingFileHandler

from hybrid.plugins.temp import temp
from hybrid.plugins.func import get_restart_data
from hybrid.plugins.db import client as redis_client

BANNER = f"""\n\n
██╗░░██╗██╗░░░██╗██████╗░██████╗░██╗██████╗░
██║░░██║╚██╗░██╔╝██╔══██╗██╔══██╗██║██╔══██╗
███████║░╚████╔╝░██████╦╝██████╔╝██║██║░░██║
██╔══██║░░╚██╔╝░░██╔══██╗██╔══██╗██║██║░░██║
██║░░██║░░░██║░░░██████╦╝██║░░██║██║██████╔╝
╚═╝░░╚═╝░░░╚═╝░░░╚═════╝░╚═╝░░╚═╝╚═╝╚═════╝░
"""

LOG_FILE_NAME = "hybridlogs.txt"
# make log txt if not exists
if not os.path.exists(LOG_FILE_NAME):
    with open(LOG_FILE_NAME, "w"):
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt='%d-%b-%y %H:%M:%S',
    handlers=[
        RotatingFileHandler(
            LOG_FILE_NAME,
            maxBytes=50000000,
            backupCount=10
        ),
        logging.StreamHandler()
    ]
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("aiosend.client").setLevel(logging.WARNING)
logging.getLogger("aiosend.polling").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

CRYPTO_STAT = False
if CRYPTO_API:
    try:
        cp = CryptoPay(CRYPTO_API)
        CRYPTO_STAT = True
    except Exception as e:
        logging.error("💳 [PAYMENT] CryptoPay init failed: %s", e)

plugins = dict(root="hybrid/plugins")

def gen_4letters():
    import random
    import string
    return ''.join(random.choices(string.ascii_letters, k=4))

async def load_num_data():
    """
    Load numbers from Fragment at startup. Runs sync get_fragment_numbers() in a thread
    so the event loop is not blocked, and we keep the same cookie/request behavior that
    was working before (httpx async path can differ re cookies and may return empty).
    """
    logging.info("🚀 [STARTUP] Loading numbers from Fragment API...")
    from hybrid.plugins.fragment import get_fragment_numbers
    loop = asyncio.get_event_loop()
    try:
        NU_MS, stat = await loop.run_in_executor(None, lambda: get_fragment_numbers())
    except Exception as e:
        logging.error("Failed to load numbers from Fragment API: %s", e, exc_info=True)
        return
    if not stat or stat.get("message") != "OK":
        logging.error("Failed to load numbers from Fragment API (stat: %s).", stat)
        return
    temp.NUMBE_RS_SET = set(temp.NUMBE_RS)
    for n in NU_MS:
        if n not in temp.NUMBE_RS_SET:
            temp.NUMBE_RS.append(n)
            temp.NUMBE_RS_SET.add(n)
    from hybrid.plugins.db import get_number_data, get_number_info, save_number_info
    for num in temp.NUMBE_RS:
        info = await get_number_info(num)
        if not info:
            await save_number_info(num, D30_RATE, D60_RATE, D90_RATE, available=True)
            info = await get_number_info(num)
        rented = await get_number_data(num)
        if rented and rented.get("user_id"):
            temp.RENTED_NUMS.add(num)
        elif info and info.get("available", True):
            temp.AVAILABLE_NUM.add(num)
    logging.info("🚀 [STARTUP] Loaded %d numbers | %d available | %d rented", len(temp.NUMBE_RS), len(temp.AVAILABLE_NUM), len(temp.RENTED_NUMS))


from hybrid.plugins.db import get_number_data, get_remaining_rent_days, is_restricted_del_enabled, remove_number, remove_number_data, save_restricted_number, get_all_rentals, get_expired_numbers
from hybrid.plugins.func import get_current_datetime, check_number_conn, delete_account

async def schedule_reminders(client):
    """
    Send reminders at 72h, 24h, 6h, and 1h before expiry.
    Runs every 15 minutes. Uses Redis to track which reminders have been sent.
    """
    from hybrid.plugins.func import format_remaining_time, t
    REMINDER_THRESHOLDS = [
        (72 * 3600, "72h"),
        (24 * 3600, "24h"),
        (6 * 3600, "6h"),
        (1 * 3600, "1h"),
    ]
    while True:
        try:
            now = get_current_datetime().replace(tzinfo=timezone.utc)
            rented = await get_all_rentals()
            for doc in rented:
                number = doc["number"]
                user_id = doc["user_id"]
                expiry = doc.get("expiry_date")
                if not expiry:
                    continue
                if isinstance(expiry, str):
                    expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                remaining_secs = (expiry - now).total_seconds()
                if remaining_secs <= 0:
                    continue
                for threshold_secs, label in REMINDER_THRESHOLDS:
                    # Only fire if within threshold window (threshold to threshold - 15min check interval)
                    window = 15 * 60
                    if threshold_secs >= remaining_secs > (threshold_secs - window):
                        # Check if already sent this reminder
                        redis_key = f"reminder:{number}:{label}"
                        already_sent = await redis_client.get(redis_key)
                        if already_sent:
                            continue
                        try:
                            remaining_str = format_remaining_time(doc.get("rent_date"), doc.get("hours", 0))
                            text = (t(user_id, "expire_soon")).format(
                                number=number,
                                remaining_days=remaining_str
                            )
                            keyboard = InlineKeyboardMarkup([[
                                InlineKeyboardButton(
                                    t(user_id, "renew"),
                                    callback_data=f"renew_{number}"
                                )
                            ]])
                            try:
                                await client.send_message(user_id, text, reply_markup=keyboard)
                                # Mark as sent with a 7-day TTL to prevent duplicate reminders across restarts
                                await redis_client.set(redis_key, "1", ex=7 * 24 * 3600)
                                logging.info(f"Sent {label} reminder to {user_id} for {number}")
                            except FloodWait as e:
                                await asyncio.sleep(e.value + 1)
                                try:
                                    await client.send_message(user_id, text, reply_markup=keyboard)
                                    await redis_client.set(redis_key, "1", ex=7 * 24 * 3600)
                                except Exception as e:
                                    logging.debug(f"schedule_reminders send_message failed user_id={user_id} number={number} label={label}: {e}")
                        except Exception as e:
                            logging.error(f"Failed to send {label} reminder to {user_id} for {number}: {e}")
        except Exception as e:
            logging.error(f"schedule_reminders error: {e}")
        await asyncio.sleep(900)  # Run every 15 minutes

# Limit concurrent delete_account calls so we don't overload Fragment/Telegram with many connections.
EXPIRED_DELETE_SEMAPHORE = asyncio.Semaphore(3)

async def _process_one_expired(number: str, client, now):
    """Handle one expired number: terminate sessions, delete account, cleanup, notify. Used concurrently with semaphore."""
    num_data = await get_number_data(number)
    user_id = num_data.get("user_id") if num_data else None
    if not user_id:
        await remove_number_data(number)
        return
    seven_day_pending = False
    try:
        async with EXPIRED_DELETE_SEMAPHORE:
            try:
                from hybrid.plugins.fragment import terminate_all_sessions_async
                await terminate_all_sessions_async(number)
            except Exception as e:
                logging.debug(f"_process_one_expired terminate_all_sessions_async failed number={number}: {e}")
            stat, reason = await delete_account(number, client)
        if stat:
            await remove_number_data(number)
            await remove_number(number, user_id)
        if reason == "7Days":
            seven_day_pending = True
            from hybrid.plugins.db import save_7day_deletion
            await save_7day_deletion(number, now + timedelta(days=7))
        if not stat and reason == "Banned":
            logging.info(f"Number {number} is banned (banned feature disabled, not tracking).")
            return
        logging.info(f"Expired number {number} cleaned up for user {user_id}")
    except Exception as e:
        logging.error(f"Error handling expired number {number}: {e}")
    finally:
        async with temp.get_lock():
            if number in temp.RENTED_NUMS:
                temp.RENTED_NUMS.remove(number)
        if not seven_day_pending:
            try:
                from hybrid.plugins.guard import guard_is_free
                is_free = await guard_is_free(number)
                if is_free:
                    async with temp.get_lock():
                        if number not in temp.AVAILABLE_NUM:
                            temp.AVAILABLE_NUM.add(number)
                    logging.info(f"Number {number} confirmed free on Fragment, relisted.")
                else:
                    logging.info(f"Number {number} not yet free on Fragment, skipping relist.")
            except Exception as e:
                logging.error(f"Fragment check failed for {number}: {e}")
                async with temp.get_lock():
                    if number not in temp.AVAILABLE_NUM:
                        temp.AVAILABLE_NUM.add(number)
        else:
            logging.info(f"Number {number} is in 7-day deletion period — skipping relist.")
        from hybrid.plugins.func import t
        text = (t(user_id, "expired_notify")).format(number=number)
        try:
            await client.send_message(user_id, text)
        except Exception as e:
            logging.error(f"Failed to notify user {user_id} about expired number {number}: {e}")

async def check_expired_numbers(client):
    """Background checker: remove expired numbers. Processes multiple expired numbers concurrently (semaphore-limited)."""
    while True:
        now = get_current_datetime().replace(tzinfo=timezone.utc)
        expired_list = await get_expired_numbers()
        if expired_list:
            await asyncio.gather(*[_process_one_expired(number, client, now) for number in expired_list], return_exceptions=True)
        await asyncio.sleep(120)


async def _finalize_7day_deletion(number, client):
    """Full cleanup + notify + relist flow after a 7-day deletion is complete."""
    from hybrid.plugins.db import get_user_by_number, remove_number_data, remove_number, remove_7day_deletion
    user_id, _, _ = await get_user_by_number(number)
    if user_id:
        await remove_number_data(number)
        await remove_number(number, user_id)
    await remove_7day_deletion(number)
    if user_id:
        try:
            await client.send_message(
                user_id,
                f"✅ The Telegram account linked to your number <b>{number}</b> has been permanently deleted.\n"
                f"The number may now be available for re-rent.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as notify_err:
            logging.error(f"Failed to notify user {user_id} after 7-day deletion of {number}: {notify_err}")
    async with temp.get_lock():
        if number in temp.RENTED_NUMS:
            temp.RENTED_NUMS.remove(number)
    try:
        from hybrid.plugins.guard import guard_is_free
        is_free = await guard_is_free(number)
        if is_free:
            async with temp.get_lock():
                if number not in temp.AVAILABLE_NUM:
                    temp.AVAILABLE_NUM.add(number)
            logging.info(f"Number {number} confirmed free on Fragment, relisted.")
        else:
            logging.info(f"Number {number} not yet free on Fragment, skipping relist.")
    except Exception as e:
        logging.error(f"Fragment check failed for {number}: {e}")
        async with temp.get_lock():
            if number not in temp.AVAILABLE_NUM:
                temp.AVAILABLE_NUM.add(number)


async def check_7day_accs(client):
    """Check and complete 7-day scheduled deletions. Reconnects with saved session to finalize deletion."""
    from pyrogram.raw import functions
    from config import API_ID, API_HASH
    while True:
        now = get_current_datetime().replace(tzinfo=timezone.utc)
        from hybrid.plugins.db import get_7day_deletions, get_7day_date, remove_7day_deletion, save_7day_deletion, get_user_by_number
        numbers = await get_7day_deletions()
        if not numbers:
            await asyncio.sleep(3600)
            continue
        for num in numbers:
            date = await get_7day_date(num)
            if not date or date > now:
                continue
            session_name = f"delete-{num.replace('+', '')}"
            temp_client = Client(session_name, api_id=API_ID, api_hash=API_HASH)
            try:
                await temp_client.connect()
                try:
                    me = await temp_client.get_me()
                except Exception:
                    me = None
                if me is not None:
                    try:
                        await temp_client.invoke(functions.account.DeleteAccount(reason="Cleanup"))
                        try:
                            from hybrid.plugins.guard import guard_is_free
                            is_free = await guard_is_free(num)
                            if is_free:
                                logging.info(f"✅ Account {num} deleted (verified via Fragment).")
                            else:
                                logging.info(f"❌ Account {num} not deleted — 7-day step two verification activated.")
                        except Exception as e:
                            logging.info(f"✅ Completed 7-day deletion for {num} (Fragment verify: {e})")
                    except Exception as e:
                        err_upper = str(e).upper()
                        if "ACCOUNT_DELETED" in err_upper or "USER_DEACTIVATED" in err_upper:
                            logging.info(f"Account {num} already deleted.")
                        else:
                            logging.error(f"Failed to complete deletion for {num}: {e}")
                            if getattr(temp_client, "is_connected", False):
                                await temp_client.disconnect()
                            stat, reason = await delete_account(num, client)
                            if stat:
                                await _finalize_7day_deletion(num, client)
                            continue
                    await _finalize_7day_deletion(num, client)
                else:
                    logging.warning(f"Session expired for {num}, attempting full re-login to complete deletion.")
                    stat, reason = await delete_account(num, client)
                    if stat and reason == "7Days":
                        logging.info(f"Deleted account {num} after 7 days (re-login path).")
                        await save_7day_deletion(num, now)
                    elif stat:
                        await _finalize_7day_deletion(num, client)
                    elif reason == "Banned":
                        pass  # Banned feature disabled
            except Exception as e:
                logging.error(f"Error completing 7-day deletion for {num}: {e}")
                try:
                    stat, reason = await delete_account(num, client)
                    if stat:
                        await _finalize_7day_deletion(num, client)
                except Exception as e2:
                    logging.error(f"Fallback delete_account failed for {num}: {e2}")
            finally:
                if getattr(temp_client, "is_connected", False):
                    await temp_client.disconnect()
        await asyncio.sleep(3600)

async def check_restricted_numbers(client):
    """Check and log restricted numbers from Fragment. Runs once a day"""
    from hybrid.plugins.func import t
    while True:
        from hybrid.plugins.fragment import get_restricted_numbers_async
        restricted, _ = await get_restricted_numbers_async()
        if not restricted:
            logging.error("No Restricted numbers found or failed to fetch.")
            return

        for num in restricted:
            logging.info(f"Number {num} is restricted by Fragment.")
            if num not in temp.RESTRICTED_NUMS:
                temp.RESTRICTED_NUMS.add(num)

            num_data = await get_number_data(num)
            user_id = num_data.get("user_id") if num_data else None
            if not user_id:
                continue

            stat, reason = await save_restricted_number(num)
            if not stat and reason == "ALREADY":
                from hybrid.plugins.db import get_rest_num_date
                date = await get_rest_num_date(num)
                now = get_current_datetime()

                if date and date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)

                if date and (now - date).days >= 3:
                    if not await is_restricted_del_enabled():
                        logging.info("Restricted auto-deletion is disabled. Skipping deletion.")
                        continue

                try:
                    from hybrid.plugins.fragment import terminate_all_sessions_async
                    await terminate_all_sessions_async(num)
                except Exception as e:
                    logging.debug(f"terminate_all_sessions_async failed for restricted number {num}: {e}")

                    stat, reason = await delete_account(num, client)
                    if stat and reason == "7Days":
                        logging.info(f"Deleted account {num} after 7 days")
                        from hybrid.plugins.db import save_7day_deletion
                        await save_7day_deletion(num, now + timedelta(days=7))
                    if stat:
                        await remove_number_data(num)
                        await remove_number(num, user_id)
                    if not stat and reason == "Banned":
                        continue  # Banned feature disabled
                    logging.info(f"Restricted number {num} cleaned up for user {user_id} after 3 days")
                else:
                    logging.info(f"Restricted number {num} not yet cleaned up for user {user_id}")
                    days_remaining = 3 - (now - date).days if date else 3
                    text = (t(user_id, "restricted_notify")).format(number=num, days=days_remaining)
                    try:
                        await client.send_message(user_id, text)
                    except Exception as e:
                        logging.error(f"Failed to notify user {user_id} about restricted number {num}: {e}")
                continue

            text = (t(user_id, "restricted_notify")).format(number=num, days=3)
            try:
                await client.send_message(user_id, text)
            except Exception as e:
                logging.error(f"Failed to notify user {user_id} about restricted number {num}: {e}")

        await asyncio.sleep(86400)


async def _process_paid_invoice(client, user_id, msg_id, inv, inv_id):
    """Shared payment processing + auto-rent for paid invoices. Handles balance crediting, rentpay auto-rent with locking, fallback keyboard, cleanup."""
    from hybrid.plugins.temp import temp
    from hybrid.plugins.db import (
        get_user_balance, save_user_balance, mark_payment_processed_crypto,
        delete_inv_entry, get_number_info, get_rented_data_for_number,
        save_number, save_rental_atomic, unlock_number_for_rent, lock_number_for_rent,
        record_revenue, record_transaction,
    )
    from hybrid.plugins.func import t, resolve_payment_keyboard, format_number, format_remaining_time, get_current_datetime, get_remaining_hours, normalize_phone
    from hybrid.plugins.callback import build_number_actions_keyboard
    from config import D30_RATE, D60_RATE, D90_RATE

    try:
        await client.edit_message_text(user_id, msg_id, "⌛")
    except Exception as e:
        logging.debug(f"_process_paid_invoice edit_message_text ⌛ failed user_id={user_id} msg_id={msg_id}: {e}")
    payload = (getattr(inv, "payload", "") or "").strip()
    current_bal = await get_user_balance(user_id) or 0.0
    fiat_amount = await redis_client.get(f"inv_amount:{inv_id}")
    credit = float(fiat_amount) if fiat_amount else float(inv.amount)
    new_bal = current_bal + credit
    await redis_client.delete(f"inv_amount:{inv_id}")
    await save_user_balance(user_id, new_bal)
    await mark_payment_processed_crypto(str(inv_id))
    await record_transaction(user_id, credit, "deposit", "Balance top-up via CryptoBot")
    if payload.startswith("rentpay:"):
        parts = payload.split(":")
        number = parts[1] if len(parts) >= 2 else ""
        hours = int(parts[2]) if len(parts) >= 3 else 0
        number = normalize_phone(number) or number
        num_text = format_number(number)
        info = await get_number_info(number)
        rented_data = await get_rented_data_for_number(number)
        if info and info.get("available", True) and hours:
            if rented_data and rented_data.get("user_id") and int(rented_data.get("user_id", 0)) != user_id:
                keyboard = await resolve_payment_keyboard(user_id, payload)
                try:
                    await client.edit_message_text(user_id, msg_id, t(user_id, "payment_confirmed"), reply_markup=keyboard)
                except Exception as e:
                    logging.debug(f"_process_paid_invoice edit_message_text failed user_id={user_id}: {e}")
            else:
                prices = info.get("prices", {})
                price_map = {720: prices.get("30d", D30_RATE), 1440: prices.get("60d", D60_RATE), 2160: prices.get("90d", D90_RATE)}
                price = price_map.get(hours)
                if price is not None and new_bal >= price:
                    lock_acquired = await lock_number_for_rent(number, user_id, ttl=1800)
                    if lock_acquired:
                        try:
                            rent_date = rented_data.get("rent_date", get_current_datetime()) if rented_data else get_current_datetime()
                            remaining_hours = get_remaining_hours(rent_date, rented_data.get("hours", 0)) if rented_data else 0
                            new_hours = remaining_hours + hours
                            new_balance = new_bal - price
                            if remaining_hours > 0:
                                await save_number(number, user_id, new_hours, extend=True)
                                original_rent_date = rented_data.get("rent_date", get_current_datetime())
                                await save_rental_atomic(user_id, number, new_balance, original_rent_date, new_hours)
                            else:
                                await save_number(number, user_id, new_hours)
                                await save_rental_atomic(user_id, number, new_balance, get_current_datetime(), new_hours)
                            async with temp.get_lock():
                                temp.RENTED_NUMS.add(number)
                                temp.AVAILABLE_NUM.discard(number)
                            try:
                                await record_revenue(user_id, number, price, new_hours)
                                if remaining_hours > 0:
                                    await record_transaction(user_id, -price, "renewal", f"Renewed {num_text} for {hours // 24} days")
                                else:
                                    await record_transaction(user_id, -price, "rent", f"Rented {num_text} for {hours // 24} days")
                            except Exception as e:
                                logging.error("🔑 [RENT] Post-rental tracking failed number=%s: %s", number, e)
                            duration = format_remaining_time(get_current_datetime(), new_hours)
                            keyboard = await build_number_actions_keyboard(user_id, number, "my_rentals")
                            try:
                                await client.edit_message_text(
                                    user_id, msg_id,
                                    t(user_id, "rental_success", number=num_text, duration=duration, price=price, balance=new_balance),
                                    reply_markup=keyboard
                                )
                            except Exception as e:
                                logging.debug(f"_process_paid_invoice edit rental_success failed user_id={user_id}: {e}")
                        finally:
                            await unlock_number_for_rent(number)
                    else:
                        try:
                            await client.edit_message_text(
                                user_id, msg_id,
                                t(user_id, "payment_confirmed") + "\n\n⚠️ Number was rented by someone else. Your balance has been credited.",
                                reply_markup=await resolve_payment_keyboard(user_id, payload)
                            )
                        except Exception as e:
                            logging.debug(f"_process_paid_invoice edit_message_text (lock failed) user_id={user_id}: {e}")
                else:
                    keyboard = await resolve_payment_keyboard(user_id, payload)
                    try:
                        await client.edit_message_text(user_id, msg_id, t(user_id, "payment_confirmed"), reply_markup=keyboard)
                    except Exception as e:
                        logging.debug(f"_process_paid_invoice edit_message_text (no price/bal) user_id={user_id}: {e}")
        else:
            keyboard = await resolve_payment_keyboard(user_id, payload)
            try:
                await client.edit_message_text(user_id, msg_id, t(user_id, "payment_confirmed"), reply_markup=keyboard)
            except Exception as e:
                logging.debug(f"_process_paid_invoice edit_message_text (not rentpay) user_id={user_id}: {e}")
    else:
        keyboard = await resolve_payment_keyboard(user_id, payload)
        try:
            await client.edit_message_text(
                user_id, msg_id,
                t(user_id, "payment_confirmed"),
                reply_markup=keyboard
            )
        except Exception as e:
            logging.debug(f"_process_paid_invoice edit_message_text (fallback) user_id={user_id}: {e}")
    temp.INV_DICT.pop(user_id, None)
    await delete_inv_entry(user_id)
    if inv_id in temp.PENDING_INV:
        temp.PENDING_INV.remove(inv_id)


async def check_payments(client):
    """Background: verify CryptoBot invoices. Update messages when paid. Auto-rent on rentpay payload."""
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from hybrid.plugins.temp import temp
    from hybrid.plugins.db import is_payment_processed_crypto, delete_inv_entry

    while True:
        try:
            if CRYPTO_STAT:
                try:
                    cp_client = cp
                except NameError:
                    cp_client = None
            else:
                cp_client = None
            if cp_client and hasattr(cp_client, "get_invoice"):
                for user_id, (inv_id, msg_id) in list(temp.INV_DICT.items()):
                    try:
                        inv = await cp_client.get_invoice(inv_id)
                        if inv and getattr(inv, "status", None) == "paid":
                            if await is_payment_processed_crypto(str(inv_id)):
                                temp.INV_DICT.pop(user_id, None)
                                await delete_inv_entry(user_id)
                                if inv_id in temp.PENDING_INV:
                                    temp.PENDING_INV.remove(inv_id)
                                continue
                            await _process_paid_invoice(client, user_id, msg_id, inv, inv_id)
                        elif inv and getattr(inv, "status", None) == "expired":
                            final_check = await cp_client.get_invoice(inv_id)
                            if final_check and getattr(final_check, "status", None) == "paid":
                                if await is_payment_processed_crypto(str(inv_id)):
                                    temp.INV_DICT.pop(user_id, None)
                                    await delete_inv_entry(user_id)
                                    if inv_id in temp.PENDING_INV:
                                        temp.PENDING_INV.remove(inv_id)
                                else:
                                    await _process_paid_invoice(client, user_id, msg_id, final_check, inv_id)
                            else:
                                temp.INV_DICT.pop(user_id, None)
                                await delete_inv_entry(user_id)
                                await redis_client.delete(f"inv_amount:{inv_id}")
                                if inv_id in temp.PENDING_INV:
                                    temp.PENDING_INV.remove(inv_id)
                                try:
                                    await client.edit_message_text(
                                        user_id, msg_id,
                                        "⚠️ Your payment invoice has expired.\n\n"
                                        "We have verified that no payment was received for this invoice. "
                                        "Please return to the number listing and initiate a new rental — "
                                        "your spot is open and available.\n\n"
                                        "If you believe this is an error, please contact support.",
                                        reply_markup=InlineKeyboardMarkup([
                                            [InlineKeyboardButton("🔄 Browse Numbers", callback_data="rentnum_page:0")],
                                            [InlineKeyboardButton("💬 Support", url="https://t.me/Aress")]
                                        ]),
                                        parse_mode=ParseMode.HTML
                                    )
                                except Exception:
                                    try:
                                        await client.send_message(
                                            user_id,
                                            "⚠️ Your payment invoice has expired.\n\n"
                                            "We have verified that no payment was received. "
                                            "Please try renting a new number.",
                                            parse_mode=ParseMode.HTML
                                        )
                                    except Exception as send_e:
                                        logging.debug(f"check_payments expired send_message fallback failed user_id={user_id}: {send_e}")
                    except Exception as e:
                        logging.debug(f"CryptoBot check invoice {inv_id}: {e}")

        except Exception as e:
            logging.error(f"Payment checker error: {e}")
        await asyncio.sleep(12)


async def cleanup_old_invoices(client):
    """Periodic cleanup: remove unpaid invoices older than 30 days. Checks daily."""
    while True:
        await asyncio.sleep(24 * 3600)  # check once per day
        try:
            last_cleanup = await redis_client.get("last_invoice_cleanup")
            if last_cleanup:
                last_ts = float(last_cleanup)
                import time as _time
                if (_time.time() - last_ts) < 29 * 24 * 3600:
                    continue  # less than 29 days since last cleanup, skip

            from hybrid.plugins.db import delete_inv_entry
            now = get_current_datetime()
            cleaned = 0
            for uid, (inv_id, msg_id) in list(temp.INV_DICT.items()):
                if not CRYPTO_STAT:
                    continue
                try:
                    inv = await cp.get_invoice(inv_id)
                    if inv and getattr(inv, "status", None) == "paid":
                        continue  # never touch paid
                    if inv and getattr(inv, "status", None) == "active":
                        created = getattr(inv, "created_at", None)
                        if created:
                            age = (now - created.replace(tzinfo=timezone.utc)).total_seconds()
                            if age < 30 * 24 * 3600:
                                continue  # less than 30 days old, skip
                    temp.INV_DICT.pop(uid, None)
                    await delete_inv_entry(uid)
                    if inv_id in temp.PENDING_INV:
                        temp.PENDING_INV.remove(inv_id)
                    cleaned += 1
                except Exception as e:
                    logging.debug(f"Monthly cleanup check failed for {inv_id}: {e}")

            import time as _time
            await redis_client.set("last_invoice_cleanup", str(_time.time()))
            if cleaned:
                logging.info(f"Monthly invoice cleanup: removed {cleaned} old unpaid invoices.")
        except Exception as e:
            logging.error(f"Monthly invoice cleanup error: {e}")


def _build_startup_message(bot_username: str, start_timestamp) -> str:
    """Build admin startup notification with version and changelog from git."""
    import subprocess
    version = "1.0.0"
    last_updated = getattr(start_timestamp, "strftime", lambda x: str(start_timestamp))( "%d/%m/%Y" )
    changelog_lines = []
    try:
        ver = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            text=True,
            timeout=2,
        ).strip()
        if ver:
            version = ver
    except Exception as e:
        logging.debug(f"_build_startup_message git describe failed: {e}")
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log = subprocess.check_output(
            ["git", "log", "-5", "--oneline", "--no-decorate"],
            cwd=root,
            text=True,
            timeout=2,
        ).strip()
        if log:
            for line in log.split("\n")[:5]:
                changelog_lines.append(f"• {line}")
        desc = subprocess.check_output(
            ["git", "log", "-1", "--format=%s"],
            cwd=root,
            text=True,
            timeout=2,
        ).strip()
        if desc and not changelog_lines:
            changelog_lines.append(f"• {desc}")
    except Exception:
        changelog_lines = ["• (changelog from git unavailable)"]
    changelog = "\n".join(changelog_lines) if changelog_lines else "• —"
    return (
        f"<b>Rent +888:</b>\n\n"
        f"🤖 <b>Bot Version Info</b>\n\n"
        f"<b>Version:</b> <code>{version}</code>\n"
        f"<b>Last Updated:</b> <code>{last_updated}</code>\n\n"
        f"<b>📋 Changelog:</b>\n\n"
        f"{changelog}\n\n"
        f"@{bot_username} Started — {start_timestamp}"
    )


class Bot(Client):
    # Session file: rental-bot.session (in cwd). If you get 401 SessionRevoked after
    # changing BOT_TOKEN, delete rental-bot.session and restart so Pyrogram logs in with the new token.
    def __init__(self):
        super().__init__(
            name="rental-bot",
            api_hash=API_HASH,
            api_id=API_ID,
            plugins=plugins,
            workers=32,
            bot_token=BOT_TOKEN
        )
    
    async def panic(self): # for use in plugins
        logging.info("\nBot Stopped. Join https://t.me/hybrid_vamp for support")
        sys.exit()

    async def start(self):
        await super().start()
        usr_bot_me = await self.get_me()
        self.start_timestamp = datetime.now()

        logging.info("%s", BANNER)
        self.set_parse_mode(ParseMode.HTML)
        self.username = usr_bot_me.username
        temp.BOT_UN = self.username
        print(f"============  {temp.BOT_UN}  ============")
        logging.info("🚀 [STARTUP] @%s Bot running.", self.username)
        msg_id, user_id = get_restart_data("Bot")
        if msg_id and user_id:
            try:
                await self.edit_message_text(user_id, msg_id, "<b>Restarted Successfully!</b>")
                os.remove("restart.json")
            except Exception as e:
                logging.error(f"Failed to send restart message: {e}")
                pass

        asyncio.create_task(schedule_reminders(self))
        logging.info("🔔 [STARTUP] Reminder scheduler started (every 15 min).")
        asyncio.create_task(check_expired_numbers(self))
        logging.info("⏰ [STARTUP] Expired numbers checker started.")
        asyncio.create_task(check_7day_accs(self))
        logging.info("⏰ [STARTUP] 7-day deletion checker started.")
        # Restricted numbers detection/deletion DISABLED
        # asyncio.create_task(check_restricted_numbers(self))
        asyncio.create_task(check_payments(self))
        logging.info("💳 [STARTUP] Payment checker (CryptoBot) started.")
        asyncio.create_task(cleanup_old_invoices(self))
        logging.info("💳 [STARTUP] Monthly invoice cleanup scheduled.")

        from hybrid.plugins.db import get_all_admins
        AD_MINS = await get_all_admins()
        for id in AD_MINS:
            if id not in ADMINS:
                ADMINS.append(id)
                logging.info(f"Added {id} to ADMINS list from DB")
        await load_num_data()
        from hybrid.plugins.db import load_inv_dict
        loaded = await load_inv_dict()
        temp.INV_DICT.clear()
        temp.INV_DICT.update(loaded)
        logging.info("Loaded %d persisted invoice(s) into INV_DICT.", len(loaded))
        startup_text = _build_startup_message(self.username, self.start_timestamp)
        for id in ADMINS:
            try:
                await self.send_message(id, startup_text)
            except Exception as e:
                logging.debug(f"Bot.start send_message to admin id={id} failed: {e}")

    async def stop(self, *args):
        await super().stop()
        try:
            from hybrid.plugins.fragment import close_fragment_session
            await close_fragment_session()
        except Exception as e:
            logging.debug("Fragment session close on stop: %s", e)
        logging.info("🛑 [SHUTDOWN] Bot stopped.")

