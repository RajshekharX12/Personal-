#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import re
import os
import time
import html
import random
import asyncio
import subprocess
import psutil
import platform
from datetime import datetime, timezone, timedelta

from pyrogram.enums import ParseMode
from pyrogram.types import Message
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import CallbackQuery
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from hybrid import Bot, LOG_FILE_NAME, logging, ADMINS, gen_4letters
from hybrid.plugins.temp import temp
from hybrid.plugins.func import *
from hybrid.plugins.db import *
from hybrid.plugins.db import ping_redis

from aiosend.types import Invoice

DEFAULT_ADMIN_BACK_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Back to Admin Menu", callback_data="admin_panel")]]
)

# =========== CryptoPay Integration (if applicable) =========== #

# @cp.invoice_paid()
# async def handle_payment(invoice: Invoice, message=None):
#     user_id = int(invoice.payload)
#     amount = float(invoice.amount)

#     old_balance = get_user_balance(user_id) or 0.0
#     save_user_balance(user_id, old_balance + amount)

#     try:
#         await Bot().send_message(
#             user_id,
#             f"✅ Payment received!\n💰 {amount} {invoice.asset} added to your balance."
#         )
#     except Exception as e:
#         logging.error(f"Failed to notify user {user_id}: {e}")


# ===================== Command Handlers ===================== #

@Bot.on_message(filters.command('start') & filters.private)
async def start_command(client: Client, message: Message):
    user = message.from_user
    await save_user_id(user.id)

    rows = [
        [InlineKeyboardButton(t(user.id, "rent"), callback_data="rentnum"),
         InlineKeyboardButton(t(user.id, "my_rentals"), callback_data="my_rentals")],
        [InlineKeyboardButton(t(user.id, "profile"), callback_data="profile"),
         InlineKeyboardButton(t(user.id, "help"), callback_data="help")],
        [InlineKeyboardButton(t(user.id, "contact_support"), url="https://t.me/aress")]
    ]

    if user.id in ADMINS:
        rows.insert(0, [InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")])

    await message.reply_text(t(user.id, "welcome", name=user.mention), reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)


@Bot.on_message(filters.command("ping") & filters.private & filters.user(ADMINS))
async def ping_command(client: Client, message: Message):
    start = time.monotonic()
    sent = await message.reply("🏓 Pinging...")
    telegram_ms = (time.monotonic() - start) * 1000

    redis_ms = await ping_redis()

    def speed_emoji(ms):
        if ms < 200:
            return "🟢"
        elif ms < 500:
            return "🟡"
        else:
            return "🔴"

    text = (
        f"🏓 <b>Pong!</b>\n\n"
        f"{speed_emoji(telegram_ms)} <b>Telegram:</b> <code>{telegram_ms:.0f}ms</code>\n"
        f"{speed_emoji(redis_ms)} <b>Redis:</b> <code>{redis_ms:.0f}ms</code>"
    )

    await sent.edit_text(text, parse_mode=ParseMode.HTML)


@Bot.on_message(filters.command("update") & filters.user(ADMINS))
async def update_restart(_, message):
    try:
        out = subprocess.check_output(["git", "pull"]).decode("UTF-8")
        if "Already up to date." in str(out):
            return await message.reply_text("Its already up-to date!", parse_mode=ParseMode.HTML)
        await message.reply_text(f"<pre>{html.escape(out)}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        return await message.reply_text(str(e))
    m = await message.reply_text("<b>Updated with default branch, restarting now...</b>", parse_mode=ParseMode.HTML)
    restart("Bot", m)

@Bot.on_message(filters.command("restart") & filters.user(ADMINS))
async def command_restart(_, message):
    m = await message.reply_text("<b>Restarting...</b>", parse_mode=ParseMode.HTML)
    restart("Bot", m)

@Bot.on_message(filters.command("logs") & filters.user(ADMINS))
async def logs_cmd(_, message):
    await message.reply_document(document=LOG_FILE_NAME)


@Bot.on_message(filters.command("setprices") & filters.user(ADMINS))
async def set_prices_cmd(client, message):
    try:
        args = message.text.split()[1]
        prices = list(map(float, args.strip().split(",")))
        if len(prices) != 3 or any(p <= 0 for p in prices):
            return await message.reply("❌ Usage: /setprices 90,170,250")
        price_30, price_60, price_90 = prices
    except Exception:
        return await message.reply(
            "❌ Usage: /setprices 90,170,250\n"
            "Updates prices for ALL numbers at once."
        )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"setprices_confirm|{price_30}|{price_60}|{price_90}"),
            InlineKeyboardButton("❌ Cancel", callback_data="setprices_cancel"),
        ]
    ])
    await message.reply(
        f"⚠️ Are you sure you want to update prices for ALL numbers?\n\n"
        f"• 30 days: {price_30} USDT\n"
        f"• 60 days: {price_60} USDT\n"
        f"• 90 days: {price_90} USDT",
        reply_markup=keyboard
    )


