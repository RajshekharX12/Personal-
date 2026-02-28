#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import re
import os
import random
import asyncio
import time
import subprocess
import psutil
import platform
import logging
from logging.handlers import RotatingFileHandler

from pyrogram.enums import ParseMode
from pyrogram.types import Message
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import CallbackQuery
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

from hybrid import Bot, LOG_FILE_NAME, logging, ADMINS, CRYPTO_STAT, gen_4letters
from hybrid.plugins.temp import temp
from hybrid.plugins.func import (
    t,
    format_number,
    normalize_phone,
    format_remaining_time,
    get_current_datetime,
    resolve_payment_keyboard,
    get_remaining_hours,
    delete_account,
    check_number_conn,
    build_number_actions_keyboard,
    build_rentnum_keyboard,
    show_numbers,
    export_numbers_csv,
    format_date,
)
from hybrid.plugins.db import (
    get_user_numbers,
    get_rented_data_for_number,
    get_rental_by_owner,
    get_number_data,
    transfer_number,
    get_user_profile_data,
    get_user_transactions,
    get_user_balance,
    get_number_info,
    save_number_info,
    get_user_by_number,
    remove_number,
    remove_number_data,
    log_admin_action,
    get_total_balance,
    save_user_balance,
    delete_inv_entry,
    save_inv_entry,
    is_payment_processed_crypto,
    mark_payment_processed_crypto,
    get_7day_deletions,
    get_7day_date,
    remove_7day_deletion,
    save_7day_deletion,
    get_rules,
    save_rules,
    save_number,
    save_rental_atomic,
    lock_number_for_rent,
    unlock_number_for_rent,
)
from hybrid.plugins.db import client as redis_client
from hybrid.plugins.fragment import fragment_api, terminate_all_sessions_async, get_login_code_async
from config import D30_RATE, D60_RATE, D90_RATE, CRYPTO_API

from datetime import datetime, timedelta, timezone

# File-only logger for [CALLBACK] / [SLOW CALLBACK] so they don't spam the terminal
_file_logger = logging.getLogger("callback.file")
_file_logger.setLevel(logging.DEBUG)
_file_logger.propagate = False
_file_handler = RotatingFileHandler(LOG_FILE_NAME, maxBytes=50000000, backupCount=10, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("[%(asctime)s - %(levelname)s] - %(name)s - %(message)s", datefmt="%d-%b-%y %H:%M:%S"))
_file_logger.addHandler(_file_handler)

if CRYPTO_STAT:
    from hybrid.__init__ import cp

DEFAULT_ADMIN_BACK_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Back to Admin Menu", callback_data="admin_panel")]]
)


async def _safe_edit(msg, text=None, reply_markup=None, client=None, **kwargs):
    """Edit message; if message has photo and client given, delete and send new text so photo is removed.
    Falls back to send_message if edit fails for any reason other than MessageNotModified."""
    kwargs.setdefault("parse_mode", ParseMode.HTML)
    try:
        if text is not None:
            if client and getattr(msg, "photo", None):
                await msg.delete()
                return await client.send_message(msg.chat.id, text, reply_markup=reply_markup, **kwargs)
            return await msg.edit_text(text, reply_markup=reply_markup, **kwargs)
        return await msg.edit(reply_markup=reply_markup, **kwargs)
    except MessageNotModified:
        return None
    except Exception as e:
        logging.error(f"Safe edit failed: {e}")
        if text and client:
            try:
                return await client.send_message(msg.chat.id, text, reply_markup=reply_markup, **kwargs)
            except Exception as e:
                logging.debug(f"_safe_edit send_message fallback failed: {e}")
        return None


# ===================== Callback Query Handler ===================== #

@Bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    import time
    start = time.monotonic()
    try:
        await _callback_handler_impl(client, query)
    except MessageNotModified:
        try:
            await query.answer()
        except Exception as e:
            logging.debug(f"callback query.answer failed: {e}")
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > 1000:
            _file_logger.warning(f"[SLOW CALLBACK] data={query.data!r} user={query.from_user.id} took {elapsed_ms:.0f}ms")


