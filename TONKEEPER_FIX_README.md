# Tonkeeper Payment Confirmation Fix

Payment verification now uses **TonCenter API v2** (TON asset processing: https://docs.ton.org/develop/dapps/asset-processing/).

## What Was Added

- **`hybrid/plugins/ton_checker.py`** – New module that polls TonCenter `getTransactions`, parses incoming messages for comment (memo) and value, and credits users when a match is found.

## Required Manual Edit in `hybrid/__init__.py`

Replace the Tonkeeper block in `check_payments()` (around lines 399–445) with:

```python
            # 2. Tonkeeper pending orders (TonCenter API v2 - TON asset processing)
            if TON_WALLET:
                from hybrid.plugins.ton_checker import check_tonkeeper_payments
                await check_tonkeeper_payments(
                    client, get_user_balance, save_user_balance, delete_ton_order,
                    get_all_pending_ton_orders, t, TON_WALLET
                )
```

**Remove** the old block that uses `TON_API_TOKEN`, `tonapi.io`, and parses `TonTransfer` events.

## Changes

1. **No `TON_API_TOKEN`** – TonCenter is used and does not need an API key.
2. **Correct parsing** – Uses `getTransactions` and inspects `in_msg.msg_data` for `msg.dataText` (comment) and `in_msg.value` (amount in nanotons).
3. **Compatible with TON docs** – Follows the invoice-based Toncoin payment flow described in the TON asset-processing guide.

## Apply the Patch (if Python is available)

```bash
cd /path/to/RentalBotcc
python patch_init.py
```

Then delete `patch_init.py` and this README.
