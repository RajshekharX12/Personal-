#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import sys
import logging
import asyncio

from config import *
from aiosend import CryptoPay
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

CRYPTO_STAT = False
if CRYPTO_API:
    try:
        cp = CryptoPay(CRYPTO_API)
        CRYPTO_STAT = True
    except Exception as e:
        logging.error(f"Failed to initialize CryptoPay: {e}")

plugins = dict(root="hybrid/plugins")

def gen_4letters():
    import random
    import string
    return ''.join(random.choices(string.ascii_letters, k=4))

from hybrid.services.expiry_service import load_num_data, check_expired_numbers, check_7day_accs


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
    except Exception:
        pass
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

        from hybrid.services.reminder_service import schedule_reminders
        asyncio.create_task(schedule_reminders(self))
        logging.info("Started reminder scheduler (every 30 min).")
        asyncio.create_task(check_expired_numbers(self))
        logging.info("Started background task to check expired numbers.")
        asyncio.create_task(check_7day_accs(self))
        logging.info("Started background task to check 7-day deletion accounts.")
        # Restricted numbers detection/deletion DISABLED
        # asyncio.create_task(check_restricted_numbers(self))
        from hybrid.services.payment_service import check_payments, cleanup_expired_invoices
        asyncio.create_task(check_payments(self))
        logging.info("Started payment checker (CryptoBot + Tonkeeper).")
        asyncio.create_task(cleanup_expired_invoices(self))
        logging.info("Started invoice cleanup task (every 5 min).")

        from hybrid.repositories.db import get_all_admins
        AD_MINS = await get_all_admins()
        for id in AD_MINS:
            if id not in ADMINS:
                ADMINS.append(id)
                logging.info(f"Added {id} to ADMINS list from DB")
        await load_num_data()
        startup_text = _build_startup_message(self.username, self.start_timestamp)
        for id in ADMINS:
            try:
                await self.send_message(id, startup_text)
            except Exception:
                pass

    async def stop(self, *args):
        await super().stop()
        logging.info("Bot stopped.")