async def _callback_handler_impl(client: Client, query: CallbackQuery):
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "my_rentals":
        numbers = await get_user_numbers(user_id)
        if not numbers:
            no_rentals_t = t(user_id, "no_rentals")
            back_t = t(user_id, "back")
            return await query.message.edit_text(
                no_rentals_t,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(back_t, callback_data="back_home")]]
                ),
                parse_mode=ParseMode.HTML,
            )

        your_rentals_t = t(user_id, "your_rentals")
        back_t = t(user_id, "back")
        keyboard = []
        for n in numbers:
            norm = normalize_phone(n) or n
            rented = await get_rented_data_for_number(norm)
            if rented:
                time_left = format_remaining_time(rented.get("rent_date"), rented.get("hours", 0))
            else:
                time_left = "N/A"
            keyboard.append([
                InlineKeyboardButton(
                    f"{format_number(norm)} — {time_left}",
                    callback_data=f"num_{norm}"
                )
            ])
        keyboard.append([InlineKeyboardButton(back_t, callback_data="back_home")])

        await _safe_edit(query.message, your_rentals_t, reply_markup=InlineKeyboardMarkup(keyboard), client=client)

    elif data.startswith("num_"):
        raw = data.replace("num_", "")
        number = normalize_phone(raw) or raw
        num_text = format_number(number)
        rented_data = await get_rented_data_for_number(number)
        no_rentals_t = t(user_id, "no_rentals")
        back_t = t(user_id, "back")
        owner_id = int(rented_data.get("user_id") or 0) if rented_data else 0
        if not rented_data or owner_id != int(user_id):
            return await query.message.edit_text(
                no_rentals_t,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(back_t, callback_data="my_rentals")]]),
                parse_mode=ParseMode.HTML,
            )
        hours = rented_data.get("hours", 0)
        rent_date = rented_data.get("rent_date")
        time_left = format_remaining_time(rent_date, hours)
        date_str = format_date(str(rent_date)) if rent_date else "N/A"
        keyboard = await build_number_actions_keyboard(user_id, number, "my_rentals")
        await _safe_edit(query.message, t(user_id, "number", num=num_text, time=time_left, date=date_str), reply_markup=keyboard, client=client)

    elif data.startswith("transfer_confirm"):
        # Parse using | separator to avoid conflicts with phone number format
        if "|" in data:
            parts = data.split("|")
            if len(parts) < 3:
                return await query.answer(t(user_id, "error_occurred"), show_alert=True)
            raw_num = parts[1]
            try:
                to_user_id = int(parts[2])
            except (ValueError, TypeError):
                return await query.answer(t(user_id, "error_occurred"), show_alert=True)
        else:
            # Fallback to old format for backward compatibility
            parts = data.replace("transfer_confirm_", "").split("_", 1)
            if len(parts) < 2:
                return await query.answer(t(user_id, "error_occurred"), show_alert=True)
            raw_num, rest = parts[0], parts[1]
            try:
                to_user_id = int(rest.split("_")[0] if "_" in rest else rest)
            except (ValueError, TypeError):
                return await query.answer(t(user_id, "error_occurred"), show_alert=True)
        
        number = normalize_phone(raw_num) or raw_num
        logging.info(f"Transfer confirm: user_id={user_id}, raw_num={raw_num}, normalized={number}, to_user_id={to_user_id}")
        rented_data = await get_rental_by_owner(user_id, number)
        logging.info(f"Rental data found for transfer: number={number}, owner={rented_data.get('user_id') if rented_data else None}")
        if not rented_data:
            # Try alternative lookup
            alt_data = await get_number_data(number)
            logging.info(f"Alternative lookup for transfer: {alt_data}")
            if alt_data and int(alt_data.get("user_id", 0)) == user_id:
                rented_data = alt_data
            else:
                logging.warning(f"Transfer not found: raw={raw_num}, norm={number}, uid={user_id}")
                return await query.answer("❌ Number not found. Please try again or contact support.", show_alert=True)
        number = rented_data.get("number") or number
        success, err = await transfer_number(number, user_id, to_user_id)
        if not success:
            msg = err if err else "Transfer failed."
            return await query.answer(msg, show_alert=True)
        num_text = format_number(number)
        await record_transaction(user_id, 0, "transfer", f"Transferred {num_text} to user {to_user_id}")
        async with temp.get_lock():
            temp.RENTED_NUMS.discard(number)
            temp.RENTED_NUMS.add(number)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data="my_rentals")]])
        await _safe_edit(query.message, f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Number <b>{num_text}</b> has been transferred successfully.", reply_markup=keyboard, client=client)
        try:
            to_user = await client.get_users(to_user_id)
            duration = format_remaining_time(rented_data.get("rent_date"), rented_data.get("hours", 0))
            prev_owner = query.from_user
            prev_owner_name = f"@{prev_owner.username}" if prev_owner.username else (prev_owner.first_name or str(prev_owner.id))
            await client.send_message(
                to_user_id,
                f"🫶 The number below has been securely transferred to your account.\n\n"
                f"• <tg-emoji emoji-id=\"5422683699130933153\">👤</tg-emoji> Previous Owner: {prev_owner_name}\n\n"
                f"• <tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji> Number: {num_text}\n\n"
                f"• ⏳ Validity: {duration}\n\n"
                f"⚠️ The previous owner no longer has access. Good luck, Friend :)",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.debug(f"edit_message_text failed after transfer success: {e}")
        return

    elif data.startswith("transfer_"):
        await query.answer()
        raw = data.replace("transfer_", "").strip()
        if not raw:
            return await query.answer("Invalid request.", show_alert=True)
        number = normalize_phone(raw) or raw
        logging.info(f"Transfer attempt: user_id={user_id}, raw={raw}, normalized={number}")
        rented_data = await get_rental_by_owner(user_id, number)
        logging.info(f"Rental data found: {rented_data}")
        if not rented_data:
            # Try alternative lookup
            alt_data = await get_number_data(number)
            logging.info(f"Alternative lookup (get_number_data): {alt_data}")
            if alt_data and int(alt_data.get("user_id", 0)) == user_id:
                rented_data = alt_data
            else:
                logging.warning(f"Transfer lookup failed: raw={raw}, norm={number}, uid={user_id}")
                return await query.answer("❌ Number not found. Please try again or contact support.", show_alert=True)
        number = rented_data.get("number") or number
        num_text = format_number(number)
        try:
            response = await query.message.chat.ask(
                f"Enter @username or User ID to transfer <b>{num_text}</b> to:\n\n"
                f"Example: @johndoe or 123456789",
                timeout=60
            )
        except Exception:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data=f"num_{number}")]])
            return await query.message.edit_text(
                "<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout. Please try again.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        identifier = (response.text or "").strip()
        await response.delete()
        try:
            await response.sent_message.delete()
        except Exception as e:
            logging.debug(f"delete sent_message failed in transfer ask: {e}")
        to_user = None
        if identifier.startswith("@"):
            try:
                to_user = await client.get_users(identifier)
            except Exception as e:
                logging.debug(f"get_users failed for identifier {identifier}: {e}")
        else:
            try:
                uid = int(identifier)
                if uid != user_id:
                    to_user = await client.get_users(uid)
            except (ValueError, TypeError):
                pass
        if not to_user or to_user.is_bot:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data=f"num_{number}")]])
            return await query.message.edit_text(
                "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> User not found. They must have started this bot first.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        if to_user.id == user_id:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data=f"num_{number}")]])
            return await query.message.edit_text(
                "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> You cannot transfer to yourself.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        recipient_name = f"@{to_user.username}" if to_user.username else (to_user.first_name or str(to_user.id))
        # Use | as separator to avoid conflicts with phone number format
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(t(user_id, "confirm"), callback_data=f"transfer_confirm|{number}|{to_user.id}"),
                InlineKeyboardButton(t(user_id, "cancel"), callback_data=f"num_{number}"),
            ]
        ])
        
        caption_text = (
            f"<b>Transfer {num_text} to {recipient_name}</b>\n"
            f"<b>ID:</b> <code>{to_user.id}</code>\n\n"
            f"<b>They can:</b>\n"
            f"🔑 Get code\n"
            f"<tg-emoji emoji-id=\"5264727218734524899\">🔄</tg-emoji> Renew\n"
            f"📤 Transfer\n\n"
            f"⚠️ <b>Note:</b>\n"
            f"Once you transfer the number, you will have no access to it.\n"
            f"Please check the username twice before transferring.\n\n"
            f"❗ If you transferred to the wrong person, please contact: @Aress immediately."
        )
        
        # Try to get and show user's profile photo (edit in place to keep message ID)
        try:
            photos = [p async for p in client.get_chat_photos(to_user.id, limit=1)]
            if photos:
                await query.message.edit_media(
                    InputMediaPhoto(
                        media=photos[0].file_id,
                        caption=caption_text
                    ),
                    reply_markup=keyboard
                )
            else:
                # No profile photo, send text message
                await _safe_edit(query.message, caption_text, reply_markup=keyboard, client=client)
        except Exception as e:
            logging.error(f"Failed to get profile photo: {e}")
            # Fallback to text message
            await _safe_edit(query.message, caption_text, reply_markup=keyboard, client=client)
        return

    elif data.startswith("getcode_"):
        raw = data.replace("getcode_", "")
        number = normalize_phone(raw) or raw
        num_text = format_number(number)
        # await query.message.edit_text(f"{t(user_id, 'getting_code')} `{num_text}`...")
        code = await get_login_code_async(number)
        if code and code.isdigit():
            keyboard = [
                [InlineKeyboardButton(t(user_id, "back"), callback_data=f"num_{number}")]
            ]
            await query.message.reply(
                t(user_id, "here_is_code", code=code),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML,
            )
        else:
            # keyboard = [
            #     [InlineKeyboardButton(t(user_id, "back"), callback_data=f"num_{number}")]
            # ]
            # await query.message.edit_text(
            #     t(user_id, "no_code"),
            #     reply_markup=InlineKeyboardMarkup(keyboard)
            # )
            await query.answer(t(user_id, "no_code"), show_alert=True)

    elif data == "profile":
        user = query.from_user
        balance, method = await get_user_profile_data(user.id)
        balance = balance or 0.0
        if method == "cryptobot":
            payment_method = "CryptoBot (@send)"
        else:
            payment_method = "Not set"
        text = t(user.id, "profile_text", id=user.id, fname=user.first_name or "N/A", uname=("@" + user.username) if user.username else "N/A", bal=balance, payment_method=payment_method)
        add_bal_lbl = t(user.id, "add_balance")
        back_lbl = t(user.id, "back")
        keyboard = [
            [InlineKeyboardButton(add_bal_lbl, callback_data="add_balance")],
            [InlineKeyboardButton("📋 Transaction History", callback_data="tx_history")],
            [InlineKeyboardButton(back_lbl, callback_data="back_home")],
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    elif data == "tx_history":
        txs = await get_user_transactions(user_id)
        if not txs:
            return await query.message.edit_text(
                "📋 No transactions found.\n\n"
                "⚠️ Transaction history is kept for 30 days only.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]),
                parse_mode=ParseMode.HTML,
            )
        lines = ["<b>📋 Transaction History</b>", "<i>Last 30 days only</i>\n"]
        for tx in txs:
            amount = float(tx.get("amount", 0))
            emoji = "➕" if amount > 0 else "➖" if amount < 0 else "↔️"
            lines.append(
                f"{emoji} <b>{abs(amount):.2f} USDT</b> — {tx.get('description', '')}\n"
                f"   📅 {tx.get('date', 'N/A')}"
            )
        text = "\n".join(lines)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    elif data == "back_home":
        user = query.from_user
        welcome_t = t(user.id, "welcome", name=user.mention)
        rent_t = t(user.id, "rent")
        my_rentals_t = t(user.id, "my_rentals")
        profile_t = t(user.id, "profile")
        help_t = t(user.id, "help")
        rows = [
            [
                InlineKeyboardButton(rent_t, callback_data="rentnum"),
                InlineKeyboardButton(my_rentals_t, callback_data="my_rentals"),
            ],
            [
                InlineKeyboardButton(profile_t, callback_data="profile"),
                InlineKeyboardButton(help_t, callback_data="help"),
            ],
        ]

        if user.id in ADMINS:
            rows.insert(0, [InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")])

        keyboard = InlineKeyboardMarkup(rows)

        await _safe_edit(query.message, welcome_t, reply_markup=keyboard, client=client)

    elif data == "add_balance":
        await query.answer()
        chat = query.message.chat
        enter_amount_t = t(user_id, "enter_amount")
        back_t = t(user_id, "back")

        if not CRYPTO_STAT:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
            )
            return await query.message.edit_text(
                "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> CryptoBot payments are currently disabled. Please choose another method.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )

        if not await check_rate_limit(user_id, "payment_create", 5, 60):
            return await query.answer("⏳ Too many payment attempts. Try again in a minute.", show_alert=True)
        try:
            response = await chat.ask(enter_amount_t, timeout=60)
        except Exception:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(back_t, callback_data="profile")]]
            )
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=keyboard, parse_mode=ParseMode.HTML)

        try:
            amount = float(response.text.strip())
            if amount <= 0:
                return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Amount must be greater than 0.5 USDT.", parse_mode=ParseMode.HTML)
        except ValueError:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter a valid number.", parse_mode=ParseMode.HTML)

        user_id = query.from_user.id

        import httpx
        try:
            async with httpx.AsyncClient() as http:
                resp = await http.post(
                    "https://pay.crypt.bot/api/createInvoice",
                    headers={"Crypto-Pay-API-Token": CRYPTO_API},
                    json={
                        "currency_type": "fiat",
                        "fiat": "USD",
                        "amount": str(amount),
                        "description": f"Top-up for {user_id}",
                        "payload": f"{user_id}_{query.message.id}",
                        "allow_comments": False,
                        "allow_anonymous": False,
                        "expires_in": 1800
                    }
                )
                resp.raise_for_status()
                j = resp.json()
                if not j.get("ok") or "result" not in j:
                    raise ValueError(j.get("error", {}).get("message", "API error"))
                data = j["result"]
        except Exception as e:
            logging.error(f"Create invoice API error: {e}")
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(back_t, callback_data="profile")]])
            return await query.message.edit_text(
                "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Failed to create invoice. Please try again.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )

        invoice_id = data["invoice_id"]
        bot_invoice_url = data["bot_invoice_url"]
        await redis_client.set(f"inv_amount:{invoice_id}", str(amount), ex=1800)

        # Cancel any old pending invoice for this user (never remove if paid)
        if user_id in temp.INV_DICT:
            old_inv_id, old_msg_id = temp.INV_DICT[user_id]
            try:
                old_invoice = await cp.get_invoice(old_inv_id)
                if getattr(old_invoice, "status", None) == "paid":
                    logging.warning(f"Attempted to delete PAID invoice {old_inv_id} for user {user_id} — skipped")
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(back_t, callback_data="profile")]])
                    return await query.message.edit_text(
                        "<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> You have a payment that was just completed. Please wait for confirmation.",
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML,
                    )
                if getattr(old_invoice, "status", None) == "pending":
                    await cp.cancel_invoice(old_inv_id)
            except Exception as e:
                logging.debug(f"cancel_invoice or cleanup failed for user_id={user_id} old_inv_id={old_inv_id}: {e}")
            try:
                msg = await client.get_messages(chat.id, old_msg_id)
                await msg.edit("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> This invoice has been cancelled due to a new top-up request.", parse_mode=ParseMode.HTML)
            except Exception as e:
                logging.debug(f"edit old invoice message failed user_id={user_id}: {e}")
            temp.INV_DICT.pop(user_id, None)
            await delete_inv_entry(user_id)

        temp.INV_DICT[user_id] = (invoice_id, query.message.id)
        await save_inv_entry(user_id, invoice_id, query.message.id)
        temp.PENDING_INV.add(invoice_id)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay", url=bot_invoice_url)],
            [InlineKeyboardButton(t(user_id, "back"), callback_data="profile")],
        ])

        await query.message.edit_text(
            t(user_id, "payment_pending", amount=amount, inv=invoice_id),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        await response.delete()
        try:
            await response.sent_message.delete()
        except Exception as e:
            logging.debug(f"delete sent_message failed in add_balance: {e}")
        return

    elif data.startswith("pay_direct_"):
        user_id = query.from_user.id
        back_t = t(user_id, "back")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(back_t, callback_data="profile")]])
        await query.message.edit_text(
            "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Direct pay is currently unavailable.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("check_direct_"):
        user_id = query.from_user.id
        rest = data.replace("check_direct_", "")
        parts = rest.split("_", 1)
        if len(parts) < 2:
            uid_str, amount_key = parts[0], ""
        else:
            uid_str, amount_key = parts[0], parts[1]
        try:
            expected_uid = int(uid_str)
        except ValueError:
            await query.answer("❌ Invalid request.", show_alert=True)
            return
        if expected_uid != user_id:
            await query.answer("❌ This button is not for you.", show_alert=True)
            return
        await query.answer("We'll confirm when we receive your transfer. You can also wait for the next check.", show_alert=False)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(user_id, "back"), callback_data="profile")],
        ])
        try:
            await query.message.edit_text(
                "<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Checking... We'll notify you when your payment is confirmed.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.debug(f"edit_message_text failed for check_direct user_id={user_id}: {e}")

    elif data == "check_payment_" or data.startswith("check_payment_"):
        user_id = query.from_user.id
        if user_id in temp.PAID_LOCK:
            return await query.answer("⏳ Please wait, checking your previous request.", show_alert=True)
        temp.PAID_LOCK.add(user_id)
        try:
            inv_id = data.replace("check_payment_", "")
            invoice = await cp.get_invoice(inv_id)
            if not invoice or inv_id not in temp.PENDING_INV:
                await query.answer(t(user_id, "payment_not_found"), show_alert=True)
                return
            if invoice.status == "paid":
                if await is_payment_processed_crypto(str(inv_id)):
                    temp.PENDING_INV.discard(inv_id)
                    return await query.message.edit_text(t(user_id, "payment_confirmed"), parse_mode=ParseMode.HTML)
                payload = (invoice.payload or "").strip()
                keyboard = await resolve_payment_keyboard(user_id, payload)
                current_bal = await get_user_balance(user_id) or 0.0
                fiat_amount = await redis_client.get(f"inv_amount:{inv_id}")
                credit = float(fiat_amount) if fiat_amount else float(invoice.amount)
                new_bal = current_bal + credit
                await redis_client.delete(f"inv_amount:{inv_id}")
                await save_user_balance(user_id, new_bal)
                await mark_payment_processed_crypto(str(inv_id))
                await record_transaction(user_id, credit, "deposit", "Balance top-up via CryptoBot")
                await query.message.edit_text(
                    t(user_id, "payment_confirmed"),
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
                temp.PENDING_INV.discard(inv_id)
            else:
                await query.answer(t(user_id, "payment_not_found"), show_alert=True)
        except Exception as e:
            logging.error(f"Payment check error for {user_id}: {e}")
            await query.answer("❌ An error occurred. Please try again.", show_alert=True)
        finally:
            temp.PAID_LOCK.discard(user_id)

    elif data == "help":
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(t(user_id, "back"), callback_data="back_home")]]
        )
        await query.message.edit_text(t(user_id, "help_text"), reply_markup=keyboard, parse_mode=ParseMode.HTML)

    elif data == "admin_panel" and query.from_user.id in ADMINS:
        text = "<tg-emoji emoji-id=\"5472308992514464048\">🛠️</tg-emoji> Admin Panel\n\nSelect an option below:"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("👤 User Management", callback_data="user_management"),
            ],
            [
                InlineKeyboardButton("🛒 Rental Management", callback_data="rental_management"),
            ],
            [
                InlineKeyboardButton("🔢 Number Control", callback_data="number_control"),
            ],
            [
                InlineKeyboardButton("🛠️ Admin Tools", callback_data="admin_tools"),
            ],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_home")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    elif data == "user_management" and query.from_user.id in ADMINS:
        text = """<tg-emoji emoji-id=\"5422683699130933153\">👤</tg-emoji> User Management
        
Details:
- User Info: Get detailed information about a user by User ID.
- User Balances: View total user balances and add balance to a user.
        """
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("User Info", callback_data="admin_user_info"),
                InlineKeyboardButton("User Balances", callback_data="admin_balances"),
            ],
            [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_panel")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    elif data == "rental_management" and query.from_user.id in ADMINS:
        text = """<tg-emoji emoji-id=\"5767374504175078683\">🛒</tg-emoji> Rental Management

Details:
- Numbers: View all rented numbers and their details.
- Cancel Rent: Cancel a user's rental by User ID or Number.
- Transfer Number: Transfer a rented number to another user.
- Change Date: Set new expiry or extend/reduce rental duration.
- Export CSV: Export all rental data in CSV format.
        """
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Numbers", callback_data="admin_numbers")],
            [
                InlineKeyboardButton("Cancel Rent", callback_data="admin_cancel_rent"),
                InlineKeyboardButton("🔄 Transfer Number", callback_data="admin_transfer_number"),
            ],
            [
                InlineKeyboardButton("📅 Change Date", callback_data="admin_change_date"),
                InlineKeyboardButton("📑 Export CSV", callback_data="exportcsv"),
            ],
            [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_panel")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    elif data == "number_control" and query.from_user.id in ADMINS:
        text = """🔢 Number Control

Details:
- Enable/Disable Numbers: Toggle the availability of numbers for rent.
- Enable All: Make all numbers available for rent.
- Delete Accounts: Delete a Telegram account associated with a number.
        """
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Enable Numbers", callback_data="admin_enable_numbers"),
                InlineKeyboardButton("Disable Numbers", callback_data="admin_disable_numbers"),
            ],
            [
                InlineKeyboardButton("Enable All", callback_data="admin_enable_all"),
                InlineKeyboardButton("Delete Accounts", callback_data="admin_delete_acc"),
            ],
            [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_panel")]
        ])
        await _safe_edit(query.message, text, reply_markup=keyboard, client=client)

    elif data == "admin_tools" and query.from_user.id in ADMINS:
        text = """<tg-emoji emoji-id=\"5472308992514464048\">🛠️</tg-emoji> Admin Tools

- Change Rules: Update the rental rules text.
- Test number connected: Check if a +888 number is linked to a Telegram account (Fragment).
        """
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Change Rules", callback_data="admin_change_rules")],
            [InlineKeyboardButton("📞 Test number connected", callback_data="admin_test_number_connected")],
            [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_panel")]
        ])
        await _safe_edit(query.message, text, reply_markup=keyboard, client=client)

    elif data == "admin_test_number_connected" and query.from_user.id in ADMINS:
        await query.answer()
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the +888 number to check if it is connected to an account (within 60s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text(
                "<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.",
                reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD,
                parse_mode=ParseMode.HTML,
            )
        number = (response.text or "").strip().replace(" ", "")
        if not number.startswith("+"):
            number = "+" + number
        try:
            await response.delete()
        except Exception:
            pass
        try:
            await response.sent_message.delete()
        except Exception:
            pass
        if not number.startswith("+888"):
            return await query.message.edit_text(
                "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid number. Use a +888 number.",
                reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD,
                parse_mode=ParseMode.HTML,
            )
        from hybrid.plugins.guard import guard_check
        ok, status_msg = await guard_check(number)
        if ok is True:
            text = f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> {number} is <b>free</b> (not connected to an account)."
        elif ok is False:
            text = f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> {number} is <b>connected</b> to an account (busy on Fragment)."
        else:
            text = f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> {status_msg}"
        await query.message.edit_text(
            text,
            reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD,
            parse_mode=ParseMode.HTML,
        )

    elif data == "admin_numbers" and query.from_user.id in ADMINS:
        await show_numbers(query, page=1)

    elif data.startswith("admin_numbers_page_"):
        page = int(data.split("_")[-1])
        await show_numbers(query, page=page)

    elif data.startswith("admin_number_"):
        remainder = data[len("admin_number_"):]
        parts = remainder.rsplit("_", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            return await query.answer("❌ Invalid request.", show_alert=True)
        number = parts[0]
        page = int(parts[1])

        number_data = await get_number_info(number)
        if not number_data:
            # save default data if not found
            await save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=True)
            logging.info(f"Number {number} not found in DB. Created with default prices.")
        async with temp.get_lock():
            if number not in temp.AVAILABLE_NUM:
                temp.AVAILABLE_NUM.add(number)
        number_data = await get_number_info(number)
        price_30d = number_data.get("prices", {}).get("30d", 0.0)
        price_60d = number_data.get("prices", {}).get("60d", 0.0)
        price_90d = number_data.get("prices", {}).get("90d", 0.0)
        available = number_data.get("available", True)
        rented_user = await get_user_by_number(number)
        if rented_user:
            rented_status = f"<tg-emoji emoji-id=\"5323535839391653590\">🔴</tg-emoji> Rented by User ID: {rented_user[0]}"
        else:
            rented_status = "<tg-emoji emoji-id=\"5323307196807653127\">🟢</tg-emoji> Available"
        avail_str = "<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Yes" if available else "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> No"
        db_yes_no = "<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Yes" if number_data else "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> No"
        updated_at_val = number_data.get("updated_at", "N/A")
        updated_str = updated_at_val.strftime('%Y-%m-%d %H:%M:%S UTC') if hasattr(updated_at_val, 'strftime') else str(updated_at_val)
        text = f"""<tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji> Number: {number}
{rented_status}
• <tg-emoji emoji-id=\"5197434882321567830\">💵</tg-emoji> Prices:
    • 30 days: {price_30d} USDT
    • 60 days: {price_60d} USDT
    • 90 days: {price_90d} USDT
• 📦 Available: {avail_str}
• <tg-emoji emoji-id=\"5472308992514464048\">🛠️</tg-emoji> Last Updated: {updated_str}
• <tg-emoji emoji-id=\"5190458330719461749\">🆔</tg-emoji> In Database: {db_yes_no}
"""
        kb = [
            [InlineKeyboardButton("💵 Change Price", callback_data=f"change_price_{number}_{page}")],
            [InlineKeyboardButton("🟢 Toggle Availability", callback_data=f"toggle_avail_{number}_{page}")],
            [InlineKeyboardButton("⬅️ Back", callback_data=f"admin_numbers_page_{page}")]
        ]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("change_price_") and query.from_user.id in ADMINS:
        await query.answer()
        remainder = data[len("change_price_"):]
        parts = remainder.rsplit("_", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            return await query.answer("❌ Invalid request.", show_alert=True)
        number = parts[0]
        page = int(parts[1])

        try:
            response = await query.message.chat.ask(
                f"<tg-emoji emoji-id=\"5375296873982604963\">💰</tg-emoji> Enter new prices for {number} in USDT as 30d,60d,90d (within 120s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", parse_mode=ParseMode.HTML)

        try:
            prices = list(map(float, response.text.strip().split(",")))
            if len(prices) != 3 or any(p <= 0 for p in prices):
                return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Please provide three positive numbers separated by commas.", parse_mode=ParseMode.HTML)
            price_30d, price_60d, price_90d = prices
        except ValueError:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter valid numbers.", parse_mode=ParseMode.HTML)

        status = await save_number_info(number, price_30d, price_60d, price_90d)
        await response.delete()
        await response.sent_message.delete()

        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data=f"admin_number_{number}_{page}")]
        ]
        await query.message.edit_text(f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Prices for {number} updated successfully ({status}).",
                                      reply_markup=InlineKeyboardMarkup(keyboard),
                                      parse_mode=ParseMode.HTML)
        return
    
    elif data.startswith("toggle_avail_") and query.from_user.id in ADMINS:
        remainder = data[len("toggle_avail_"):]
        parts = remainder.rsplit("_", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            return await query.answer("❌ Invalid request.", show_alert=True)
        number = parts[0]
        page = int(parts[1])

        number_data = await get_number_info(number)
        if not number_data:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Number not found in database.", parse_mode=ParseMode.HTML)

        current_status = number_data.get("available", True)
        new_status = not current_status
        await save_number_info(
            number,
            number_data.get("prices", {}).get("30d", 0.0),
            number_data.get("prices", {}).get("60d", 0.0),
            number_data.get("prices", {}).get("90d", 0.0),
            available=new_status
        )

        status_label = "<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Yes" if new_status else "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> No"
        await query.message.edit_text(
            f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Availability for {number} set to {status_label}.",
            parse_mode=ParseMode.HTML,
        )
        # change in temp.AVAILABLE_NUM
        async with temp.get_lock():
            if new_status:
                temp.AVAILABLE_NUM.add(number)
            else:
                temp.AVAILABLE_NUM.discard(number)
        if not new_status:
            temp.UN_AV_NUMS.add(number)
        else:
            temp.UN_AV_NUMS.discard(number)
        query.data = f"admin_number_{number}_{page}"
        await _callback_handler_impl(client, query)
        return

    elif data == "admin_cancel_rent" and query.from_user.id in ADMINS:
        await query.answer()
        user = query.from_user
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number (starting with +888) to cancel rent (within 120s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        identifier = response.text.strip()
        identifier = identifier.replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        if identifier.startswith("+888"):
            number = identifier
            user_data = await get_user_by_number(number)
            if not user_data:
                return await query.message.edit_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
            user_id = user_data[0]
        elif identifier.startswith("888") and identifier.isdigit():
            number = f"+{identifier}"
            user_data = await get_user_by_number(number)
            if not user_data:
                return await query.message.edit_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
            user_id = user_data[0]
        else:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter a valid User ID or Number.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        user = await client.get_users(user_id)
        success, status = await remove_number(number, user_id)
        await remove_number_data(number)


        if success:
            await log_admin_action(query.from_user.id, "admin_cancel_rent", number, f"user_id={user_id}")
            try:
                is_free = await check_number_conn(number)
                if not is_free:
                    try:
                        from hybrid.plugins.fragment import terminate_all_sessions_async
                        await terminate_all_sessions_async(number)
                    except Exception as e:
                        logging.warning(f"Session termination failed for {number}: {e}")
                else:
                    logging.info(f"Number {number} is free — no active account, skipping termination.")
            except Exception as e:
                logging.warning(f"Could not check connection status for {number}: {e} — skipping termination.")
            async with temp.get_lock():
                temp.RENTED_NUMS.discard(number)
                temp.UN_AV_NUMS.discard(number)
                if number not in temp.AVAILABLE_NUM:
                    temp.AVAILABLE_NUM.add(number)

        if success:
            _bal = await get_user_balance(user.id) or 0.0
            TEXT = f"""<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Rental for number {number} has been cancelled.
• User ID: {user.id}
• Username: @{user.username if user.username else 'N/A'}
• Name: {user.first_name if user.first_name else 'N/A'}
• Balance: {_bal}
• Rented On: {user_data[2]}
• Time Left: {format_remaining_time(user_data[2], user_data[1])}
• Cancelled By: {query.from_user.mention} (ID: {query.from_user.id})

The number will appear as 🟢 available in the listing immediately.
            """
            keyboard = [
                [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
            ]
            await query.message.edit_text(TEXT, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
            try:
                await client.send_message(
                    user.id,
                    f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Your rental for number {number} has been cancelled by the admin.\n"
                    f"• Rented On: {user_data[2]}\n"
                    f"• Time Left: {format_remaining_time(user_data[2], user_data[1])}\n"
                    f"For more info, contact support.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logging.debug(f"send_message failed notifying user {user.id} after admin cancel rent number={number}: {e}")

    elif data == "admin_balances" and query.from_user.id in ADMINS:
        to_tal, to_user = await get_total_balance()
        text = f"<tg-emoji emoji-id=\"5375296873982604963\">💰</tg-emoji> Total User Balances:\n\n• Total Balance: {to_tal} USDT\n• Total Users with Balance: {to_user}"
        keyboard = [
            [InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    elif data == "admin_add_balance" and query.from_user.id in ADMINS:
        await query.answer()
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the User ID to add balance to (within 120s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        identifier = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        try:
            user_id = int(identifier)
        except ValueError:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter a valid User ID.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        try:
            user = await client.get_users(user_id)
        except Exception as e:
            logging.debug(f"get_users failed for user_id={user_id}: {e}")
            user = None
        if not user:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> User not found/invalid User ID. (User must start this bot first)", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        try:
            response = await query.message.chat.ask(
                f"⚠️ Enter the amount in USDT to add to user {user.first_name} (ID: {user.id}) (within 120s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        try:
            amount = float(response.text.strip())
            if amount <= 0:
                return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Amount must be greater than 0.5 USDT.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        except ValueError:
            return await query.message.reply("❌ Invalid input. Please enter a valid number.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        current_bal = await get_user_balance(user.id) or 0.0
        new_bal = current_bal + amount
        await save_user_balance(user.id, new_bal)
        await log_admin_action(query.from_user.id, "admin_add_balance", str(user.id), f"amount={amount} new_bal={new_bal}")
        await response.delete()
        await response.sent_message.delete()
        keyboard = [
            [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
        ]
        await query.message.edit_text(
            f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Added {amount} USDT to user {user.first_name} (ID: {user.id}). New Balance: {new_bal} USDT",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
        try:
            await client.send_message(
                user.id,
                f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> An admin has added {amount} USDT to your balance.\n"
                f"• New Balance: {new_bal} USDT\n"
                f"For more info, contact support.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.debug(f"send_message failed notifying user {user.id} after admin add balance: {e}")

    elif data == "admin_user_info" and query.from_user.id in ADMINS:
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the User ID to get info for (within 120s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        identifier = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        try:
            user_id = int(identifier)
        except ValueError:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter a valid User ID.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        user = await client.get_users(user_id)
        if not user:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> User not found/invalid User ID. (User must start this bot first)", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        balance = await get_user_balance(user.id) or 0.0
        numbers = await get_user_numbers(user.id)
        text = (
            f"<tg-emoji emoji-id=\"5422683699130933153\">👤</tg-emoji> User Info\n\n"
            f"<tg-emoji emoji-id=\"5190458330719461749\">🆔</tg-emoji> User ID: {user.id}\n"
            f"<tg-emoji emoji-id=\"5422683699130933153\">👤</tg-emoji> First Name: {user.first_name or 'N/A'}\n"
            f"<tg-emoji emoji-id=\"5318757666800031348\">🔗</tg-emoji> Username: @{user.username if user.username else 'N/A'}\n"
            f"<tg-emoji emoji-id=\"5375296873982604963\">💰</tg-emoji> Balance: {balance} USDT\n"
            f"<tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji> Active Rentals: {len(numbers)}\n"
        )
        if numbers:
            text += "• " + "\n• ".join(numbers) + "\n"
        keyboard = [
            [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    elif data == "admin_delete_acc" and query.from_user.id in ADMINS:
        await query.answer()
        # TEST - ask for number to delete account using chat.ask do not check anything with db just ask for number and call delete_account from func.py also ask for code and 2fa if needed
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number to delete account (within 120s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        identifier = response.text.strip()
        identifier = identifier.replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        chat = query.message.chat
        stat, reason = await delete_account(identifier, app=client)
        if stat:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]])
            try:
                from hybrid.plugins.guard import guard_is_free
                is_free = await guard_is_free(identifier)
                if is_free:
                    msg = f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Account associated with number {identifier} has been deleted."
                else:
                    msg = f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Account is not deleted. 7-day step two verification activated for {identifier}."
            except Exception:
                msg = f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Account associated with number {identifier} has been deleted/deletion counter for one week started successfully."
            await query.message.edit_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            keyboard = [
                [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
            ]
            # OTP = couldn't fetch login code from Fragment — usually means frag.json cookies expired
            hint = " Update Fragment cookies (frag.json) and try again." if reason == "OTP" else ""
            await query.message.edit_text(
                f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Failed to delete account for number <b>{identifier}</b>. Reason: {reason}.{hint}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML,
            )
            if reason == "Banned":
                logging.info(f"Number {identifier} is banned (banned feature disabled).")
        return
        
    elif data == "admin_change_rules" and query.from_user.id in ADMINS:
        await query.answer()
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the new rules text (within 300s):",
                timeout=300
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        new_rules = response.text.strip()
        try:
            await response.delete()
        except Exception as e:
            logging.debug(f"response.delete failed in admin_change_rules: {e}")
        try:
            await response.sent_message.delete()
        except Exception as e:
            logging.debug(f"response.sent_message.delete failed in admin_change_rules: {e}")
        await save_rules(new_rules, lang="en")
        await query.message.edit_text("<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Rules updated.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)

    elif data.startswith("delacc_") and query.from_user.id in ADMINS:
        parts = data.replace("delacc_", "").rsplit("_", 1)
        number = parts[0]
        user_id = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else None

        # ========== Delete Account logic ========== #
        try:
            from hybrid.plugins.guard import guard_is_free
            is_connected = not await guard_is_free(number)
        except Exception as e:
            logging.debug(f"guard_is_free failed for number={number}: {e}")
            is_connected = True  # assume connected if check fails, proceed normally
        if not is_connected:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]])
            return await query.message.edit_text(
                f"ℹ️ Number {number} is already disconnected — no account to delete.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        stat, reason = await delete_account(number, app=client)
        if stat:
            await log_admin_action(query.from_user.id, "admin_delete_acc", number, f"reason={reason}")
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]])
            try:
                from hybrid.plugins.guard import guard_is_free
                is_free = await guard_is_free(number)
                if is_free:
                    msg = f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Account associated with number {number} has been deleted."
                else:
                    msg = f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Account is not deleted. 7-day step two verification activated for {number}."
            except Exception:
                msg = f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Account associated with number {number} has been deleted/deletion counter for one week started successfully."
            await query.message.edit_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            return
        else:
            if reason == "Banned":
                logging.info(f"Number {number} is banned (banned feature disabled).")
                            
            hint = " Update Fragment cookies (frag.json) and try again." if reason == "OTP" else ""
            return await query.message.edit_text(
                f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Failed to delete account. Reason: {reason}.{hint}",
                reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD,
                parse_mode=ParseMode.HTML,
            ) 
        # ========== End Delete Account logic ========== #

    elif data == "rentnum":
        await query.message.edit_text(
            t(user_id, "choose_number"),
            reply_markup=await build_rentnum_keyboard(user_id, page=0),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("rentnum_page:"):
        user_id = query.from_user.id
        page = int(data.split(":")[1])
        await query.message.edit_text(
            t(user_id, "choose_number"),
            reply_markup=await build_rentnum_keyboard(user_id, page=page),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("rentpay:"):
        parts = data.split(":")
        user_id = query.from_user.id
        if len(parts) >= 2:
            number = normalize_phone(parts[1]) or parts[1]
            query.data = f"numinfo:{number}:0"
        else:
            query.data = "back_home"
        if query.data.startswith("numinfo:"):
            number = normalize_phone(query.data.split(":")[1]) or query.data.split(":")[1]
            num_text = format_number(number)
            page = 0
            rented_data = await get_rented_data_for_number(number)
            if rented_data and rented_data.get("user_id") == user_id:
                rent_date = rented_data.get("rent_date")
                hours = rented_data.get("hours", 0)
                time_left = format_remaining_time(rent_date, hours)
                date_str = format_date(str(rent_date)) if rent_date else "N/A"
                keyboard = await build_number_actions_keyboard(user_id, number, "my_rentals")
                await query.message.edit_text(
                    t(user_id, "number", num=num_text, time=time_left, date=date_str),
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
                return
            info = await get_number_info(number)
            if not info:
                await query.answer(t(user_id, "no_info"), show_alert=True)
                return
            if rented_data and rented_data.get("user_id"):
                rent_date = rented_data.get("rent_date")
                remaining_days = format_remaining_time(rent_date, rented_data.get("hours", 0))
                date_str = format_date(str(rent_date))
                txt = (
                    f"<tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji>: {num_text}\n"
                    f"<tg-emoji emoji-id=\"5323535839391653590\">🔴</tg-emoji>: {t(user_id, 'unavailable')}\n\n"
                    f"<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> {t(user_id, 'days')}: {remaining_days}\n"
                    f"<tg-emoji emoji-id=\"5274055917766202507\">📅</tg-emoji> {t(user_id, 'date')}: {date_str}"
                )
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data=f"rentnum_page:{page}")]]
                )
                await query.message.edit_text(txt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            elif info and info.get("available", True):
                prices = info.get("prices", {})
                txt = (
                    f"<tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji>: {num_text}\n"
                    f"<tg-emoji emoji-id=\"5323307196807653127\">🟢</tg-emoji>: {t(user_id, 'available')}\n"
                    f"<tg-emoji emoji-id=\"5375296873982604963\">💰</tg-emoji>: {t(user_id, 'rent_now')}"
                )
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"30 {t(user_id, 'days')} - {prices.get('30d', D30_RATE)} USDT", callback_data=f"rentfor:{number}:720")],
                    [InlineKeyboardButton(f"60 {t(user_id, 'days')} - {prices.get('60d', D60_RATE)} USDT", callback_data=f"rentfor:{number}:1440")],
                    [InlineKeyboardButton(f"90 {t(user_id, 'days')} - {prices.get('90d', D90_RATE)} USDT", callback_data=f"rentfor:{number}:2160")],
                    [InlineKeyboardButton(t(user_id, "back"), callback_data=f"rentnum_page:{page}")],
                ])
                await query.message.edit_text(txt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            else:
                txt = f"<tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji>: {num_text}\n<tg-emoji emoji-id=\"5323535839391653590\">🔴</tg-emoji>: {t(user_id, 'unavailable')}"
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data=f"rentnum_page:{page}")]]
                )
                await query.message.edit_text(txt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            user = query.from_user
            rows = [
                [InlineKeyboardButton(t(user.id, "rent"), callback_data="rentnum"), InlineKeyboardButton(t(user.id, "my_rentals"), callback_data="my_rentals")],
                [InlineKeyboardButton(t(user.id, "profile"), callback_data="profile"), InlineKeyboardButton(t(user.id, "help"), callback_data="help")],
            ]
            if user.id in ADMINS:
                rows.insert(0, [InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")])
            await query.message.edit_text(t(user.id, "welcome", name=user.first_name or ""), reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)

    elif data.startswith("numinfo:"):
        number = normalize_phone(data.split(":")[1]) or data.split(":")[1]
        num_text = format_number(number)
        page = int(data.split(":")[2])
        user_id = query.from_user.id

        info, rented_data = await asyncio.gather(
            get_number_info(number),
            get_rented_data_for_number(number),
        )

        if rented_data and rented_data.get("user_id"):  # Already rented
            unav_t = t(user_id, 'unavailable')
            days_t = t(user_id, 'days')
            date_t = t(user_id, 'date')
            back_t = t(user_id, "back")
            rent_date = rented_data.get("rent_date")
            date_str = format_date(str(rent_date))
            remaining_days = format_remaining_time(rent_date, rented_data.get("hours", 0))
            txt = (
                f"<tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji>: {num_text}\n"
                f"<tg-emoji emoji-id=\"5323535839391653590\">🔴</tg-emoji>: {unav_t}\n\n"
                f"<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> {days_t}: {remaining_days}\n"
                f"<tg-emoji emoji-id=\"5274055917766202507\">📅</tg-emoji> {date_t}: {date_str}"
            )
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(back_t, callback_data=f"rentnum_page:{page}")]]
            )
            await query.message.edit_text(txt, reply_markup=keyboard, parse_mode=ParseMode.HTML)

        else:  # Available
            if not info:  # if no record exists at all
                await query.answer(t(user_id, "no_info"), show_alert=True)
                return

            if not info.get("available", True):
                unav_t = t(user_id, 'unavailable')
                back_t = t(user_id, "back")
                txt = f"<tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji>: {num_text}\n<tg-emoji emoji-id=\"5323535839391653590\">🔴</tg-emoji>: {unav_t}"
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(back_t, callback_data=f"rentnum_page:{page}")]]
                )
                await query.message.edit_text(txt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                return

            # number available, show rent buttons
            available_t = t(user_id, 'available')
            rent_now_t = t(user_id, 'rent_now')
            days_t = t(user_id, 'days')
            back_t = t(user_id, "back")
            prices = info.get("prices", {})
            txt = (
                f"<tg-emoji emoji-id=\"5467539229468793355\">📞</tg-emoji>: {num_text}\n"
                f"<tg-emoji emoji-id=\"5323307196807653127\">🟢</tg-emoji>: {available_t}\n"
                f"<tg-emoji emoji-id=\"5375296873982604963\">💰</tg-emoji>: {rent_now_t}"
            )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"30 {days_t} - {prices.get('30d', D30_RATE)} USDT",
                                      callback_data=f"rentfor:{number}:720")],
                [InlineKeyboardButton(f"60 {days_t} - {prices.get('60d', D60_RATE)} USDT",
                                      callback_data=f"rentfor:{number}:1440")],
                [InlineKeyboardButton(f"90 {days_t} - {prices.get('90d', D90_RATE)} USDT",
                                      callback_data=f"rentfor:{number}:2160")],
                [InlineKeyboardButton(back_t, callback_data="rentnum_page:" + str(page))],
            ])
            await query.message.edit_text(txt, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    elif data.startswith("admin_enable_numbers") and query.from_user.id in ADMINS:
        await query.answer()
        user = query.from_user
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number (starting with +888 or 888) to enable numbers (comma separated for multiple) (within 120s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        await response.delete()
        await response.sent_message.delete()

        numbers = []
        if "," in response.text:
            for num in response.text.split(","):
                n = num.strip()
                if n.startswith("+888"):
                    numbers.append(n)
                elif n.startswith("888"):
                    numbers.append("+" + n)
                else:
                    if n.isdigit():
                        numbers = ["+888" + n]
                    else:
                        await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter valid numbers.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
                        return
        else:
            n = response.text.strip()
            if n.startswith("+888"):
                numbers = [n]
            elif n.startswith("888"):
                numbers = ["+" + n]
            else:
                if n.isdigit():
                    numbers = ["+888" + n]
                else:
                    await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter valid numbers.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
                    return
        if not numbers:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> No valid numbers provided.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        enabled = []
        for number in numbers:
            number_data = await get_number_info(number)
            if not number_data:
                await save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=True)
                enabled.append(number)
            else:
                if not number_data.get("available", True):
                    await save_number_info(
                        number,
                        number_data.get("prices", {}).get("30d", D30_RATE),
                        number_data.get("prices", {}).get("60d", D60_RATE),
                        number_data.get("prices", {}).get("90d", D90_RATE),
                        available=True
                    )
                    enabled.append(number)
        if not enabled:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> No valid numbers provided.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        
        for num in enabled:
            async with temp.get_lock():
                if num not in temp.AVAILABLE_NUM:
                    temp.AVAILABLE_NUM.add(num)
        await query.message.reply(f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Enabled the following numbers:\n" + "\n".join(enabled), reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)

    elif data.startswith("admin_disable_numbers") and query.from_user.id in ADMINS:
        await query.answer()
        user = query.from_user
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number (starting with +888 or 888) to Disable numbers (comma separated for multiple) (within 120s):",
                timeout=60
            )
        except Exception:
            return await query.message.edit_text("<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        await response.delete()
        await response.sent_message.delete()

        numbers = []
        if "," in response.text:
            for num in response.text.split(","):
                n = num.strip()
                if n.startswith("+888"):
                    numbers.append(n)
                elif n.startswith("888"):
                    numbers.append("+" + n)
                else:
                    if n.isdigit():
                        numbers = ["+888" + n]
                    else:
                        await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter valid numbers.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
                        return
        else:
            n = response.text.strip()
            if n.startswith("+888"):
                numbers = [n]
            elif n.startswith("888"):
                numbers = ["+" + n]
            else:
                if n.isdigit():
                    numbers = ["+888" + n]
                else:
                    await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid input. Please enter valid numbers.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
                    return
        if not numbers:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> No valid numbers provided.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        disabled = []
        for number in numbers:
            number_data = await get_number_info(number)
            if not number_data:
                await save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=False)
                disabled.append(number)
            else:
                if number_data.get("available", True):
                    await save_number_info(
                        number,
                        number_data.get("prices", {}).get("30d", D30_RATE),
                        number_data.get("prices", {}).get("60d", D60_RATE),
                        number_data.get("prices", {}).get("90d", D90_RATE),
                        available=False
                    )
                    disabled.append(number)
        if not disabled:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> No valid numbers provided.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        
        for num in disabled:
            async with temp.get_lock():
                if num in temp.AVAILABLE_NUM:
                    temp.AVAILABLE_NUM.remove(num)
        await query.message.reply(f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Disabled the following numbers:\n" + "\n".join(disabled), reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)

    elif data == "admin_enable_all" and query.from_user.id in ADMINS:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, Enable All", callback_data="admin_enable_all_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="number_control"),
            ]
        ])
        await query.message.edit_text(
            "⚠️ Are you sure you want to enable ALL numbers?\n"
            "This will make every number available for rent.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )

    elif data == "admin_enable_all_confirm" and query.from_user.id in ADMINS:
        user = query.from_user
        all_numbers = temp.NUMBE_RS
        if not all_numbers:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> No numbers found in the database.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        enabled = []
        for number in all_numbers:
            number_data = await get_number_info(number)
            if not number_data:
                await save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=True)
                enabled.append(number)
            else:
                if not number_data.get("available", True):
                    await save_number_info(
                        number,
                        number_data.get("prices", {}).get("30d", D30_RATE),
                        number_data.get("prices", {}).get("60d", D60_RATE),
                        number_data.get("prices", {}).get("90d", D90_RATE),
                        available=True
                    )
                    enabled.append(number)
        if not enabled:
            return await query.message.reply("<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> All numbers are already enabled.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        
        for num in enabled:
            async with temp.get_lock():
                if num not in temp.AVAILABLE_NUM:
                    temp.AVAILABLE_NUM.add(num)
        await query.message.reply(f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Enabled all numbers ({len(enabled)} total).", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)

    elif data == "setprices_cancel" and query.from_user.id in ADMINS:
        await query.answer()
        await query.message.edit_text("❌ Price update cancelled.")

    elif data.startswith("setprices_confirm|") and query.from_user.id in ADMINS:
        await query.answer()
        parts = data.split("|")
        price_30 = float(parts[1])
        price_60 = float(parts[2])
        price_90 = float(parts[3])
        await query.message.edit_text("⏳ Updating prices for all numbers...")
        updated = 0
        for number in temp.NUMBE_RS:
            info = await get_number_info(number)
            if info:
                await save_number_info(
                    number, price_30, price_60, price_90,
                    available=info.get("available", True)
                )
                updated += 1
        await query.message.edit_text(
            f"✅ Updated prices for {updated} numbers.\n"
            f"• 30 days: {price_30} USDT\n"
            f"• 60 days: {price_60} USDT\n"
            f"• 90 days: {price_90} USDT"
        )

    elif data == "admin_transfer_number" and query.from_user.id in ADMINS:
        await query.answer()
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the number to transfer (starting with +888, within 120s):",
                timeout=120
            )
        except Exception:
            return await query.message.edit_text("⏰ Timeout.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        number = response.text.strip().replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        if number.startswith("888") and not number.startswith("+888"):
            number = "+" + number
        if not number.startswith("+888"):
            return await query.message.reply("❌ Invalid number format.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        rented_data = await get_rented_data_for_number(number)
        if not rented_data or not rented_data.get("user_id"):
            return await query.message.reply("❌ This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        current_owner_id = rented_data.get("user_id")
        try:
            current_owner = await client.get_users(current_owner_id)
            owner_name = f"@{current_owner.username}" if current_owner.username else current_owner.first_name
        except Exception:
            owner_name = str(current_owner_id)
        try:
            response2 = await query.message.chat.ask(
                f"📞 Number: {format_number(number)}\n"
                f"👤 Current owner: {owner_name}\n\n"
                f"Enter @username or User ID to transfer to (within 120s):",
                timeout=120
            )
        except Exception:
            return await query.message.edit_text("⏰ Timeout.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        identifier = response2.text.strip()
        await response2.delete()
        await response2.sent_message.delete()
        to_user = None
        try:
            if identifier.startswith("@"):
                to_user = await client.get_users(identifier)
            else:
                to_user = await client.get_users(int(identifier))
        except Exception:
            return await query.message.reply("❌ User not found. They must have started this bot first.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        if to_user.is_bot:
            return await query.message.reply("❌ Cannot transfer to a bot.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        recipient_name = f"@{to_user.username}" if to_user.username else to_user.first_name
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"admin_transfer_confirm|{number}|{to_user.id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="rental_management"),
            ]
        ])
        await query.message.edit_text(
            f"⚠️ Confirm Transfer\n\n"
            f"📞 Number: {format_number(number)}\n"
            f"👤 From: {owner_name}\n"
            f"➡️ To: {recipient_name} (ID: {to_user.id})",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("admin_transfer_confirm|") and query.from_user.id in ADMINS:
        parts = data.split("|")
        number = parts[1]
        to_user_id = int(parts[2])
        rented_data = await get_rented_data_for_number(number)
        if not rented_data or not rented_data.get("user_id"):
            return await query.message.reply("❌ Rental not found.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        from_user_id = rented_data.get("user_id")
        success, err = await transfer_number(number, from_user_id, to_user_id)
        if success:
            await log_admin_action(query.from_user.id, "admin_transfer_number", number, f"from={from_user_id} to={to_user_id}")
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]])
            await query.message.edit_text(
                f"✅ Number {format_number(number)} transferred successfully.\n"
                f"From: {from_user_id} → To: {to_user_id}",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            try:
                to_user = await client.get_users(to_user_id)
                await client.send_message(to_user_id, f"✅ Number {format_number(number)} has been transferred to you by an admin.")
            except Exception as e:
                logging.debug(f"send_message failed notifying to_user_id={to_user_id} after admin transfer number={number}: {e}")
        else:
            await query.message.reply(f"❌ Transfer failed: {err}", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)

    elif data.startswith("rentfor:"):
        parts = data.split(":")
        number = normalize_phone(parts[1]) or parts[1] if len(parts) >= 2 else ""
        hours = int(parts[2]) if len(parts) >= 3 else 0
        num_text = format_number(number)
        user = query.from_user
        user_id = user.id

        info, (balance, method) = await asyncio.gather(
            get_number_info(number),
            get_user_profile_data(user_id),
        )
        balance = balance or 0.0
        if not info or not info.get("available", True):
            return await query.answer(t(user_id, "unavailable"), show_alert=True)

        prices = info.get("prices", {})
        price_map = {720: prices.get("30d", D30_RATE), 1440: prices.get("60d", D60_RATE), 2160: prices.get("90d", D90_RATE)}
        price = price_map.get(hours, None)
        if price is None:
            return await query.answer(t(user_id, "error_occurred"), show_alert=True)
        if balance < price:
            # await query.message.edit_text(
            #     t(user_id, "insufficient_balance").format(balance=balance, price=price),
            #     reply_markup=InlineKeyboardMarkup(
            #         [
            #             [InlineKeyboardButton(t(user_id, "add_balance"), callback_data="add_balance")],
            #             [InlineKeyboardButton(t(user_id, "back"), callback_data=f"numinfo:{number}:0")]
            #         ]
            #     )
            # )
            amount = price - balance
            if not CRYPTO_STAT:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(user_id, "back"), callback_data=f"numinfo:{number}:0")]
                ])
                return await query.message.edit_text(
                    "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> CryptoBot payments are currently disabled.",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            if not await check_rate_limit(user_id, "payment_create", 5, 60):
                return await query.answer("⏳ Too many payment attempts. Try again in a minute.", show_alert=True)
            from hybrid import cp
            inv = await send_cp_invoice(cp, client, user_id, amount, f"Payment for {num_text}", query.message, f"rentpay:{number}:{hours}")
            if inv:
                temp.INV_DICT[user_id] = (inv.invoice_id, query.message.id)
                await save_inv_entry(user_id, inv.invoice_id, query.message.id)
                temp.PENDING_INV.add(inv.invoice_id)
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Pay", url=inv.bot_invoice_url)],
                    [InlineKeyboardButton(t(user_id, "back"), callback_data=f"numinfo:{number}:0")],
                ])
                await query.message.edit_text(
                    f"<tg-emoji emoji-id=\"5206583755367538087\">💸</tg-emoji> Invoice Created\n\nAmount: {amount} USDT\nDescription: Payment for {num_text}\nPay using the button below.",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            return

        if hours == 720:
            days = 30
        elif hours == 1440:
            days = 60
        elif hours == 2160:
            days = 90
        else:
            days = hours // 24

        confirm_t = t(user_id, "confirm")
        cancel_t = t(user_id, "cancel")
        confirm_rent_t = t(user_id, "confirm_rent")
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(confirm_t, callback_data=f"rule:{number}:{hours}"),
                    InlineKeyboardButton(cancel_t, callback_data=f"numinfo:{number}:0")
                ]
            ]
        )
        await query.message.edit_text(
            confirm_rent_t.format(number=num_text, days=days, price=price),
            reply_markup=keyboard
        )

    elif data.startswith("rule:"):
        _, number, hours = data.split(":")
        hours = int(hours)
        user_id = query.from_user.id
        rules = await get_rules(lang="en")
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(t(user_id, "accept"), callback_data=f"confirmrent:{number}:{hours}"),
                    InlineKeyboardButton(t(user_id, "decline"), callback_data=f"numinfo:{number}:0")
                ]
            ]
        )
        await query.message.edit_text(
            t(user_id, "rules").format(rules=rules),
            reply_markup=keyboard
        )

    elif data.startswith("confirmrent:"):
        _, number, hours = data.split(":")
        num_text = format_number(number)
        hours = int(hours)
        user = query.from_user
        user_id = user.id
        info, (balance, method), rented_data = await asyncio.gather(
            get_number_info(number),
            get_user_profile_data(user_id),
            get_rented_data_for_number(number),
        )
        balance = balance or 0.0
        if not info or not info.get("available", True):
            return await query.answer(t(user_id, "unavailable"), show_alert=True)

        prices = info.get("prices", {})
        price_map = {720: prices.get("30d", D30_RATE), 1440: prices.get("60d", D60_RATE), 2160: prices.get("90d", D90_RATE)}
        price = price_map.get(hours, None)
        if price is None:
            return await query.answer(t(user_id, "error_occurred"), show_alert=True)

        if balance < price:
            amount = price - balance
            if not CRYPTO_STAT:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(user_id, "back"), callback_data=f"numinfo:{number}:0")]
                ])
                return await query.message.edit_text(
                    "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> CryptoBot payments are currently disabled.",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            if not await check_rate_limit(user_id, "payment_create", 5, 60):
                return await query.answer("⏳ Too many payment attempts. Try again in a minute.", show_alert=True)
            from hybrid import cp
            inv = await send_cp_invoice(cp, client, user_id, amount, f"Payment for {num_text}", query.message, f"rentpay:{number}:{hours}")
            if inv:
                temp.INV_DICT[user_id] = (inv.invoice_id, query.message.id)
                await save_inv_entry(user_id, inv.invoice_id, query.message.id)
                temp.PENDING_INV.add(inv.invoice_id)
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Pay", url=inv.bot_invoice_url)],
                    [InlineKeyboardButton(t(user_id, "back"), callback_data=f"rentpay:{number}:{hours}")],
                ])
                await query.message.edit_text(
                    f"<tg-emoji emoji-id=\"5206583755367538087\">💸</tg-emoji> Invoice Created\n\nAmount: {amount} USDT\nDescription: Payment for {num_text}\nPay using the button below.",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            return

        # for renewal check if user already rented this number ,if yes must extend hours by remaining hours + new hours
        if rented_data and rented_data.get("user_id") and rented_data.get("user_id") != user.id:
            return await query.answer(t(user_id, "unavailable"), show_alert=True)

        rent_date = rented_data.get("rent_date", get_current_datetime()) if rented_data else get_current_datetime()
        remaining_hours = get_remaining_hours(rent_date, rented_data.get("hours", 0)) if rented_data else 0
        new_hours = remaining_hours + hours
        new_balance = balance - price

        lock_acquired = await lock_number_for_rent(number, user.id, ttl=1800)
        if not lock_acquired:
            return await query.answer(t(user_id, "unavailable"), show_alert=True)
        try:
            if remaining_hours > 0:
                await save_number(number, user.id, new_hours, extend=True)
                original_rent_date = rented_data.get("rent_date", get_current_datetime())
                await save_rental_atomic(user.id, number, new_balance, original_rent_date, new_hours)
            else:
                await save_number(number, user.id, new_hours)
                await save_rental_atomic(user.id, number, new_balance, get_current_datetime(), new_hours)

            await record_revenue(user.id, number, price, new_hours)
            await record_transaction(user.id, -price, "rent", f"Rented {num_text} for {hours // 24} days")
            async with temp.get_lock():
                temp.RENTED_NUMS.add(number)
                temp.AVAILABLE_NUM.discard(number)
            duration = format_remaining_time(get_current_datetime(), new_hours)
            keyboard = await build_number_actions_keyboard(user_id, number, "my_rentals")
            await query.message.edit_text(
                t(user_id, "rental_success", number=num_text, duration=duration, price=price, balance=new_balance),
                reply_markup=keyboard
            )
        finally:
            await unlock_number_for_rent(number)

    elif data.startswith("renew_"):
        raw = data.replace("renew_", "")
        number = normalize_phone(raw) or raw
        num_text = format_number(number)
        user = query.from_user
        user_id = user.id
        rented_data, info = await asyncio.gather(
            get_rented_data_for_number(number),
            get_number_info(number),
        )
        owner_id = int(rented_data.get("user_id") or 0) if rented_data else 0
        if not rented_data or owner_id != int(user.id):
            msg = "Number not found." if not rented_data else "You do not own this number."
            return await query.answer(msg, show_alert=True)
        if not info or not info.get("available", True):
            return await query.answer(t(user_id, "unavailable"), show_alert=True)
        prices = info.get("prices", {})
        days_lbl = t(user_id, 'days')
        back_lbl = t(user_id, "back")
        choose_renew_t = t(user_id, "choose_renew")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"30 {days_lbl} - {prices.get('30d', D30_RATE)} USDT",
                                  callback_data=f"confirmrent:{number}:720")],
            [InlineKeyboardButton(f"60 {days_lbl} - {prices.get('60d', D60_RATE)} USDT",
                                  callback_data=f"confirmrent:{number}:1440")],
            [InlineKeyboardButton(f"90 {days_lbl} - {prices.get('90d', D90_RATE)} USDT",
                                  callback_data=f"confirmrent:{number}:2160")],
            [InlineKeyboardButton(back_lbl, callback_data="my_rentals")],
        ])
        await query.message.edit_text(
            choose_renew_t.format(number=num_text),
            reply_markup=keyboard
        )

    elif data == "exportcsv" and query.from_user.id in ADMINS:
        try:
            message = query.message
            msg = await message.reply("⏳ Exporting numbers data to CSV...")
            filename = await export_numbers_csv(f"numbers_export_{gen_4letters()}.csv")
            await message.reply_document(filename, caption="📑 Exported Numbers Data")
            os.remove(filename)
            await msg.delete()
        except Exception as e:
            await message.reply_text(f"❌ Failed to export: {e}")

    elif data == "admin_change_date" and query.from_user.id in ADMINS:
        await query.answer()
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the number (starting with +888, within 120s):",
                timeout=120
            )
        except Exception:
            return await query.message.edit_text("⏰ Timeout.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        number = response.text.strip().replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        if number.startswith("888") and not number.startswith("+888"):
            number = "+" + number
        if not number.startswith("+888"):
            return await query.message.reply("❌ Invalid number format.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        rented_data = await get_rented_data_for_number(number)
        if not rented_data or not rented_data.get("user_id"):
            return await query.message.reply("❌ This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        current_rent_date = rented_data.get("rent_date")
        current_hours = rented_data.get("hours", 0)
        if hasattr(current_rent_date, "replace") and getattr(current_rent_date, "tzinfo", None) is None:
            current_rent_date = current_rent_date.replace(tzinfo=timezone.utc)
        expiry = current_rent_date + timedelta(hours=current_hours)
        try:
            response2 = await query.message.chat.ask(
                f"📞 Number: {format_number(number)}\n"
                f"📅 Rented on: {current_rent_date.strftime('%d/%m/%Y')}\n"
                f"⏰ Expires on: {expiry.strftime('%d/%m/%Y')}\n\n"
                f"Enter new EXPIRY date in DD/MM/YYYY format\n"
                f"OR enter +1d, +7d, +30d to extend\n"
                f"OR enter -1d, -7d to reduce\n"
                f"(within 120s):",
                timeout=120
            )
        except Exception:
            return await query.message.edit_text("⏰ Timeout.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)
        raw_input = response2.text.strip()
        await response2.delete()
        await response2.sent_message.delete()

        new_expiry = None
        try:
            if raw_input.startswith("+") or raw_input.startswith("-"):
                sign = 1 if raw_input.startswith("+") else -1
                val = raw_input[1:].strip().lower()
                if val.endswith("d") and val[:-1].isdigit():
                    delta_hours = sign * int(val[:-1]) * 24
                elif val.endswith("h") and val[:-1].isdigit():
                    delta_hours = sign * int(val[:-1])
                else:
                    raise ValueError("Invalid format")
                new_expiry = expiry + timedelta(hours=delta_hours)
            else:
                new_expiry = datetime.strptime(raw_input, "%d/%m/%Y").replace(
                    hour=expiry.hour, minute=expiry.minute, second=expiry.second,
                    tzinfo=timezone.utc
                )
        except Exception:
            return await query.message.reply(
                "❌ Invalid input. Use DD/MM/YYYY or +7d/-1d format.",
                reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD,
                parse_mode=ParseMode.HTML
            )

        new_hours = int((new_expiry - current_rent_date).total_seconds() / 3600)
        if new_hours <= 0:
            return await query.message.reply("❌ New expiry must be in the future relative to rent start.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD, parse_mode=ParseMode.HTML)

        user_id_owner = rented_data.get("user_id")
        user = await client.get_users(user_id_owner)
        await save_number(number, user.id, new_hours, date=current_rent_date, extend=True)
        await save_number_data(number, user_id_owner, current_rent_date, new_hours)
        await log_admin_action(query.from_user.id, "admin_change_date", number, f"new_expiry={new_expiry.strftime('%d/%m/%Y')} hours={new_hours}")

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="rental_management")]])
        await query.message.reply(
            f"✅ Expiry updated for {format_number(number)}\n"
            f"📅 New expiry: {new_expiry.strftime('%d/%m/%Y')}\n"
            f"⏰ Total hours: {new_hours}",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )


