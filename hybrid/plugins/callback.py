#(©) @Hybrid_Vamp - https://github.com/hybridvamp

from email.mime import message
import re
import os
import random
import asyncio
import subprocess
import psutil
import platform

from pyrogram.types import Message
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import CallbackQuery
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from hybrid import Bot, LOG_FILE_NAME, logging, ADMINS, CRYPTO_STAT, gen_4letters
from hybrid.plugins.temp import temp
from hybrid.plugins.func import *
from hybrid.plugins.db import *
from hybrid.plugins.fragment import *
from config import D30_RATE, D60_RATE, D90_RATE
try:
    from config import USDT_ADDRESS, TON_ADDRESS
except ImportError:
    import config as _config
    USDT_ADDRESS = getattr(_config, "TON_ADDRESS", "TU5wSTooaND4E5NVEidd9MyNM1NByZGcCF")
    TON_ADDRESS = getattr(_config, "TON_ADDRESS", "UQAYH3MHNSUABi73Z6HwIcuXkmws1tBDDN-lWIPhXZW455bI")

from aiosend.types import Invoice
from datetime import datetime, timezone


if CRYPTO_STAT:
    from hybrid.__init__ import cp

DEFAULT_ADMIN_BACK_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Back to Admin Menu", callback_data="admin_panel")]]
)


# ===================== Callback Query Handler ===================== #

@Bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    if data == "my_rentals":
        numbers = get_numbers_by_user(user_id)
        if not numbers:
            return await query.message.edit_text(
                t(user_id, "no_rentals"),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data="back_home")]]
                ),
            )
        keyboard = []
        for num in numbers:
            label = f"{num} {t(user_id, 'expired_tag')}" if is_rental_expired(num) else num
            keyboard.append([InlineKeyboardButton(label, callback_data=f"num_{num}")])
        keyboard.append([InlineKeyboardButton(t(user_id, "back"), callback_data="back_home")])
        await query.message.edit_text(
            t(user_id, "your_rentals"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("num_"):
        number = data.replace("num_", "")
        num_text = format_number(number)
        await query.message.edit_text(f"⏳ Loading details for **{num_text}**...")
        user_data = get_user_by_number(number)
        if not user_data:
            return await query.message.edit_text(
                t(user_id, "no_rentals"),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data="back_home")]])
            )
        _, hours, date = user_data
        time_left = format_remaining_time(date, hours)
        date_str = format_date(str(date))
        body = t(user_id, "number", num=num_text, time=time_left, date=date_str)
        expired = is_rental_expired(number)
        if expired:
            body += f"\n\n🔴 **{t(user_id, 'expired_tag')}**"
            days_left = get_7day_days_left(number)
            if days_left is not None:
                body += f"\n_{t(user_id, 'expired_pending', days=days_left)}_"
        keyboard = [
            [
                InlineKeyboardButton(t(user_id, "renew"), callback_data=f"renew_{number}"),
                InlineKeyboardButton(t(user_id, "get_code"), callback_data=f"getcode_{number}"),
            ],
            [InlineKeyboardButton(t(user_id, "back"), callback_data="my_rentals")],
        ]
        await query.message.edit_text(body, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("getcode_"):
        number = data.replace("getcode_", "")
        num_text = format_number(number)
        # await query.message.edit_text(f"{t(user_id, 'getting_code')} `{num_text}`...")
        code = get_login_code(number)
        await asyncio.sleep(2)  # Simulate waiting for the code
        if code and code.isdigit():
            keyboard = [
                [InlineKeyboardButton(t(user_id, "back"), callback_data=f"num_{number}")]
            ]
            await query.message.reply(
                t(user_id, "here_is_code", code=code),
                reply_markup=InlineKeyboardMarkup(keyboard)
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
        balance = get_user_balance(user.id) or 0.0
        method = get_user_payment_method(user.id)
        if method == "ton":
            payment_method = "Tonkeeper (TON)"
        elif method == "cryptobot":
            payment_method = "CryptoBot (@send)"
        else:
            payment_method = "Not set"
        text = t(
            user.id,
            "profile_text",
            id=user.id,
            fname=user.first_name or "N/A",
            uname=("@" + user.username) if user.username else "N/A",
            bal=balance,
            payment_method=payment_method
        )
        keyboard = [
            [InlineKeyboardButton(t(user.id, "add_balance"), callback_data="add_balance")],
            [InlineKeyboardButton(t(user.id, "change_payment_method"), callback_data="change_payment_method")],
            [InlineKeyboardButton(t(user.id, "language"), callback_data="language")],
            [InlineKeyboardButton(t(user.id, "back"), callback_data="back_home")],
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "change_payment_method":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Tonkeeper (TON)", callback_data="setpayment_ton")],
            [InlineKeyboardButton("CryptoBot (@send)", callback_data="setpayment_cryptobot")],
            [InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]
        ])
        await query.message.edit_text(t(user_id, "choose_payment_method"), reply_markup=keyboard)

    elif data == "back_home":
        user = query.from_user
        rows = [
            [
                InlineKeyboardButton(t(user.id, "rent"), callback_data="rentnum"),
                InlineKeyboardButton(t(user.id, "my_rentals"), callback_data="my_rentals"),
            ],
            [
                InlineKeyboardButton(t(user.id, "profile"), callback_data="profile"),
                InlineKeyboardButton(t(user.id, "help"), callback_data="help"),
            ],
        ]

        if user.id in ADMINS:
            rows.insert(0, [InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")])

        keyboard = InlineKeyboardMarkup(rows)

        await query.message.edit(
            t(user.id, "welcome", name=user.mention),
            reply_markup=keyboard
        )

    elif data == "setpayment_ton" or data == "setpayment_cryptobot" or data.startswith("setpayment_"):
        method = data.replace("setpayment_", "")
        if method == "ton":
            save_user_payment_method(user_id, "ton")
            await query.message.edit_text(t(user_id, "selected_payment_method", method="Tonkeeper (TON)"),
                                          reply_markup=InlineKeyboardMarkup(
                                              [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                                          ))
        elif method == "cryptobot":
            save_user_payment_method(user_id, "cryptobot")
            await query.message.edit_text(t(user_id, "selected_payment_method", method="CryptoBot (@send)"),
                                          reply_markup=InlineKeyboardMarkup(
                                              [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                                          ))
        else:
            await query.answer("❌ Invalid payment method selected.", show_alert=True)
    
    elif data.startswith("set_payment_"):
        method = data.replace("set_payment_", "")
        if method == "ton":
            save_user_payment_method(user_id, "ton")
            await query.message.edit_text(t(user_id, "selected_payment_method", method="Tonkeeper (TON)"),
                                          reply_markup=InlineKeyboardMarkup(
                                              [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                                          ))
            await asyncio.sleep(3)
            await query.message.delete()
        elif method == "cryptobot":
            save_user_payment_method(user_id, "cryptobot")
            await query.message.edit_text(t(user_id, "selected_payment_method", method="CryptoBot (@send)"),
                                          reply_markup=InlineKeyboardMarkup(
                                              [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                                          ))
            await asyncio.sleep(3)
            await query.message.delete()
        else:
            await query.answer("❌ Invalid payment method selected.", show_alert=True)
            await asyncio.sleep(3)
            await query.message.delete()

    elif data == "add_balance":
        method = get_user_payment_method(user_id)
        if not method:
            return await give_payment_option(client, query.message, user_id)
        chat = query.message.chat

        if method == "cryptobot":
            if not CRYPTO_STAT:
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                )
                return await query.message.edit_text(
                    "❌ CryptoBot payments are currently disabled. Please choose another method.",
                    reply_markup=keyboard
                )
            
            else:
                try:
                    response = await chat.ask(
                        t(user_id, "enter_amount"),
                        timeout=120
                    )
                except Exception:
                    keyboard = InlineKeyboardMarkup(
                        [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                    )
                    return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=keyboard)

                try:
                    amount = float(response.text.strip())
                    if amount <= 0:
                        return await query.message.reply("❌ Amount must be greater than 0.5 USDT.")
                except ValueError:
                    return await query.message.reply("❌ Invalid input. Please enter a valid number.")

                user_id = query.from_user.id

                invoice = await cp.create_invoice(
                    amount=amount,
                    asset="USDT",
                    description=f"Top-up for {user_id}",
                    payload=str(f"{user_id}_{query.message.id}"),
                    allow_comments=False,
                    allow_anonymous=False,
                    expires_in=1800
                )

                # cancel old invoice if exists
                if user_id in temp.INV_DICT:
                    old_inv_id, old_msg_id = temp.INV_DICT[user_id]
                    old_invoice = await cp.get_invoice(old_inv_id)
                    if old_invoice.status == "pending":
                        await cp.cancel_invoice(old_inv_id)
                    try:
                        msg = await client.get_messages(chat.id, old_msg_id)
                        await msg.edit("❌ This invoice has been cancelled due to a new top-up request.")
                    except Exception:
                        pass
                    temp.INV_DICT.pop(user_id, None)

                temp.INV_DICT[user_id] = (invoice.invoice_id, query.message.id)
                temp.PENDING_INV.append(invoice.invoice_id)

                pay_url = invoice.bot_invoice_url
                inv_id = invoice.invoice_id
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(user_id, "pay_now"), url=pay_url)],
                    [InlineKeyboardButton(t(user_id, "i_paid"), callback_data=f"check_payment_{inv_id}")],
                ])

                await query.message.edit_text(
                    t(user_id, "payment_pending", amount=amount, inv=invoice.invoice_id),
                    reply_markup=keyboard
                )
                await response.delete()
                await response.sent_message.delete()
                return

        elif method == "ton":
            try:
                response = await chat.ask(
                    t(user_id, "enter_amount"),
                    timeout=120
                )
            except Exception:
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                )
                return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=keyboard)

            try:
                amount = float(response.text.strip())
                if amount <= 0:
                    return await query.message.reply("❌ Amount must be greater than 0.")
            except ValueError:
                return await query.message.reply("❌ Invalid input. Please enter a valid number.")

            await send_ton_invoice(client, user_id, amount, query.message)
            await response.delete()
            await response.sent_message.delete()

    elif data == "check_payment_" or data.startswith("check_payment_"):
        user_id = query.from_user.id
        if user_id in temp.PAID_LOCK:
            return await query.answer("⏳ Please wait, checking your previous request.", show_alert=True)
        temp.PAID_LOCK.append(user_id)

        inv_id = data.replace("check_payment_", "")
        if inv_id.startswith("TON_"):
            try:
                amount = float(inv_id.replace("TON_", ""))
            except ValueError:
                await query.answer("❌ Invalid amount format.", show_alert=True)
                temp.PAID_LOCK.remove(user_id)
                return
            chat = query.message.chat
            # Ask for transaction hash to verify payment (no auto-credit)
            try:
                await query.message.edit_text(t(user_id, "tx_ton_ask"))
                response = await chat.ask(t(user_id, "transaction_id"), timeout=120)
            except Exception:
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                )
                await query.message.edit_text("⏰ Timeout. Please try again.", reply_markup=keyboard)
                temp.PAID_LOCK.remove(user_id)
                return
            tx_hash = response.text.strip()
            if not tx_hash:
                await query.answer(t(user_id, "ton_tx_invalid"), show_alert=True)
                temp.PAID_LOCK.remove(user_id)
                return
            check, reason = save_ton_tx_hash(tx_hash, user_id)
            if not check and reason == "ALREADY":
                await query.message.reply(t(user_id, "ton_tx_used"))
                await response.delete()
                try:
                    await response.sent_message.delete()
                except Exception:
                    pass
                temp.PAID_LOCK.remove(user_id)
                return
            dest_addr, tx_ton = get_ton_tx(tx_hash)
            if dest_addr is None or tx_ton is None:
                await query.message.reply(t(user_id, "ton_tx_invalid"))
                await response.delete()
                try:
                    await response.sent_message.delete()
                except Exception:
                    pass
                temp.PAID_LOCK.remove(user_id)
                return
            # Optional: verify destination is our wallet (API may return raw or friendly address)
            our_addr = (TON_ADDRESS or "").replace(" ", "").strip().lower()
            dest_norm = (dest_addr or "").replace(" ", "").strip().lower()
            if our_addr and dest_norm and our_addr not in dest_norm and dest_norm not in our_addr:
                # Raw format might differ; allow if amount matches (tx is single-use)
                pass
            if float(tx_ton) < float(amount) - 0.01:
                await query.message.reply(t(user_id, "ton_tx_invalid"))
                await response.delete()
                try:
                    await response.sent_message.delete()
                except Exception:
                    pass
                temp.PAID_LOCK.remove(user_id)
                return
            current_bal = get_user_balance(user_id) or 0.0
            new_bal = current_bal + float(amount)
            save_user_balance(user_id, new_bal)
            pending = temp.PENDING_TON_RENT.pop(user_id, None)
            if pending:
                number, hours = pending
                num_text = format_number(number)
                rent_date = get_current_datetime()
                save_number(number, user_id, hours)
                save_number_data(number, user_id=user_id, rent_date=rent_date, hours=hours)
                if number not in temp.RENTED_NUMS:
                    temp.RENTED_NUMS.append(number)
                prices = get_number_info(number)
                prices = prices.get("prices", {}) if isinstance(prices, dict) else {}
                price_map = {720: prices.get("30d", D30_RATE), 1440: prices.get("60d", D60_RATE), 2160: prices.get("90d", D90_RATE)}
                price = price_map.get(hours, D30_RATE)
                new_bal = new_bal - float(price)
                save_user_balance(user_id, new_bal)
                if hours == 720:
                    days = 30
                elif hours == 1440:
                    days = 60
                elif hours == 2160:
                    days = 90
                else:
                    days = hours // 24
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data="my_rentals")]]
                )
                await query.message.edit_text(
                    t(user_id, "rental_success").format(
                        number=num_text, duration=f"{days} {t(user_id, 'days')}",
                        price=price, balance=new_bal
                    ),
                    reply_markup=keyboard
                )
            else:
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                )
                await query.message.edit_text(
                    t(user_id, "payment_confirmed"),
                    reply_markup=keyboard
                )
            await response.delete()
            try:
                await response.sent_message.delete()
            except Exception:
                pass
            temp.PAID_LOCK.remove(user_id)
            return

        invoice = await cp.get_invoice(inv_id)
        if not invoice or inv_id not in temp.PENDING_INV:
            await query.answer(t(user_id, "payment_not_found"), show_alert=True)
            temp.PAID_LOCK.remove(user_id)
            return

        if invoice.status == "paid":
            payload = invoice.payload
            if payload and payload.startswith("numinfo:"):
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data=payload)]]
                )
            else:
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]]
                )
            current_bal = get_user_balance(user_id) or 0.0
            new_bal = current_bal + float(invoice.amount)
            save_user_balance(user_id, new_bal)

            await query.message.edit_text(
                t(user_id, "payment_confirmed"),
                reply_markup=keyboard
            )
            temp.PAID_LOCK.remove(user_id)
            temp.PENDING_INV.remove(inv_id)
        else:
            await query.answer(t(user_id, "payment_not_found"), show_alert=True)
            temp.PAID_LOCK.remove(user_id)

    elif data == "help":
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(t(user_id, "back"), callback_data="back_home")]]
        )
        await query.message.edit_text(t(user_id, "help_text"), reply_markup=keyboard)

    elif data.startswith("lang_"):
        lang = query.data.split("_")[1]
        user_id = query.from_user.id

        save_user_language(user_id, lang)

        await query.message.edit("✅ Language saved! press /start again to continue.")

    elif data == "language":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")],
            [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
            [InlineKeyboardButton("🇰🇷 한국어", callback_data="lang_ko")],
            [InlineKeyboardButton("🇨🇳 中文", callback_data="lang_zh")],
            [InlineKeyboardButton(t(user_id, "back"), callback_data="profile")]
        ])
        await query.message.edit("🌍 Please choose your language:", reply_markup=keyboard)

    elif data == "admin_panel" and query.from_user.id in ADMINS:
        text = "🛠️ **Admin Panel**\n\nSelect an option below:"
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
        await query.message.edit_text(text, reply_markup=keyboard)
    
    elif data == "user_management" and query.from_user.id in ADMINS:
        text = """👤 **User Management**
        
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
        await query.message.edit_text(text, reply_markup=keyboard)

    elif data == "rental_management" and query.from_user.id in ADMINS:
        text = """🛒 **Rental Management**

