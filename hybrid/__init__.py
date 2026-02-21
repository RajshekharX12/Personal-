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

from datetime import datetime
from logging.handlers import RotatingFileHandler

from hybrid.plugins.temp import temp
from hybrid.plugins.func import get_restart_data

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
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
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

CRYPTO_STAT = True

if CRYPTO_API:
    try:
        cp = CryptoPay(CRYPTO_API)
    except Exception as e:
        CRYPTO_STAT = False
        logging.error(f"Failed to initialize CryptoPay: {e}")
        pass

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
    logging.info("Loading numbers from Fragment API...")
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
    for n in NU_MS:
        if n not in temp.NUMBE_RS:
            temp.NUMBE_RS.append(n)
    from hybrid.plugins.db import get_number_data, get_number_info, save_number_info
    for num in temp.NUMBE_RS:
        info = await get_number_info(num)
        if not info:
            await save_number_info(num, D30_RATE, D60_RATE, D90_RATE, available=True)
            info = await get_number_info(num)
        rented = await get_number_data(num)
        if info and info.get("available", True):
            temp.AVAILABLE_NUM.append(num)
            logging.info(f"Number {num} is available.")
        if rented and rented.get("user_id"):
            temp.RENTED_NUMS.append(num)
            logging.info(f"Number {num} is rented.")


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
                        from hybrid.plugins.db import client as redis_client
                        already_sent = await redis_client.get(redis_key)
                        if already_sent:
                            continue
                        try:
                            remaining_str = format_remaining_time(doc.get("rent_date"), doc.get("hours", 0))
                            text = (await t(user_id, "expire_soon")).format(
                                number=number,
                                remaining_days=remaining_str
                            )
                            keyboard = InlineKeyboardMarkup([[
                                InlineKeyboardButton(
                                    await t(user_id, "renew"),
                                    callback_data=f"renew_{number}"
                                )
                            ]])
                            await client.send_message(user_id, text, reply_markup=keyboard)
                            # Mark as sent, expire key after threshold so it doesn't linger
                            await redis_client.set(redis_key, "1", ex=int(threshold_secs) + 3600)
                            logging.info(f"Sent {label} reminder to {user_id} for {number}")
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
    try:
        async with EXPIRED_DELETE_SEMAPHORE:
            try:
                from hybrid.plugins.fragment import terminate_all_sessions_async
                await terminate_all_sessions_async(number)
            except Exception:
                pass
            stat, reason = await delete_account(number, client)
        if stat:
            await remove_number_data(number)
            await remove_number(number, user_id)
        if reason == "7Days":
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
        # Verify number is free on Fragment before relisting
        try:
            from hybrid.plugins.fragment import fragment_api
            is_free = await fragment_api.check_is_number_free(number)
            if is_free:
                async with temp.get_lock():
                    if number not in temp.AVAILABLE_NUM:
                        temp.AVAILABLE_NUM.append(number)
                logging.info(f"Number {number} confirmed free on Fragment, relisted.")
            else:
                logging.info(f"Number {number} not yet free on Fragment, skipping relist.")
        except Exception as e:
            logging.error(f"Fragment check failed for {number}: {e}")
            async with temp.get_lock():
                if number not in temp.AVAILABLE_NUM:
                    temp.AVAILABLE_NUM.append(number)
        from hybrid.plugins.func import t
        text = (await t(user_id, "expired_notify")).format(number=number)
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
        await asyncio.sleep(600)

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
                # Check if still logged in from initial attempt (session may be in pending-deletion state)
                try:
                    me = await temp_client.get_me()
                except Exception:
                    me = None
                if me is not None:
                    try:
                        await temp_client.invoke(functions.account.DeleteAccount(reason="Cleanup"))
                        try:
                            from hybrid.plugins.fragment import fragment_api
                            is_free = await fragment_api.check_is_number_free(num)
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
                            # Fallback: full re-login via delete_account
                            stat, reason = await delete_account(num, client)
                            if stat:
                                async with temp.get_lock():
                                    if num in temp.RENTED_NUMS:
                                        temp.RENTED_NUMS.remove(num)
                                try:
                                    from hybrid.plugins.fragment import fragment_api
                                    is_free = await fragment_api.check_is_number_free(num)
                                    if is_free:
                                        async with temp.get_lock():
                                            if num not in temp.AVAILABLE_NUM:
                                                temp.AVAILABLE_NUM.append(num)
                                        logging.info(f"Number {num} confirmed free on Fragment, relisted.")
                                    else:
                                        logging.info(f"Number {num} not yet free on Fragment, skipping relist.")
                                except Exception as e:
                                    logging.error(f"Fragment check failed for {num}: {e}")
                                    async with temp.get_lock():
                                        if num not in temp.AVAILABLE_NUM:
                                            temp.AVAILABLE_NUM.append(num)
                                user_id, _, _ = await get_user_by_number(num)
                                if user_id:
                                    await remove_number_data(num)
                                    await remove_number(num, user_id)
                                await remove_7day_deletion(num)
                            continue
                    # Cleanup after successful completion
                    user_id, _, _ = await get_user_by_number(num)
                    if user_id:
                        await remove_number_data(num)
                        await remove_number(num, user_id)
                    await remove_7day_deletion(num)
                    async with temp.get_lock():
                        if num in temp.RENTED_NUMS:
                            temp.RENTED_NUMS.remove(num)
                    try:
                        from hybrid.plugins.fragment import fragment_api
                        is_free = await fragment_api.check_is_number_free(num)
                        if is_free:
                            async with temp.get_lock():
                                if num not in temp.AVAILABLE_NUM:
                                    temp.AVAILABLE_NUM.append(num)
                            logging.info(f"Number {num} confirmed free on Fragment, relisted.")
                        else:
                            logging.info(f"Number {num} not yet free on Fragment, skipping relist.")
                    except Exception as e:
                        logging.error(f"Fragment check failed for {num}: {e}")
                        async with temp.get_lock():
                            if num not in temp.AVAILABLE_NUM:
                                temp.AVAILABLE_NUM.append(num)
                else:
                    logging.warning(f"Session expired for {num}, attempting full re-login to complete deletion.")
                    stat, reason = await delete_account(num, client)
                    if stat and reason == "7Days":
                        logging.info(f"Deleted account {num} after 7 days (re-login path).")
                        await save_7day_deletion(num, now)
                    elif stat:
                        async with temp.get_lock():
                            if num in temp.RENTED_NUMS:
                                temp.RENTED_NUMS.remove(num)
                        try:
                            from hybrid.plugins.fragment import fragment_api
                            is_free = await fragment_api.check_is_number_free(num)
                            if is_free:
                                async with temp.get_lock():
                                    if num not in temp.AVAILABLE_NUM:
                                        temp.AVAILABLE_NUM.append(num)
                                logging.info(f"Number {num} confirmed free on Fragment, relisted.")
                            else:
                                logging.info(f"Number {num} not yet free on Fragment, skipping relist.")
                        except Exception as e:
                            logging.error(f"Fragment check failed for {num}: {e}")
                            async with temp.get_lock():
                                if num not in temp.AVAILABLE_NUM:
                                    temp.AVAILABLE_NUM.append(num)
                        user_id, _, _ = await get_user_by_number(num)
                        if user_id:
                            await remove_number_data(num)
                            await remove_number(num, user_id)
                        await remove_7day_deletion(num)
                    elif reason == "Banned":
                        pass  # Banned feature disabled
            except Exception as e:
                logging.error(f"Error completing 7-day deletion for {num}: {e}")
                try:
                    stat, reason = await delete_account(num, client)
                    if stat:
                        user_id, _, _ = await get_user_by_number(num)
                        if user_id:
                            await remove_number_data(num)
                            await remove_number(num, user_id)
                        await remove_7day_deletion(num)
                        async with temp.get_lock():
                            if num in temp.RENTED_NUMS:
                                temp.RENTED_NUMS.remove(num)
                        try:
                            from hybrid.plugins.fragment import fragment_api
                            is_free = await fragment_api.check_is_number_free(num)
                            if is_free:
                                async with temp.get_lock():
                                    if num not in temp.AVAILABLE_NUM:
                                        temp.AVAILABLE_NUM.append(num)
                                logging.info(f"Number {num} confirmed free on Fragment, relisted.")
                            else:
                                logging.info(f"Number {num} not yet free on Fragment, skipping relist.")
                        except Exception as e:
                            logging.error(f"Fragment check failed for {num}: {e}")
                            async with temp.get_lock():
                                if num not in temp.AVAILABLE_NUM:
                                    temp.AVAILABLE_NUM.append(num)
                except Exception as e2:
                    logging.error(f"Fallback delete_account failed for {num}: {e2}")
            finally:
                if getattr(temp_client, "is_connected", False):
                    await temp_client.disconnect()
        await asyncio.sleep(3600)

