#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import os
import json
from dotenv import load_dotenv
from pyrogram.types import InlineKeyboardButton
import base64

load_dotenv() 

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8612236509:AAFRaPRokisAcKQjHhSzAhsmGdz9PvLZqYk")
API_ID = int(os.environ.get("API_ID", "29060335"))
API_HASH = os.environ.get("API_HASH", "b5b12f67224082319e736dc900a2f604")
OWNER_ID = int(os.environ.get("OWNER_ID", "7940894807"))
REDIS_URI = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DB_NAME = os.environ.get("DATABASE_NAME", "rental")
CRYPTO_API = os.environ.get("CRYPTO_API", "523718:AAEQO6x6qx2PXerElEVuIvBcuL5rdHgDR4Q")
TON_WALLET = os.environ.get("TON_WALLET", "UQAYH3MHNSUABi73Z6HwIcuXkmws1tBDDN-lWIPhXZW455bI")  # TON wallet address for Tonkeeper payments

# ============== FRAGMENT data =============
FRAGMENT_API_HASH = os.environ.get("FRAGMENT_API_HASH", "38f80e92d2dbe5065b")

# ============== GUARD (standalone number checker — own cookies/session) =============
GUARD_HASH = os.environ.get("GUARD_HASH", "38f80e92d2dbe5065b")
GUARD_STEL_SSID = os.environ.get("GUARD_STEL_SSID", "")
GUARD_STEL_TOKEN = os.environ.get("GUARD_STEL_TOKEN", "884240f6dbe482b02a_5308285395763385298")
GUARD_STEL_TON_TOKEN = os.environ.get("GUARD_STEL_TON_TOKEN", "xxgsv9mztTU-BGBYhydE4mJHB3JCNmAJNMtQTxCzs-guGtXGEDyWX2_R34L3nM64DE4Iqq1Vpg8kFRezUhCLavT5aZzERq-qBzOAmeHQiO5nvarAeTbpjWXWSjn3jJL1JhHecWeOZJZtA_zNQgT8Za1VpqHxMh9Gh41mwbJGC7CTAr3q_wnU6zpF3r7CcHyCHuv3eMnb")
GUARD_CACHE_TTL = int(os.environ.get("GUARD_CACHE_TTL", "300"))

# ============== Other Configs =============
D30_RATE = float(os.environ.get("D30_RATE", "80.0"))
D60_RATE = float(os.environ.get("D60_RATE", "152.0"))
D90_RATE = float(os.environ.get("D90_RATE", "224.0"))

with open("lang.json", "r", encoding="utf-8") as f:
    LANGUAGES = json.load(f)

try:
    ADMINS = []
    for x in (os.environ.get("ADMINS", "").split()):
        if x.strip():
            ADMINS.append(int(x))
except ValueError:
    raise Exception("Your Admins list doesn't contain valid integers.")

ADMINS.append(OWNER_ID)








