@Bot.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_cmd(_, message: Message):
    try:
        msg = await message.reply_text("⏳ Gathering stats...", parse_mode=ParseMode.HTML)

        # Users
        all_users = await get_all_user_ids()
        total_users = len(all_users)

        # Rentals
        all_rentals = await get_all_rentals()
        active_rentals = len(all_rentals)

        # Numbers
        total_numbers = len(temp.NUMBE_RS)
        available = len([n for n in temp.AVAILABLE_NUM if n not in temp.RENTED_NUMS and n not in temp.UN_AV_NUMS])
        rented = len(temp.RENTED_NUMS)
        unavailable = len(temp.UN_AV_NUMS)

        # 7-day pending deletions
        from hybrid.plugins.db import get_7day_deletions
        pending_deletions = len(await get_7day_deletions())

        # Pending CryptoBot invoices
        pending_crypto = len(temp.PENDING_INV)

        # Revenue
        from hybrid.plugins.db import get_total_revenue, client as redis_client
        total_revenue = await get_total_revenue()
        now = datetime.now(timezone.utc)
        this_month_key = f"revenue:month:{now.strftime('%Y%m')}"
        last_month = now.replace(day=1) - timedelta(days=1)
        last_month_key = f"revenue:month:{last_month.strftime('%Y%m')}"
        this_month_rev = await redis_client.get(this_month_key)
        last_month_rev = await redis_client.get(last_month_key)
        this_month_rev = float(this_month_rev) if this_month_rev else 0.0
        last_month_rev = float(last_month_rev) if last_month_rev else 0.0

        # Total balances
        total_balance, users_with_balance = await get_total_balance()

        text = (
            f"<b>📊 Bot Dashboard</b>\n\n"
            f"<b>👥 Users</b>\n"
            f"• Total Users: <b>{total_users}</b>\n"
            f"• Users with Balance: <b>{users_with_balance}</b>\n"
            f"• Total User Balances: <b>{total_balance:.2f} USDT</b>\n\n"
            f"<b>📞 Numbers</b>\n"
            f"• Total in Pool: <b>{total_numbers}</b>\n"
            f"• 🟢 Available: <b>{available}</b>\n"
            f"• 🔴 Rented: <b>{rented}</b>\n"
            f"• 🔒 Disabled: <b>{unavailable}</b>\n\n"
            f"<b>🛒 Rentals</b>\n"
            f"• Active Rentals: <b>{active_rentals}</b>\n"
            f"• Pending 7-Day Deletions: <b>{pending_deletions}</b>\n\n"
            f"<b>💰 Revenue</b>\n"
            f"• This Month: <b>{this_month_rev:.2f} USDT</b>\n"
            f"• Last Month: <b>{last_month_rev:.2f} USDT</b>\n"
            f"• All Time:   <b>{total_revenue:.2f} USDT</b>\n\n"
            f"<b>⏳ Pending Payments</b>\n"
            f"• CryptoBot Invoices: <b>{pending_crypto}</b>\n"
        )
        await msg.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"❌ Failed to gather stats: {e}", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("cleardb") & filters.user(ADMINS))
async def clear_db_cmd(_, message):
    try:
        response = await message.chat.ask(
            "⚠️ Are you sure you want to clear the database? This action cannot be undone. Type 'YES' to confirm.",
            timeout=30
        )
    except Exception:
        return await message.reply_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", parse_mode=ParseMode.HTML)
    if response.text.strip().upper() != "YES":
        return await message.reply_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Database clear operation cancelled.", parse_mode=ParseMode.HTML)
    stat, _ = await delete_all_data()
    if stat:
        from hybrid.plugins.db import log_admin_action
        await log_admin_action(message.from_user.id, "cleardb", "all", None)
        await message.reply_text("<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> All data has been cleared from the database.", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("sysinfo") & filters.user(ADMINS))