async def check_restricted_numbers(client):
    """Check and log restricted numbers from Fragment. Runs once a day"""
    while True:
        from hybrid.plugins.fragment import get_restricted_numbers_async
        restricted, _ = await get_restricted_numbers_async()
        if not restricted:
            logging.error("No Restricted numbers found or failed to fetch.")
            return

        for num in restricted:
            logging.info(f"Number {num} is restricted by Fragment.")
            if num not in temp.RESTRICTED_NUMS:
                temp.RESTRICTED_NUMS.append(num)

            num_data = await get_number_data(num)
            user_id = num_data.get("user_id") if num_data else None
            if not user_id:
                continue

            stat, reason = await save_restricted_number(num)
            if not stat and reason == "ALREADY":
                from hybrid.plugins.db import get_rest_num_date
                from hybrid.plugins.func import t
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
                    except Exception:
                        pass

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
                    text = t(user_id, "restricted_notify").format(number=num, days=days_remaining)
                    try:
                        await client.send_message(user_id, text)
                    except Exception as e:
                        logging.error(f"Failed to notify user {user_id} about restricted number {num}: {e}")
                continue

            text = t(user_id, "restricted_notify").format(number=num, days=3)
            try:
                await client.send_message(user_id, text)
            except Exception as e:
                logging.error(f"Failed to notify user {user_id} about restricted number {num}: {e}")

        await asyncio.sleep(86400)