Details:
- Numbers: View all rented numbers and their details.
- Assign Number: Manually assign a number to a user.
- Cancel Rent: Cancel a user's rental by User ID or Number.
- Extend Rent: Extend a user's rental duration by User ID or Number.
- Change Rental Date: Modify the rental dates for a user's number.
- Export CSV: Export all rental data in CSV format.
        """
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Numbers", callback_data="admin_numbers"),
                InlineKeyboardButton("Assign Number", callback_data="admin_assign_number"),
            ],
            [
                InlineKeyboardButton("Cancel Rent", callback_data="admin_cancel_rent"),
                InlineKeyboardButton("Extend Rent", callback_data="admin_extend_rent"),
            ],
            [
                InlineKeyboardButton("Change Rental Date", callback_data="change_rental_date"),
                InlineKeyboardButton("📑 Export CSV", callback_data="exportcsv")
            ],
            [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_panel")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard)

    elif data == "number_control" and query.from_user.id in ADMINS:
        rest_toggle = is_restricted_del_enabled()
        if rest_toggle:
            toggle_text = "Disable Restricted Auto-Deletion"
        else:
            toggle_text = "Enable Restricted Auto-Deletion"
        text = """🔢 **Number Control**

Details:
- Enable/Disable Numbers: Toggle the availability of numbers for rent.
- Enable All: Make all numbers available for rent.
- Delete Accounts: Delete a Telegram account associated with a number.
- Banned Numbers: View banned numbers.
- Restricted Auto-Deletion: Toggle automatic deletion of restricted numbers.
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
            [InlineKeyboardButton("Banned Numbers", callback_data="banned_numbers")],
            [InlineKeyboardButton(toggle_text, callback_data="toggle_restricted_del")],
            [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_panel")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard)

    elif data == "admin_tools" and query.from_user.id in ADMINS:
        text = """🛠️ **Admin Tools**

Details:
- Change Rules: Update the rental rules text in multiple languages.
- Check Tx: Verify a transaction ID for balance top-up.
- Admin Help: Get help on using admin features.
        """
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Check Tx", callback_data="checktx"),
                InlineKeyboardButton("Change Rules", callback_data="admin_change_rules"),
            ],
            [
                InlineKeyboardButton("❓ Admin Help", callback_data="admin_help")
            ],
            [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_panel")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard)

    elif data == "admin_numbers" and query.from_user.id in ADMINS:
        await show_numbers(query, page=1)

    elif data == "toggle_restricted_del" and query.from_user.id in ADMINS:
        current_status = is_restricted_del_enabled()
        new_status = restricted_del_toggle()
        status_text = "enabled" if new_status else "disabled"
        await query.message.edit_text(
            f"✅ Restricted numbers auto-deletion has been {status_text}.",
            reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD
        )

    elif data.startswith("admin_numbers_page_"):
        page = int(data.split("_")[-1])
        await show_numbers(query, page=page)

    elif data.startswith("admin_number_"):
        _, _, number, page = data.split("_")
        page = int(page)

        number_data = get_number_info(number)
        if not number_data:
            # save default data if not found
            save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=True)
            logging.info(f"Number {number} not found in DB. Created with default prices.")
        if number not in temp.AVAILABLE_NUM:
            temp.AVAILABLE_NUM.append(number)
        number_data = get_number_info(number)
        price_30d = number_data.get("prices", {}).get("30d", 0.0)
        price_60d = number_data.get("prices", {}).get("60d", 0.0)
        price_90d = number_data.get("prices", {}).get("90d", 0.0)
        available = number_data.get("available", True)
        rented_user = get_user_by_number(number)
        if rented_user:
            rented_status = f"🔴 Rented by User ID: {rented_user[0]}"   
        else:
            rented_status = "🟢 Available"
        text = f"""📞 **Number:** {number}
{rented_status}
• 💵 **Prices:**
    • 30 days: {price_30d} USDT
    • 60 days: {price_60d} USDT
    • 90 days: {price_90d} USDT
• 📦 **Available:** {"✅ Yes" if available else "❌ No"}
• 🛠️ **Last Updated:** {number_data.get("updated_at", "N/A").strftime('%Y-%m-%d %H:%M:%S UTC')}
• 🆔 **In Database:** {"✅ Yes" if number_data else "❌ No"}
"""
        kb = [
            [InlineKeyboardButton("💵 Change Price", callback_data=f"change_price_{number}_{page}")],
            [InlineKeyboardButton("🟢 Toggle Availability", callback_data=f"toggle_avail_{number}_{page}")],
            [InlineKeyboardButton("⬅️ Back", callback_data=f"admin_numbers_page_{page}")]
        ]

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("change_price_") and query.from_user.id in ADMINS:
        _, _, number, page = data.split("_")
        page = int(page)

        try:
            response = await query.message.chat.ask(
                f"💰 Enter new prices for **{number}** in USDT as `30d,60d,90d` (within 120s):",
                timeout=120
            )
        except Exception:
            return await query.message.edit_text("⏰ Timeout! Please try again.")

        try:
            prices = list(map(float, response.text.strip().split(",")))
            if len(prices) != 3 or any(p <= 0 for p in prices):
                return await query.message.reply("❌ Please provide three positive numbers separated by commas.")
            price_30d, price_60d, price_90d = prices
        except ValueError:
            return await query.message.reply("❌ Invalid input. Please enter valid numbers.")

        status = save_number_info(number, price_30d, price_60d, price_90d)
        await response.delete()
        await response.sent_message.delete()

        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data=f"admin_number_{number}_{page}")]
        ]
        await query.message.edit_text(f"✅ Prices for **{number}** updated successfully ({status}).",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    elif data.startswith("toggle_avail_") and query.from_user.id in ADMINS:
        _, _, number, page = data.split("_")
        page = int(page)

        number_data = get_number_info(number)
        if not number_data:
            return await query.message.edit_text("❌ Number not found in database.")

        current_status = number_data.get("available", True)
        new_status = not current_status
        save_number_info(
            number,
            number_data.get("prices", {}).get("30d", 0.0),
            number_data.get("prices", {}).get("60d", 0.0),
            number_data.get("prices", {}).get("90d", 0.0),
            available=new_status
        )

        await query.message.edit_text(
            f"✅ Availability for **{number}** set to {'✅ Yes' if new_status else '❌ No'}.",
        )
        # change in temp.AVAILABLE_NUM
        if new_status and number not in temp.AVAILABLE_NUM:
            temp.AVAILABLE_NUM.append(number)
        elif not new_status and number in temp.AVAILABLE_NUM:
            temp.AVAILABLE_NUM.remove(number)
        if not new_status:
            if number not in temp.UN_AV_NUMS:
                temp.UN_AV_NUMS.append(number)
        else:
            if number in temp.UN_AV_NUMS:
                temp.UN_AV_NUMS.remove(number)
        await asyncio.sleep(2)
        query_data = CallbackQuery(
            id=query.id,
            from_user=query.from_user,
            message=query.message,
            chat_instance=query.chat_instance,
            data=f"admin_number_{number}_{page}"
        )
        await callback_handler(client, query=query_data)
        return

    elif data == "admin_cancel_rent" and query.from_user.id in ADMINS:
        user = query.from_user
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number (starting with +888) to cancel rent (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        identifier = response.text.strip()
        identifier = identifier.replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        if identifier.startswith("+888"):
            number = identifier
            user_data = get_user_by_number(number)
            if not user_data:
                return await query.message.edit_text("❌ This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
            user_id = user_data[0]
        elif identifier.startswith("888") and identifier.isdigit():
            number = f"+{identifier}"
            user_data = get_user_by_number(number)
            if not user_data:
                return await query.message.edit_text("❌ This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
            user_id = user_data[0]
        else:
            return await query.message.reply("❌ Invalid input. Please enter a valid User ID or Number.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        user = await client.get_users(user_id)
        success, status = remove_number(number, user_id)
        remove_number_data(number)


        if success:
            terminate_all_sessions(number)


        if success:
            TEXT = f"""✅ Rental for number **{number}** has been cancelled.
• User ID: {user.id}
• Username: @{user.username if user.username else 'N/A'}
• Name: {user.first_name if user.first_name else 'N/A'}
• Balance: {get_user_balance(user.id) or 0.0}
• Rented On: {user_data[2]}
• Time Left: {format_remaining_time(user_data[2], user_data[1])}
• Cancelled By: {query.from_user.mention} (ID: {query.from_user.id})
            """
            keyboard = [
                [InlineKeyboardButton("🗑️ Delete Account", callback_data=f"delacc_{number}")],
                [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
            ]
            await query.message.edit_text(TEXT, reply_markup=InlineKeyboardMarkup(keyboard))
            try:
                await client.send_message(
                    user.id,
                    f"❌ Your rental for number **{number}** has been cancelled by the admin.\n"
                    f"• Rented On: {user_data[2]}\n"
                    f"• Time Left: {format_remaining_time(user_data[1], user_data[2])}\n"
                    f"For more info, contact support."
                )
            except Exception:
                pass
        
    elif data == "admin_extend_rent" and query.from_user.id in ADMINS:
        user = query.from_user
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number (starting with +888) to extend rent (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        identifier = response.text.strip()
        identifier = identifier.replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        if identifier.startswith("+888"):
            number = identifier
            user_data = get_user_by_number(number)
            if not user_data:
                return await query.message.edit_text("❌ This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
            user_id = user_data[0]
        elif identifier.startswith("888") and identifier.isdigit():
            number = f"+{identifier}"
            user_data = get_user_by_number(number)
            if not user_data:
                return await query.message.edit_text("❌ This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
            user_id = user_data[0]
        else:
            return await query.message.reply("❌ Invalid input. Please enter a valid Number.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        user = await client.get_users(user_id)
        try:
            response = await query.message.chat.ask(
                f"⚠️ Enter the number of hours/days (6h or 2d format) to extend for **{number}** (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        duration_str = response.text.strip().lower()
        await response.delete()
        await response.sent_message.delete()
        match = re.match(r"^(\d+)([hd])$", duration_str)
        if not match:
            return await query.message.reply("❌ Invalid format. Use number followed by 'h' or 'd' (e.g., 6h or 2d).", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        amount, unit = match.groups()
        amount = int(amount)
        hours = amount * 24 if unit == "d" else amount
        success, status = save_number(number, user_id, hours, extend=True)
        if success:
            new_time_left = format_remaining_time(user_data[1], user_data[2] + hours)
            h_days = hours // 24
            TEXT = f"""✅ Rental for number **{number}** has been extended by **{h_days} days**.
• User ID: {user.id}
• Username: @{user.username if user.username else 'N/A'}
• Name: {user.first_name if user.first_name else 'N/A'}
• Balance: {get_user_balance(user.id) or 0.0}
• Rented On: {user_data[1].strftime('%Y-%m-%d %H:%M:%S UTC')}
• New Time Left: {new_time_left}
• Extended By: {query.from_user.mention} (ID: {query.from_user.id})
            """
            keyboard = [
                [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
            ]
            await query.message.edit_text(TEXT, reply_markup=InlineKeyboardMarkup(keyboard))
            try:
                await client.send_message(
                    user.id,
                    f"✅ Your rental for number **{number}** has been extended by **{h_days} days** by the admin.\n"
                    f"• Rented On: {user_data[1].strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"• New Time Left: {new_time_left}\n"
                    f"For more info, contact support."
                )
            except Exception:
                pass

    elif data == "admin_balances" and query.from_user.id in ADMINS:
        to_tal, to_user = get_total_balance()
        text = f"💰 **Total User Balances:**\n\n• Total Balance: **{to_tal} USDT**\n• Total Users with Balance: **{to_user}**"
        keyboard = [
            [InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_add_balance" and query.from_user.id in ADMINS:
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the User ID to add balance to (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        identifier = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        try:
            user_id = int(identifier)
        except ValueError:
            return await query.message.reply("❌ Invalid input. Please enter a valid User ID.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        try:
            user = await client.get_users(user_id)
        except Exception:
            user = None
        if not user:
            return await query.message.edit_text("❌ User not found/invalid User ID. (User must start this bot first)", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        try:
            response = await query.message.chat.ask(
                f"⚠️ Enter the amount in **USDT** to add to user {user.first_name} (ID: {user.id}) (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        try:
            amount = float(response.text.strip())
            if amount <= 0:
                return await query.message.reply("❌ Amount must be greater than 0.5 USDT.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        except ValueError:
            return await query.message.reply("❌ Invalid input. Please enter a valid number.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        current_bal = get_user_balance(user.id) or 0.0
        new_bal = current_bal + amount
        save_user_balance(user.id, new_bal)
        await response.delete()
        await response.sent_message.delete()
        keyboard = [
            [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
        ]
        await query.message.edit_text(
            f"✅ Added **{amount} USDT** to user {user.first_name} (ID: {user.id}). New Balance: **{new_bal} USDT**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        try:
            await client.send_message(
                user.id,
                f"✅ An admin has added **{amount} USDT** to your balance.\n"
                f"• New Balance: **{new_bal} USDT**\n"
                f"For more info, contact support."
            )
        except Exception:
            pass

    elif data == "admin_user_info" and query.from_user.id in ADMINS:
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the User ID to get info for (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        identifier = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        try:
            user_id = int(identifier)
        except ValueError:
            return await query.message.reply("❌ Invalid input. Please enter a valid User ID.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        user = await client.get_users(user_id)
        if not user:
            return await query.message.edit_text("❌ User not found/invalid User ID. (User must start this bot first)", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        balance = get_user_balance(user.id) or 0.0
        numbers = get_numbers_by_user(user.id)
        text = (
            f"👤 **User Info**\n\n"
            f"🆔 User ID: `{user.id}`\n"
            f"👤 First Name: {user.first_name or 'N/A'}\n"
            f"🔗 Username: @{user.username if user.username else 'N/A'}\n"
            f"💰 Balance: **{balance} USDT**\n"
            f"📞 Active Rentals: {len(numbers)}\n"
        )
        if numbers:
            text += "• " + "\n• ".join(numbers) + "\n"
        keyboard = [
            [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_delete_acc" and query.from_user.id in ADMINS:
        # TEST - ask for number to delete account using chat.ask do not check anything with db just ask for number and call delete_account from func.py also ask for code and 2fa if needed
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number to delete account (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        identifier = response.text.strip()
        identifier = identifier.replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        chat = query.message.chat
        stat, reason = await delete_account(identifier, app=client)
        if stat:
            keyboard = [
                [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
            ]
            await query.message.edit_text(f"✅ Account associated with number **{identifier}** has been deleted/deletion counter for one week started successfully.", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            keyboard = [
                [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
            ]
            await query.message.edit_text(f"❌ Failed to delete account for number **{identifier}**. Reason: {reason}", reply_markup=InlineKeyboardMarkup(keyboard))
            if reason == "Banned":
                logging.info(f"Number {identifier} is banned.")
                if identifier not in temp.BLOCKED_NUMS:
                    temp.BLOCKED_NUMS.append(identifier)
        return
        
    elif data == "admin_help" and query.from_user.id in ADMINS:
        text = (
            "❓ **Admin Help & Commands**\n\n"
            "1. **Numbers**: View and manage all numbers in the system.\n"
            "2. **Cancel Rent**: Cancel a user's rental by User ID or Number.\n"
            "3. **Extend Rent**: Extend a user's rental duration by User ID or Number.\n"
            "4. **User Info**: Get detailed information about a user by User ID.\n"
            "5. **User Balances**: View total user balances and add balance to a user.\n"
            "6. **Delete Accounts**: Delete a Telegram account associated with a number.\n"
            "7. **Change Rules**: Update the rental rules text in multiple languages.\n"
            "8. **Check Tx**: Manually check and process pending transactions (if applicable).\n"
            "9. **Restricted Auto-Deletion**: Toggle automatic deletion of restricted numbers.\n\n"
            "For further assistance, contact the bot developer."
        )
        keyboard = [
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_change_rules" and query.from_user.id in ADMINS:
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the new rules text - ENGLISH (within 300s):",
                timeout=300
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        new_rules = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        save_rules(new_rules, lang="en")

        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the new rules text - RUSSIAN (within 300s):",
                timeout=300
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        new_rules = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        save_rules(new_rules, lang="ru")

        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the new rules text - KOREAN (within 300s):",
                timeout=300
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        new_rules = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        save_rules(new_rules, lang="ko")

        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the new rules text - CHINESE (within 300s):",
                timeout=300
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        new_rules = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        save_rules(new_rules, lang="zh")
        
        await query.message.edit_text("✅ Rules updated successfully in all languages.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)

    elif data.startswith("delacc_") and query.from_user.id in ADMINS:
        number = data.replace("delacc_", "")
        user_data = get_user_by_number(number)
        if not user_data:
            return await query.message.edit_text("❌ This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        user_id = user_data[0]
        user = await client.get_users(user_id)

        # ========== Delete Account logic ========== #
        check = await fragment_api.check_is_number_free(number)
        if check:
            return await query.message.edit_text("❌ Cannot delete account. The number is currently in use in Fragment.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        stat, reason = await delete_account(number, app=client, chat=query.message.chat)
        if stat:
            keyboard = [
                [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_panel")]
            ]
            await query.message.edit_text(f"✅ Account associated with number **{number}** has been deleted/deletion counter for one week started successfully.", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        else:
            if reason == "Banned":
                logging.info(f"Number {number} is banned.")
                if number not in temp.BLOCKED_NUMS:
                    temp.BLOCKED_NUMS.append(number)
                            
            return await query.message.edit_text("❌ Failed to delete account. Please check logs.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD) 
        # ========== End Delete Account logic ========== #

    elif data == "rentnum":
        await query.message.edit("⌛")
        choose_text = t(user_id, "choose_number")
        try:
            choose_entities = build_custom_emoji_entities(choose_text)
        except Exception:
            choose_entities = None
        await query.message.edit_text(
            choose_text,
            reply_markup=build_rentnum_keyboard(user_id, page=0),
            entities=choose_entities
        )

    elif data.startswith("rentnum_page:"):
        user_id = query.from_user.id
        choose_text = t(user_id, "choose_number")
        try:
            choose_entities = build_custom_emoji_entities(choose_text)
        except Exception:
            choose_entities = None
        await query.message.edit_text(choose_text, entities=choose_entities)
        page = int(data.split(":")[1])
        await query.message.edit_reply_markup(
            build_rentnum_keyboard(user_id, page=page)
        )

    elif data.startswith("numinfo:"):
        number = data.split(":")[1]
        num_text = format_number(number)
        page = int(data.split(":")[2])
        user_id = query.from_user.id

        info = get_number_info(number)  # main DB record
        if not info and number:
            save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=True)
            info = get_number_info(number)
        rented_data = get_number_data(number)  # rental state (if rented to user)

        if rented_data and rented_data.get("user_id"):  # Already rented
            rent_date = rented_data.get("rent_date")
            date_str = format_date(str(rent_date))
            remaining_days = format_remaining_time(rent_date, rented_data.get("hours", 0))
            txt = (
                f"📞: `{num_text}`\n"
                f"🔴: {t(user_id, 'unavailable')}\n\n"
                f"⏰ {t(user_id, 'days')}: {remaining_days}\n"
                f"📅 {t(user_id, 'date')}: {date_str}"
            )
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(t(user_id, "back"), callback_data=f"rentnum_page:{page}")]]
            )
            await query.message.edit_text(txt, reply_markup=keyboard)

        else:  # Available
            if not info:  # if no record exists at all
                await query.answer(t(user_id, "no_info"), show_alert=True)
                return

            if not info.get("available", True):
                txt = f"📞: `{num_text}`\n🔴: {t(user_id, 'unavailable')}"
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(user_id, "back"), callback_data=f"rentnum_page:{page}")]]
                )
                await query.message.edit_text(txt, reply_markup=keyboard)
                return

            # number available, show rent buttons
            prices = info.get("prices", {})
            txt = (
                f"📞: `{num_text}`\n"
                f"🟢: {t(user_id, 'available')}\n"
                f"💰: {t(user_id, 'rent_now')}"
            )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"30 {t(user_id, 'days')} — {prices.get('30d', D30_RATE)} TON",
                                      callback_data=f"rentfor:{number}:720")],
                [InlineKeyboardButton(f"60 {t(user_id, 'days')} — {prices.get('60d', D60_RATE)} TON",
                                      callback_data=f"rentfor:{number}:1440")],
                [InlineKeyboardButton(f"90 {t(user_id, 'days')} — {prices.get('90d', D90_RATE)} TON",
                                      callback_data=f"rentfor:{number}:2160")],
                [InlineKeyboardButton(t(user_id, "back"), callback_data="rentnum_page:" + str(page))],
            ])
            await query.message.edit_text(txt, reply_markup=keyboard)

    elif data.startswith("admin_enable_numbers") and query.from_user.id in ADMINS:
        user = query.from_user
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number (starting with +888 or 888) to enable numbers (comma separated for multiple) (within 120s):",
                timeout=120
            )
        except Exception:
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
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
                        await query.message.reply("❌ Invalid input. Please enter valid numbers.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
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
                    await query.message.reply("❌ Invalid input. Please enter valid numbers.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
                    return
        if not numbers:
            return await query.message.reply("❌ No valid numbers provided.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        enabled = []
        for number in numbers:
            number_data = get_number_info(number)
            if not number_data:
                save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=True)
                enabled.append(number)
            else:
                if not number_data.get("available", True):
                    save_number_info(
                        number,
                        number_data.get("prices", {}).get("30d", D30_RATE),
                        number_data.get("prices", {}).get("60d", D60_RATE),
                        number_data.get("prices", {}).get("90d", D90_RATE),
                        available=True
                    )
                    enabled.append(number)
        if not enabled:
            return await query.message.reply("❌ No valid numbers provided.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        
        for num in enabled:
            if num not in temp.AVAILABLE_NUM:
                temp.AVAILABLE_NUM.append(num)
        await query.message.reply(f"✅ Enabled the following numbers:\n" + "\n".join(enabled), reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)

    elif data.startswith("admin_disable_numbers") and query.from_user.id in ADMINS:
        user = query.from_user
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number (starting with +888 or 888) to Disable numbers (comma separated for multiple) (within 120s):",
                timeout=120
            )
        except Exception:
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
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
                        await query.message.reply("❌ Invalid input. Please enter valid numbers.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
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
                    await query.message.reply("❌ Invalid input. Please enter valid numbers.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
                    return
        if not numbers:
            return await query.message.reply("❌ No valid numbers provided.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        disabled = []
        for number in numbers:
            number_data = get_number_info(number)
            if not number_data:
                save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=False)
                disabled.append(number)
            else:
                if number_data.get("available", True):
                    save_number_info(
                        number,
                        number_data.get("prices", {}).get("30d", D30_RATE),
                        number_data.get("prices", {}).get("60d", D60_RATE),
                        number_data.get("prices", {}).get("90d", D90_RATE),
                        available=False
                    )
                    disabled.append(number)
        if not disabled:
            return await query.message.reply("❌ No valid numbers provided.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        
        for num in disabled:
            if num in temp.AVAILABLE_NUM:
                temp.AVAILABLE_NUM.remove(num)
        await query.message.reply(f"✅ Disabled the following numbers:\n" + "\n".join(disabled), reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)

    elif data == "admin_enable_all" and query.from_user.id in ADMINS:
        user = query.from_user
        all_numbers = temp.NUMBE_RS
        if not all_numbers:
            return await query.message.reply("❌ No numbers found in the database.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        enabled = []
        for number in all_numbers:
            number_data = get_number_info(number)
            if not number_data:
                save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=True)
                enabled.append(number)
            else:
                if not number_data.get("available", True):
                    save_number_info(
                        number,
                        number_data.get("prices", {}).get("30d", D30_RATE),
                        number_data.get("prices", {}).get("60d", D60_RATE),
                        number_data.get("prices", {}).get("90d", D90_RATE),
                        available=True
                    )
                    enabled.append(number)
        if not enabled:
            return await query.message.reply("❌ All numbers are already enabled.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        
        for num in enabled:
            if num not in temp.AVAILABLE_NUM:
                temp.AVAILABLE_NUM.append(num)
        await query.message.reply(f"✅ Enabled all numbers ({len(enabled)} total).", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)

    elif data == "admin_assign_number" and query.from_user.id in ADMINS:
        user = query.from_user
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the User ID to assign number to (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        identifier = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        try:
            user_id = int(identifier)
        except ValueError:
            return await query.message.reply("❌ Invalid input. Please enter a valid User ID.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        try:
            user = await client.get_users(user_id)
        except Exception:
            user = None
        if not user:
            return await query.message.edit_text("❌ User not found/invalid User ID. (User must start this bot first)", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        try:
            response = await query.message.chat.ask(
                f"⚠️ Enter the Number (starting with +888) to assign to user {user.first_name} (ID: {user.id}) (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        number = response.text.strip()
        number = number.replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        if not number.startswith("+888") or not number[1:].isdigit():
            return await query.message.reply("❌ Invalid number format. It should start with +888 followed by digits.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        number_data = get_number_info(number)
        if not number_data:
            save_number_info(number, D30_RATE, D60_RATE, D90_RATE, available=True)
            logging.info(f"Number {number} not found in DB. Created with default prices.")
        number_data = get_number_info(number)
        if not number_data.get("available", True):
            return await query.message.reply("❌ This number is currently marked as unavailable. Cannot assign.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        rented_data = get_number_data(number)
        if rented_data and rented_data.get("user_id"):
            return await query.message.reply("❌ This number is already rented to another user.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        try:
            response = await query.message.chat.ask(
                f"⚠️ Enter the number of hours (e.g., 720 for 30 days) to assign for **{number}** \n\n 30 days - 720 hours\n 60 days - 1440 hours\n 90 days - 2160 hours\n\n (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        hours = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        if not hours.isdigit():
            return await query.message.reply("❌ Invalid input. Please enter a valid number of hours.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        hours = int(hours)
        if hours <= 0:
            return await query.message.reply("❌ Invalid input. Please enter a positive number of hours.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        # Assign the number to the user
        save_number(number, user.id, hours)
        save_number_data(number, user_id=user.id, rent_date=get_current_datetime(), hours=hours)
        if number not in temp.RENTED_NUMS:
            temp.RENTED_NUMS.append(number)
        await query.message.reply(f"✅ Assigned number **{number}** to user {user.first_name} (ID: {user.id}) for **{hours} hours**.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        await client.send_message(
            user.id,
            f"✅ An admin has assigned you the number **{number}** for **{hours} hours**.\n"
            f"• Rented On: {get_current_datetime().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"For more info, contact support."
        )

    elif data.startswith("rentfor:"):
        _, number, hours = data.split(":")
        num_text = format_number(number)
        hours = int(hours)
        user_id = query.from_user.id
        user = await client.get_users(user_id)

        info = get_number_info(number)
        if not info or not info.get("available", True):
            return await query.answer(t(user_id, "unavailable"), show_alert=True)

        prices = info.get("prices", {})
        price_map = {720: prices.get("30d", D30_RATE), 1440: prices.get("60d", D60_RATE), 2160: prices.get("90d", D90_RATE)}
        price = price_map.get(hours, None)
        if price is None:
            return await query.answer(t(user_id, "error_occurred"), show_alert=True)

        balance = get_user_balance(user.id) or 0.0
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
            method = get_user_payment_method(user.id)
            if not method:
                return await give_payment_option(client, query.message, user.id)
            if method == "cryptobot":
                return await send_cp_invoice(cp, client, user_id, amount, f"Payment for {num_text}", query.message, f"numinfo:{number}:0")
            elif method == "ton":
                temp.PENDING_TON_RENT[user_id] = (number, hours)
                return await send_ton_invoice(client, user_id, amount, query.message)
            return

        if hours == 720:
            days = 30
        elif hours == 1440:
            days = 60
        elif hours == 2160:
            days = 90
        else:
            days = hours // 24

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(t(user_id, "confirm"), callback_data=f"rule:{number}:{hours}"),
                    InlineKeyboardButton(t(user_id, "cancel"), callback_data=f"numinfo:{number}:0")
                ]
            ]
        )
        await query.message.edit_text(
            t(user_id, "confirm_rent").format(number=num_text, days=days, price=price),
            reply_markup=keyboard
        )

    elif data.startswith("rule:"):
        _, number, hours = data.split(":")
        hours = int(hours)
        user_id = query.from_user.id
        rules = get_rules(lang="en")
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
        user_id = query.from_user.id
        user = await client.get_users(user_id)
        info = get_number_info(number)
        if not info or not info.get("available", True):
            return await query.answer(t(user_id, "unavailable"), show_alert=True)
        prices = info.get("prices", {})
        price_map = {720: prices.get("30d", D30_RATE), 1440: prices.get("60d", D60_RATE), 2160: prices.get("90d", D90_RATE)}
        price = price_map.get(hours, None)
        if price is None:
            return await query.answer(t(user_id, "error_occurred"), show_alert=True)
        balance = get_user_balance(user.id) or 0.0
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
            method = get_user_payment_method(user.id)
            if not method:
                return await give_payment_option(client, query.message, user.id)
            if method == "cryptobot":
                return await send_cp_invoice(cp, client, user_id, amount, f"Payment for {num_text}", query.message, f"numinfo:{number}:0")
            elif method == "ton":
                temp.PENDING_TON_RENT[user_id] = (number, hours)
                return await send_ton_invoice(client, user_id, amount, query.message)
            return
        # for renewal check if user already rented this number ,if yes must extend hours by remaining hours + new hours
        rented_data = get_number_data(number)
        if rented_data and rented_data.get("user_id") and rented_data.get("user_id") != user.id:
            return await query.answer(t(user_id, "unavailable"), show_alert=True)


        rent_date = rented_data.get("rent_date", get_current_datetime()) if rented_data else get_current_datetime()

        remaining_hours = get_remaining_hours(rent_date, rented_data.get("hours", 0)) if rented_data else 0

        new_hours = remaining_hours + hours
        new_balance = balance - price

        # if already remaining hours exist, extend from current time
        # else start new rental from now
        if remaining_hours > 0:
            save_number(number, user.id, new_hours, extend=True)
        else:
            save_number(number, user.id, new_hours)

        save_user_balance(user.id, new_balance)
        save_number_data(number, user_id=user.id, rent_date=get_current_datetime(), hours=new_hours)

        if number not in temp.RENTED_NUMS:
            temp.RENTED_NUMS.append(number)
        duration = format_remaining_time(get_current_datetime(), new_hours)

        keyboard = [
            [
                InlineKeyboardButton(t(user_id, "renew"), callback_data=f"renew_{number}"),
                InlineKeyboardButton(t(user_id, "get_code"), callback_data=f"getcode_{number}"),
            ],
            [InlineKeyboardButton(t(user_id, "back"), callback_data="my_rentals")],
        ]
        await query.message.edit_text(
            t(user_id, "rental_success").format(number=num_text, duration=duration, price=price, balance=new_balance),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("renew_"):
        number = data.replace("renew_", "")
        num_text = format_number(number)
        user_id = query.from_user.id
        user = await client.get_users(user_id)
        rented_data = get_number_data(number)
        if not rented_data or rented_data.get("user_id") != user.id:
            return await query.answer(t(user_id, "error_occurred"), show_alert=True)
        info = get_number_info(number)
        if not info or not info.get("available", True):
            return await query.answer(t(user_id, "unavailable"), show_alert=True)
        prices = info.get("prices", {})
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"30 {t(user_id, 'days')} - {prices.get('30d', D30_RATE)} USDT",
                                  callback_data=f"rentfor:{number}:720")],
            [InlineKeyboardButton(f"60 {t(user_id, 'days')} - {prices.get('60d', D60_RATE)} USDT",
                                  callback_data=f"rentfor:{number}:1440")],
            [InlineKeyboardButton(f"90 {t(user_id, 'days')} - {prices.get('90d', D90_RATE)} USDT",
                                  callback_data=f"rentfor:{number}:2160")],
            [InlineKeyboardButton(t(user_id, "back"), callback_data="back_home")],
        ])
        await query.message.edit_text(
            t(user_id, "choose_renew").format(number=num_text),
            reply_markup=keyboard
        )

    elif data == "exportcsv" and query.from_user.id in ADMINS:
        try:
            message = query.message
            msg = await message.reply("⏳ **Exporting numbers data to CSV...**")
            filename = export_numbers_csv(f"numbers_export_{gen_4letters()}.csv")
            await message.reply_document(filename, caption="📑 Exported Numbers Data")
            os.remove(filename)
            await msg.delete()
        except Exception as e:
            await message.reply_text(f"❌ Failed to export: {e}")

    elif data == "checktx" and query.from_user.id in ADMINS:
        try:
            response = await query.message.chat.ask(
                "⚠️ send the transaction hash you wanna check in tron network (within 300s):",
                timeout=300
            )
        except Exception:
            return await query.message.reply("⏰ Timeout! Please try again.")

        tx_hash = response.text
        to, amount, symbol = get_tron_tx(tx_hash)
        if to and amount:
            text = (
                f"✅ Transaction found!\n\n"
                f"🔗 Hash: `{tx_hash}`\n"
                f"🏦 To: `{to}`\n"
                f"💰 Amount: {amount} {symbol}"
            )
            return await query.message.reply(text)
        else:
            return await query.message.reply(f"❌ Transaction {tx_hash} is not found or unconfirmed.")

    elif data == "banned_numbers" and query.from_user.id in ADMINS:
        banned_numbers = temp.BLOCKED_NUMS
        if not banned_numbers:
            return await query.message.reply("❌ No banned numbers found.")
        text = "📜 Banned Numbers:\n" + "\n".join(f"• {num}" for num in banned_numbers)
        return await query.message.reply(text, reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)

    elif data == "change_rental_date" and query.from_user.id in ADMINS:
        try:
            response = await query.message.chat.ask(
                "⚠️ Enter the Number (starting with +888) to change rental date (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.edit_text("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        identifier = response.text.strip()
        identifier = identifier.replace(" ", "")
        await response.delete()
        await response.sent_message.delete()
        if not identifier.startswith("+888"):
            return await query.message.reply("❌ Invalid number format. It should start with +888 followed by digits.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        
        if identifier.startswith("888"):
            identifier = "+" + identifier
        number_data = get_number_info(identifier)
        if not number_data:
            return await query.message.reply("❌ This number does not exist in the database.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        rented_data = get_number_data(identifier)
        if not rented_data or not rented_data.get("user_id"):
            return await query.message.reply("❌ This number is not currently rented.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        keyboard = [
            [InlineKeyboardButton("Change Rental Duration", callback_data=f"changerental_duration_{identifier}")],
            [InlineKeyboardButton("Change Rented date", callback_data=f"changerental_date_{identifier}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="rental_management")]
        ]
        await query.message.edit_text(
            f"📞 Number: **{identifier}**\n"
            f"👤 Rented by User ID: **{rented_data.get('user_id')}**\n"
            f"⏰ Currently rented for (days): {rented_data.get('hours', 0) // 24}\n"
            f"📅 Rented On: {rented_data.get('rent_date').strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("changerental_duration_") and query.from_user.id in ADMINS:
        identifier = data.replace("changerental_duration_", "")
        rented_data = get_number_data(identifier)
        user_id = rented_data.get("user_id")
        rented_date = rented_data.get("rent_date")
        user = await client.get_users(user_id)
        try:
            response = await query.message.chat.ask(
                f"⚠️ Enter the new rental duration in hours or days (e.g. 2h or 3d) for **{identifier}** (currently rented for {rented_data.get('hours', 0)} hours) (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.reply("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        raw = response.text.strip().replace(" ", "").lower()
        await response.delete()
        await response.sent_message.delete()
        if raw.endswith("d") and raw[:-1].isdigit():
            hours = int(raw[:-1]) * 24
        elif raw.endswith("h") and raw[:-1].isdigit():
            hours = int(raw[:-1])
        else:
            return await query.message.reply("❌ Invalid format. Use e.g. 2h or 3d.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        if hours <= 0:
            return await query.message.reply("❌ Invalid input. Please enter a positive number of hours.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        # Keep same rent start date; only change duration so DB + My Rentals reflect correctly
        from hybrid.plugins.func import _ensure_utc
        rent_date_utc = _ensure_utc(rented_date) if rented_date else get_current_datetime()
        save_number(identifier, user.id, hours, date=rent_date_utc, extend=True)
        save_number_data(identifier, user_id=user.id, rent_date=rent_date_utc, hours=hours)
        duration = format_remaining_time(rent_date_utc, hours)
        keyboard = [
            [
                InlineKeyboardButton("Back to Rental Management", callback_data="rental_management")
            ]
        ]
        await query.message.reply(
            f"✅ Updated rental duration for number **{identifier}** to **{hours} hours** (Duration: {duration}).",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("changerental_date_") and query.from_user.id in ADMINS:
        identifier = data.replace("changerental_date_", "")
        rented_data = get_number_data(identifier)
        if not rented_data:
            return await query.message.reply("❌ No rental data for this number.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        user_id = rented_data.get("user_id")
        rented_date = rented_data.get("rent_date")
        hours = int(rented_data.get("hours") or 0)
        user = await client.get_users(user_id)
        date_preview = rented_date.strftime("%Y-%m-%d %H:%M:%S") if rented_date else "N/A"
        try:
            response = await query.message.chat.ask(
                f"⚠️ Enter the new rental start date for **{identifier}** in format DD/MM/YYYY (currently: {date_preview}) (within 120s):",
                timeout=120
            )
        except Exception:
            await response.sent_message.delete()
            return await query.message.reply("⏰ Timeout! Please try again.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        date_str = response.text.strip()
        await response.delete()
        await response.sent_message.delete()
        try:
            new_rent_date = datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            return await query.message.reply("❌ Invalid date format. Please use DD/MM/YYYY.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        new_rent_date = new_rent_date.replace(tzinfo=timezone.utc)
        now = get_current_datetime()
        if getattr(now, "tzinfo", None) is None:
            now = now.replace(tzinfo=timezone.utc)
        if new_rent_date > now:
            return await query.message.reply("❌ Rental date cannot be in the future.", reply_markup=DEFAULT_ADMIN_BACK_KEYBOARD)
        # Update both users_col and rental_col so My Rentals and number list reflect new date
        save_number(identifier, user.id, hours, date=new_rent_date, extend=True)
        save_number_data(identifier, user_id=user.id, rent_date=new_rent_date, hours=hours)
        duration = format_remaining_time(new_rent_date, hours)
        keyboard = [
            [
                InlineKeyboardButton("Back to Rental Management", callback_data="rental_management")
            ]
        ]
        await query.message.reply(
            f"✅ Updated rental start date for number **{identifier}** to **{new_rent_date.strftime('%Y-%m-%d %H:%M:%S')} UTC** (Duration: {duration}).",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
