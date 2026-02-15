# Tonkeeper payment checker using TonCenter API v2 (TON asset processing)
# https://docs.ton.org/develop/dapps/asset-processing/

import asyncio
import base64
import logging
import requests

from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton


async def check_tonkeeper_payments(client, get_user_balance, save_user_balance, delete_ton_order,
                                   get_all_pending_ton_orders, t, TON_WALLET):
    """Poll TonCenter getTransactions, parse in_msg comment and value. Credit on match."""
    if not TON_WALLET:
        return
    pending = get_all_pending_ton_orders()
    if not pending:
        return
    try:
        url = f"https://toncenter.com/api/v2/getTransactions?address={TON_WALLET}&limit=30"
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: requests.get(url, timeout=15))
        if r.status_code != 200:
            return
        data = r.json()
        txs = data.get("result") or []
        for order_ref, order in pending:
            memo_needle = order_ref
            amount_ton = order.get("amount_ton") or (float(order["amount"]) / 5.0)
            amount_nano_min = int(float(amount_ton) * 1_000_000_000 * 0.99)
            for tx in txs:
                in_msg = tx.get("in_msg")
                if not in_msg or in_msg.get("@type") != "ext.message":
                    continue
                dest = in_msg.get("destination") or ""
                if TON_WALLET not in str(dest):
                    wallet_norm = TON_WALLET.replace("-", "").replace("_", "")
                    dest_norm = str(dest).replace("-", "").replace("_", "")
                    if dest_norm != wallet_norm:
                        continue
                try:
                    amt = int(in_msg.get("value") or 0)
                except (ValueError, TypeError):
                    amt = 0
                if amt < amount_nano_min:
                    continue
                msg_data = in_msg.get("msg_data") or {}
                comment = ""
                if msg_data.get("@type") == "msg.dataText":
                    comment = (msg_data.get("message") or "").strip()
                    if not comment and msg_data.get("text"):
                        try:
                            comment = base64.b64decode(msg_data["text"]).decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                if memo_needle not in comment and comment != memo_needle and (comment or "").strip() != memo_needle:
                    continue
                user_id = order["user_id"]
                payload = order["payload"]
                current_bal = get_user_balance(user_id) or 0.0
                new_bal = current_bal + order["amount"]
                save_user_balance(user_id, new_bal)
                back_cb = payload if payload and str(payload).startswith("numinfo:") else "profile"
                try:
                    await client.edit_message_text(
                        order["chat_id"], order["msg_id"],
                        t(user_id, "payment_confirmed"),
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(user_id, "back"), callback_data=back_cb)]])
                    )
                except Exception:
                    pass
                delete_ton_order(order_ref)
                break
    except Exception as e:
        logging.error(f"Tonkeeper check error: {e}")