async def check_payments(client):
    """Background: verify CryptoBot invoices and Tonkeeper orders. Update messages when paid."""
    import requests
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from hybrid.plugins.temp import temp
    from hybrid.plugins.db import get_user_balance, save_user_balance, get_ton_order, delete_ton_order, get_all_pending_ton_orders
    from hybrid.plugins.func import t, resolve_payment_keyboard
    from config import TON_WALLET, TON_API_TOKEN

    while True:
        try:
            pending_ton = await get_all_pending_ton_orders() if TON_WALLET else []
            if TON_WALLET and pending_ton:
                from hybrid.plugins.func import check_tonkeeper_payments
                await check_tonkeeper_payments(
                    client, get_user_balance, save_user_balance, delete_ton_order,
                    get_all_pending_ton_orders, t, TON_WALLET
                )
            # 1. CryptoBot pending invoices
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
                            try:
                                await client.edit_message_text(user_id, msg_id, "⌛")
                            except Exception:
                                pass
                            payload = (getattr(inv, "payload", "") or "").strip()
                            current_bal = await get_user_balance(user_id) or 0.0
                            new_bal = current_bal + float(inv.amount)
                            await save_user_balance(user_id, new_bal)
                            keyboard = await resolve_payment_keyboard(user_id, payload)
                            try:
                                await client.edit_message_text(
                                    user_id, msg_id,
                                    await t(user_id, "payment_confirmed"),
                                    reply_markup=keyboard
                                )
                            except Exception:
                                pass
                            temp.INV_DICT.pop(user_id, None)
                            if inv_id in temp.PENDING_INV:
                                temp.PENDING_INV.remove(inv_id)
                    except Exception as e:
                        logging.debug(f"CryptoBot check invoice {inv_id}: {e}")

            # 2. Tonkeeper (if not already run this loop)
            if TON_WALLET and not pending_ton:
                from hybrid.plugins.func import check_tonkeeper_payments
                await check_tonkeeper_payments(
                    client, get_user_balance, save_user_balance, delete_ton_order,
                    get_all_pending_ton_orders, t, TON_WALLET
                )
        except Exception as e:
            logging.error(f"Payment checker error: {e}")
        pending_ton = await get_all_pending_ton_orders() if TON_WALLET else []
        await asyncio.sleep(6 if pending_ton else 12)