async def sysinfo_cmd(_, message):
    try:
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        sys_info = (
            f"<b>System Information:</b>\n"
            f"🖥️ System: {platform.system()} {platform.release()}\n"
            f"💻 Machine: {platform.machine()}\n"
            f"🧠 CPU Usage: {cpu_usage}%\n"
            f"💾 Memory: {memory.percent}% used of {round(memory.total / (1024 ** 3), 2)} GB\n"
            f"🗄️ Disk: {disk.percent}% used of {round(disk.total / (1024 ** 3), 2)} GB\n"
        )
        await message.reply_text(sys_info, parse_mode=ParseMode.HTML)
    except ImportError:
        await message.reply_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> psutil module is not installed. Please install it to use this command.", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("addadmin") & filters.user(ADMINS))
async def add_admin_cmd(_, message):
    if len(message.command) != 2:
        return await message.reply_text("Usage: /addadmin <user_id>", parse_mode=ParseMode.HTML)
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid user ID. Please provide a valid integer.", parse_mode=ParseMode.HTML)
    success, status = await add_admin(user_id)
    if success:
        from hybrid.plugins.db import log_admin_action
        await log_admin_action(message.from_user.id, "addadmin", str(user_id), None)
        await message.reply_text(f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> User {user_id} has been added as an admin.", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> User {user_id} could not be added. Status: {status}", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("remadmin") & filters.user(ADMINS))
async def remove_admin_cmd(_, message):
    if len(message.command) != 2:
        return await message.reply_text("Usage: /removeadmin <user_id>", parse_mode=ParseMode.HTML)
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid user ID. Please provide a valid integer.", parse_mode=ParseMode.HTML)
    success, status = await remove_admin(user_id)
    if success:
        from hybrid.plugins.db import log_admin_action
        await log_admin_action(message.from_user.id, "remadmin", str(user_id), None)
        await message.reply_text(f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> User {user_id} has been removed from admins.", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> User {user_id} could not be removed. Status: {status}", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("broadcast") & filters.user(ADMINS))
async def broadcast_cmd(_, message):
    if not message.reply_to_message:
        return await message.reply_text("Usage: /broadcast as reply to a message", parse_mode=ParseMode.HTML)
    broadcast_message = message.reply_to_message
    if not broadcast_message:
        return await message.reply_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Please reply to a text message to broadcast.", parse_mode=ParseMode.HTML)
    user_ids = await get_all_user_ids()
    success_count = 0
    fail_count = 0
    sem = asyncio.Semaphore(20)

    async def send_one(uid):
        nonlocal success_count, fail_count
        async with sem:
            try:
                await broadcast_message.copy(chat_id=uid)
                success_count += 1
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    await broadcast_message.copy(chat_id=uid)
                    success_count += 1
                except Exception as fe:
                    logging.error(f"Failed after FloodWait for {uid}: {fe}")
                    fail_count += 1
            except Exception as e:
                logging.error(f"Failed to send broadcast to {uid}: {e}")
                fail_count += 1

    await asyncio.gather(*[send_one(uid) for uid in user_ids], return_exceptions=True)

    await message.reply_text(f"📢 Broadcast completed!\n<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Success: {success_count}\n<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Failed: {fail_count}", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("checknum") & filters.user(ADMINS))
async def check_num_cmd(_, message):
    try:
        response = await message.chat.ask(
            "⚠️ send the number you wanna check",
            timeout=30
        )
    except Exception:
        return await message.reply_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", parse_mode=ParseMode.HTML)
    number = response.text if response.text.startswith("+888") else False
    if not number:
        return await message.reply_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid number format. Please send a valid number starting with +888.", parse_mode=ParseMode.HTML)

    check = check_number_conn(number)
    if check:
        return await message.reply_text(f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Number {number} is available.", parse_mode=ParseMode.HTML)
    else:
        return await message.reply_text(f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Number {number} is not available.", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("exportcsv") & filters.user(ADMINS))
async def export_csv_cmd(_, message: Message):
    try:
        msg = await message.reply_text("⏳ <b>Exporting numbers data to CSV...</b>", parse_mode=ParseMode.HTML)
        filename = await export_numbers_csv(f"numbers_export_{gen_4letters()}.csv")
        await message.reply_document(filename, caption="📑 Exported Numbers Data")
        os.remove(filename)
        await msg.delete()
    except Exception as e:
        await message.reply_text(f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Failed to export: {e}", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("createbtn") & filters.private)
async def create_button_cmd(_, message: Message):
    if len(message.command) < 3:
        return await message.reply_text("Usage: /createbtn <button_text> <data>", parse_mode=ParseMode.HTML)
    button_text = message.command[1]
    data = message.command[2]

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(button_text, callback_data=data)]])
    await message.reply_text("Here is your button:", reply_markup=keyboard, parse_mode=ParseMode.HTML)
