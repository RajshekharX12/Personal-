#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import os
import json
from dotenv import load_dotenv
from pyrogram.types import InlineKeyboardButton
import base64

load_dotenv() 

BOT_TOKEN = os.environ.get("BOT_TOKEN", "7780014048:AAGuVnYTxEyfaJdHNp0-Mw29q8tKdb5B3uU")
API_ID = int(os.environ.get("API_ID", "29060335"))
API_HASH = os.environ.get("API_HASH", "b5b12f67224082319e736dc900a2f604")
OWNER_ID = int(os.environ.get("OWNER_ID", "7940894807"))
REDIS_URI = os.environ.get("REDIS_URL", "redis://:Vu9yPldfEJJo3N9IvoVFw1NPRvTofWAi@redis-18639.c56.east-us.azure.cloud.redislabs.com:18639/0")
DB_NAME = os.environ.get("DATABASE_NAME", "rental")
CRYPTO_API = os.environ.get("CRYPTO_API", "523718:AAEQO6x6qx2PXerElEVuIvBcuL5rdHgDR4Q")
TON_WALLET = os.environ.get("TON_WALLET", "UQAYH3MHNSUABi73Z6HwIcuXkmws1tBDDN-lWIPhXZW455bI")  # TON wallet address for Tonkeeper payments
TON_API_TOKEN = os.environ.get("TON_API_TOKEN", "762cfcfb5dc3b67f31d8eba4fec6377bc98b28f3b8e2a24954d31201e6143911")  # Optional: for payment checker (get from @tonapibot)

# ============== FRAGMENT data =============
FRAGMENT_API_HASH = os.environ.get("FRAGMENT_API_HASH", "38f80e92d2dbe5065b")

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