async def cleanup_expired_invoices(client):
    """Remove stale invoices from temp.INV_DICT that are older than 30 minutes."""
    while True:
        try:
            now = get_current_datetime()
            stale = []
            for uid, (inv_id, msg_id) in list(temp.INV_DICT.items()):
                # Try to cancel if still pending
                if CRYPTO_STAT:
                    try:
                        inv = await cp.get_invoice(inv_id)
                        if inv and getattr(inv, "status", None) == "pending":
                            created = getattr(inv, "created_at", None)
                            if created:
                                age = (now - created.replace(tzinfo=timezone.utc)).total_seconds()
                                if age > 1800:  # 30 minutes
                                    await cp.cancel_invoice(inv_id)
                                    stale.append(uid)
                        elif inv and getattr(inv, "status", None) != "pending":
                            stale.append(uid)
                    except Exception as e:
                        logging.debug(f"Invoice cleanup check failed for {inv_id}: {e}")
            for uid in stale:
                inv_id, msg_id = temp.INV_DICT.pop(uid, (None, None))
                if inv_id and inv_id in temp.PENDING_INV:
                    temp.PENDING_INV.remove(inv_id)
                logging.info(f"Cleaned up stale invoice {inv_id} for user {uid}")
        except Exception as e:
            logging.error(f"Invoice cleanup error: {e}")
        await asyncio.sleep(300)  # Run every 5 minutes


class Bot(Client):
    def __init__(self):
        super().__init__(
            name="rental-bot",
            api_hash=API_HASH,
            api_id=API_ID,
            plugins=plugins,
            workers=8,
            bot_token=BOT_TOKEN
        )
    
    async def panic(self): # for use in plugins
        logging.info("\nBot Stopped. Join https://t.me/hybrid_vamp for support")
        sys.exit()

    async def start(self):
        await super().start()
        usr_bot_me = await self.get_me()
        self.start_timestamp = datetime.now()

        logging.info(f"{BANNER}")
        self.set_parse_mode(ParseMode.HTML)
        self.username = usr_bot_me.username
        temp.BOT_UN = self.username
        print(f"============  {temp.BOT_UN}  ============")
        logging.info(f"@{self.username} Bot Running..!")
        msg_id, user_id = get_restart_data("Bot")
        if msg_id and user_id:
            try:
                await self.edit_message_text(user_id, msg_id, "<b>Restarted Successfully!</b>")
                os.remove("restart.json")
            except Exception as e:
                logging.error(f"Failed to send restart message: {e}")
                pass

        asyncio.create_task(schedule_reminders(self))
        logging.info("Started reminder scheduler (every 30 min).")
        asyncio.create_task(check_expired_numbers(self))
        logging.info("Started background task to check expired numbers.")
        asyncio.create_task(check_7day_accs(self))
        logging.info("Started background task to check 7-day deletion accounts.")
        # Restricted numbers detection/deletion DISABLED
        # asyncio.create_task(check_restricted_numbers(self))
        asyncio.create_task(check_payments(self))
        logging.info("Started payment checker (CryptoBot + Tonkeeper).")
        asyncio.create_task(cleanup_expired_invoices(self))
        logging.info("Started invoice cleanup task (every 5 min).")

        from hybrid.plugins.db import get_all_admins
        AD_MINS = await get_all_admins()
        for id in AD_MINS:
            if id not in ADMINS:
                ADMINS.append(id)
                logging.info(f"Added {id} to ADMINS list from DB")
        await load_num_data()
        for id in ADMINS:
            try:
                await self.send_message(id, f"@{self.username} Started\n{self.start_timestamp}")
            except:
                pass

    async def stop(self, *args):
        await super().stop()
        logging.info("Bot stopped.")

