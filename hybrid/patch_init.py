path = "hybrid/__init__.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace TonAPI block with TonCenter-based checker call
old_block = """                pending = get_all_pending_ton_orders()
                for order_ref, order in pending:
                    try:
                        url = f"https://tonapi.io/v2/accounts/{TON_WALLET}/events?limit=30"
                        headers = {"Authorization": f"Bearer {TON_API_TOKEN}"}
                        loop = asyncio.get_event_loop()
                        r = await loop.run_in_executor(None, lambda: requests.get(url, headers=headers, timeout=15))
                        if r.status_code != 200:
                            continue
                        data = r.json()
                        events = data.get("events") or []
                        memo_needle = order_ref  # e.g. PayEFoT3YAg (no #)
                        amount_ton = order.get("amount_ton") or (float(order["amount"]) / 5.0)  # fallback
                        amount_nano_min = int(float(amount_ton) * 1_000_000_000 * 0.99)
                        for ev in events:
                            for act in ev.get("actions") or []:
                                atype = act.get("type", "")
                                if atype not in ("TonTransfer", "ton_transfer"):
                                    continue
                                tt = act.get("TonTransfer") or act.get("ton_transfer") or act
                                recip = tt.get("recipient") or tt.get("destination")
                                dest = (recip.get("address") if isinstance(recip, dict) else None) or (str(recip) if recip else "") or ""
                                comment = str(tt.get("comment") or tt.get("payload") or "").strip()
                                amt = int(tt.get("amount", 0) or tt.get("amount_nano", 0) or 0)
                                if memo_needle in comment or comment == memo_needle or comment.strip() == memo_needle:
                                    if TON_WALLET in str(dest) or (dest and dest.replace("-", "").replace("_", "") in TON_WALLET.replace("-", "").replace("_", "")):
                                        if amt >= amount_nano_min:
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
                        logging.debug(f"Tonkeeper check order {order_ref}: {e}")"""

new_block = """                from hybrid.plugins.ton_checker import check_tonkeeper_payments
                await check_tonkeeper_payments(
                    client, get_user_balance, save_user_balance, delete_ton_order,
                    get_all_pending_ton_orders, t, TON_WALLET
                )"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK")
else:
    print("NOT_FOUND")
