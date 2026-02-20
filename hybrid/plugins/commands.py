#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import re
import os
import html
import random
import asyncio
import subprocess
import psutil
import platform

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

    lang = await get_user_language(user.id)
    if not lang:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")],
            [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
            [InlineKeyboardButton("🇰🇷 한국어", callback_data="lang_ko")],
            [InlineKeyboardButton("🇨🇳 中文", callback_data="lang_zh")],
        ])
        return await message.reply_text(await t(user.id, "choose_lang"), reply_markup=keyboard, parse_mode=ParseMode.HTML)

    rows = [
        [InlineKeyboardButton(await t(user.id, "rent"), callback_data="rentnum"),
         InlineKeyboardButton(await t(user.id, "my_rentals"), callback_data="my_rentals")],
        [InlineKeyboardButton(await t(user.id, "profile"), callback_data="profile"),
         InlineKeyboardButton(await t(user.id, "help"), callback_data="help")],
        [InlineKeyboardButton(await t(user.id, "contact_support"), url="https://t.me/aress")]
    ]

    if user.id in ADMINS:
        rows.insert(0, [InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")])

    await message.reply_text(await t(user.id, "welcome", name=user.mention), reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)

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

    for user_id in user_ids:
        try:
            await broadcast_message.copy(chat_id=user_id)
            success_count += 1
            await asyncio.sleep(0.1)  # slight delay to avoid hitting rate limits
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await broadcast_message.copy(chat_id=user_id)
                success_count += 1
            except Exception as e:
                logging.error(f"Failed to send broadcast to {user_id} after FloodWait: {e}")
                fail_count += 1
        except Exception as e:
            logging.error(f"Failed to send broadcast to {user_id}: {e}")
            fail_count += 1

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
        filename = export_numbers_csv(f"numbers_export_{gen_4letters()}.csv")
        await message.reply_document(filename, caption="📑 Exported Numbers Data")
        os.remove(filename)
        await msg.delete()
    except Exception as e:
        await message.reply_text(f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Failed to export: {e}", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("banned") & filters.private)
async def banned_cmd(_, message: Message):
    await message.reply_text("🔒 Banned numbers feature is disabled.", parse_mode=ParseMode.HTML)

@Bot.on_message(filters.command("createbtn") & filters.private)
async def create_button_cmd(_, message: Message):
    if len(message.command) < 3:
        return await message.reply_text("Usage: /createbtn <button_text> <data>", parse_mode=ParseMode.HTML)
    button_text = message.command[1]
    data = message.command[2]

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(button_text, callback_data=data)]])
    await message.reply_text("Here is your button:", reply_markup=keyboard, parse_mode=ParseMode.HTML)
