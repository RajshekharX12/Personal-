#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import sys
import logging
import asyncio

from config import *
from aiosend import CryptoPay
from datetime import timedelta, timezone

from pyrogram import Client
from pyrogram.enums import ParseMode

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
    logging.info("Loading numbers from Fragment API...")
    from hybrid.plugins.fragment import get_fragment_numbers
    NU_MS, stat = get_fragment_numbers()
    if not stat:
        logging.error("Failed to load numbers from Fragment API.")
        return
    for n in NU_MS:
        if n not in temp.NUMBE_RS:
            temp.NUMBE_RS.append(n)
    from hybrid.plugins.db import get_number_data, get_number_info, save_number_info
    for num in temp.NUMBE_RS:
        info = get_number_info(num)
        if not info:
            save_number_info(num, D30_RATE, D60_RATE, D90_RATE, available=True)
            info = get_number_info(num)
        rented = get_number_data(num)
        if info and info.get("available", True):
            temp.AVAILABLE_NUM.append(num)
            logging.info(f"Number {num} is available.")
        if rented and rented.get("user_id"):
            temp.RENTED_NUMS.append(num)
            logging.info(f"Number {num} is rented.")


from hybrid.plugins.db import get_number_data, get_remaining_rent_days, is_restricted_del_enabled, remove_number, remove_number_data, save_restricted_number
from hybrid.plugins.db import numbers_col
from hybrid.plugins.func import get_current_datetime, check_number_conn, delete_account

async def schedule_reminders(client):
    """Schedule reminders for numbers expiring within 3 days."""
    now = get_current_datetime().replace(tzinfo=timezone.utc)  # ✅ ensure aware
    rented = numbers_col.find({"user_id": {"$exists": True}})

    for doc in rented:
        number = doc["number"]
        user_id = doc["user_id"]
        expiry = doc.get("expiry_date")
        t_hours = doc.get("hours", 0)

        if not expiry:
            continue

        expiry = expiry.replace(tzinfo=timezone.utc)  # ✅ normalize
        remaining = expiry - now
        if remaining.total_seconds() <= 0:
            continue  # already expired

        if remaining <= timedelta(days=3):
            for day in range(3):
                remind_time = now + timedelta(days=day)
                for hour in [8, 12, 16, 20, 23]:
                    remind_at = remind_time.replace(hour=hour, minute=0, second=0, microsecond=0)
                    if remind_at < expiry:
                        delay = (remind_at - now).total_seconds()
                        asyncio.create_task(send_reminder_later(client, user_id, number, delay))

async def send_reminder_later(client, user_id, number, delay):
    """Send reminder after delay."""
    await asyncio.sleep(delay)
    try:
        from hybrid.plugins.db import get_number_data
        num_data = get_number_data(number)
        start_date = num_data.get("rent_date")
        t_hours = num_data.get("hours", 0)

        from hybrid.plugins.func import format_remaining_time, t
        remaining_days = format_remaining_time(start_date, t_hours)
        text = t(user_id, "expire_soon").format(number=number, remaining_days=remaining_days)
        await client.send_message(user_id, text)
    except Exception as e:
        logging.error(f"Failed to send reminder to {user_id} for {number}: {e}")

async def check_expired_numbers(client):
    """Background checker: expire → delete immediately or request 7-day delete. Only free number when actually deleted."""
    from hybrid.plugins.func import t
    while True:
        try:
            now = get_current_datetime().replace(tzinfo=timezone.utc)
            rented = list(numbers_col.find({"user_id": {"$exists": True}}))
        except Exception as e:
            logging.error(f"check_expired_numbers: DB error (will retry): {e}")
            await asyncio.sleep(600)
            continue
        for doc in rented:
            number = doc["number"]
            user_id = doc["user_id"]
            expiry = doc.get("expiry_date")
            if not expiry:
                continue
            expiry = expiry.replace(tzinfo=timezone.utc) if getattr(expiry, "tzinfo", None) is None else expiry
            if expiry > now:
                continue
            freed = False
            try:
                try:
                    from hybrid.plugins.fragment import terminate_all_sessions
                    terminate_all_sessions(number)
                except Exception:
                    pass
                stat, reason = await delete_account(number, client)
                if stat and reason == "7Days":
                    from hybrid.plugins.db import save_7day_deletion
                    save_7day_deletion(number, now + timedelta(days=7))
                    msg = t(user_id, "expired_notify_7days").format(number=number)
                    try:
                        await client.send_message(user_id, msg)
                    except Exception as e:
                        logging.error(f"Failed to notify user {user_id} (7-day): {e}")
                    logging.info(f"Expired number {number} scheduled for 7-day deletion (user {user_id}).")
                    continue
                if stat:
                    remove_number_data(number)
                    remove_number(number, user_id)
                    freed = True
                    logging.info(f"Expired number {number} cleaned up for user {user_id}")
                if not stat and reason == "Banned":
                    logging.info(f"Number {number} is banned.")
                    if number not in temp.BLOCKED_NUMS:
                        temp.BLOCKED_NUMS.append(number)
            except Exception as e:
                logging.error(f"Error handling expired number {number}: {e}")
            finally:
                if freed:
                    if number in temp.RENTED_NUMS:
                        temp.RENTED_NUMS.remove(number)
                    if number not in temp.AVAILABLE_NUM:
                        temp.AVAILABLE_NUM.append(number)
                    text = t(user_id, "expired_notify").format(number=number)
                    try:
                        await client.send_message(user_id, text)
                    except Exception as e:
                        logging.error(f"Failed to notify user {user_id} about expired number {number}: {e}")
        await asyncio.sleep(600)

async def check_7day_accs(client):
    """Hourly background checker to make 7 days marked numbers available"""
    while True:
        now = get_current_datetime().replace(tzinfo=timezone.utc)
        from hybrid.plugins.db import get_7day_deletions, get_7day_date, remove_7day_deletion, save_7day_deletion, get_user_by_number
        numbers = get_7day_deletions()
        if not numbers:
            await asyncio.sleep(3600)
            continue
        for num in numbers:
            date = get_7day_date(num)
            if date and date <= now:
                # check = check_number_conn(num)
                check = True # TEMP SKIP
                try:
                    from hybrid.plugins.fragment import terminate_all_sessions
                    terminate_all_sessions(num)
                except:
                    pass
                if check:
                    stat, reason = await delete_account(num, client)
                    if stat and reason == "7Days":
                        logging.info(f"Account {num} still has 2FA; deletion rescheduled for 7 days.")
                        save_7day_deletion(num, now + timedelta(days=7))
                        continue
                    if stat:
                        if num in temp.RENTED_NUMS:
                            temp.RENTED_NUMS.remove(num)
                        if num not in temp.AVAILABLE_NUM:
                            temp.AVAILABLE_NUM.append(num)
                        user_data = get_user_by_number(num)
                        if user_data:
                            user_id, _hour, _date = user_data
                            remove_number_data(num)
                            remove_number(num, user_id)
                    if not stat:
                        if reason == "Banned":
                            logging.info(f"Number {num} is banned.")
                            if num not in temp.BLOCKED_NUMS:
                                temp.BLOCKED_NUMS.append(num)
                            continue
                        logging.error(f"Failed to delete account {num}: {reason}")
                        continue
                else:
                    if num in temp.RENTED_NUMS:
                        temp.RENTED_NUMS.remove(num)
                    if num not in temp.AVAILABLE_NUM:
                        temp.AVAILABLE_NUM.append(num)
                    user_data = get_user_by_number(num)
                    if user_data:
                        user_id, _hour, _date = user_data
                        remove_number_data(num)
                        remove_number(num, user_id)
        await asyncio.sleep(3600)

async def check_restricted_numbers(client):
    """Check and log restricted numbers from Fragment. Runs once a day"""
    while True:
        from hybrid.plugins.fragment import get_restricted_numbers
        restricted = get_restricted_numbers()
        if not restricted:
            logging.warning("No restricted numbers found or fetch failed; retrying in 24h.")
            await asyncio.sleep(86400)
            continue

        for num in restricted:
            logging.info(f"Number {num} is restricted by Fragment.")
            if num not in temp.RESTRICTED_NUMS:
                temp.RESTRICTED_NUMS.append(num)

            num_data = get_number_data(num)
            user_id = num_data.get("user_id") if num_data else None
            if not user_id:
                continue

            stat, reason = save_restricted_number(num)
            if not stat and reason == "ALREADY":
                from hybrid.plugins.db import get_rest_num_date
                from hybrid.plugins.func import t
                date = get_rest_num_date(num)
                now = get_current_datetime()

                if date and date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)

                if date and (now - date).days >= 3:
                    if not is_restricted_del_enabled():
                        logging.info("Restricted auto-deletion is disabled. Skipping deletion.")
                        continue

                    try:
                        from hybrid.plugins.fragment import terminate_all_sessions
                        terminate_all_sessions(num)
                    except Exception:
                        pass

                    stat, reason = await delete_account(num, client)
                    if stat and reason == "7Days":
                        logging.info(f"Deleted account {num} after 7 days")
                        from hybrid.plugins.db import save_7day_deletion
                        save_7day_deletion(num, now + timedelta(days=7))
                    if stat:
                        remove_number_data(num)
                        remove_number(num, user_id)
                    if not stat and reason == "Banned":
                        logging.info(f"Number {num} is banned.")
                        if num not in temp.BLOCKED_NUMS:
                            temp.BLOCKED_NUMS.append(num)
                        continue
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
                


class Bot(Client):
    def __init__(self):
        super().__init__(
            name=f"rental-{gen_4letters()}",
            api_hash=API_HASH,
            api_id=API_ID,
            plugins=plugins,
            workers=50,
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
        self.set_parse_mode(ParseMode.MARKDOWN)
        self.username = usr_bot_me.username
        temp.BOT_UN = self.username
        print(f"============  {temp.BOT_UN}  ============")
        logging.info(f"@{self.username} Bot Running..!")
        msg_id, user_id = get_restart_data("Bot")
        if msg_id and user_id:
            try:
                await self.edit_message_text(user_id, msg_id, "**Restarted Successfully!**")
                os.remove("restart.json")
            except Exception as e:
                logging.error(f"Failed to send restart message: {e}")
                pass

        await schedule_reminders(self)
        asyncio.create_task(check_expired_numbers(self))
        logging.info("Started background task to check expired numbers.")
        asyncio.create_task(check_7day_accs(self))
        logging.info("Started background task to check 7-day deletion accounts.")
        asyncio.create_task(check_restricted_numbers(self))
        logging.info("Started daily task to check restricted numbers.")

        from hybrid.plugins.db import get_all_admins
        AD_MINS = get_all_admins()
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


