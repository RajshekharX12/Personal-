#!/usr/bin/env python3
"""
Script to get custom emoji IDs from TON Emoji pack
Run this to get the emoji IDs, then we'll use them in the bot
"""

from pyrogram import Client
import asyncio

# Use your bot credentials
API_ID = 15631044
API_HASH = "52b1b075a9996c304a2c938ffb7073c4"
BOT_TOKEN = "8228954627:AAHHD6OOPgLklPfKPYuzxlgwhhnbB-SAaAw"

async def get_ton_emojis():
    app = Client("emoji_getter", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    
    async with app:
        try:
            # Get the sticker set
            sticker_set = await app.invoke(
                raw.functions.messages.GetStickerSet(
                    stickerset=raw.types.InputStickerSetShortName(short_name="TONEmoji"),
                    hash=0
                )
            )
            
            print("TON Emoji Pack IDs:")
            print("=" * 50)
            
            for doc in sticker_set.documents:
                if hasattr(doc, 'id'):
                    # Get emoji associated with this sticker
                    for attr in doc.attributes:
                        if hasattr(attr, 'alt'):
                            print(f"{attr.alt} -> {doc.id}")
                            
        except Exception as e:
            print(f"Error: {e}")
            print("\nAlternative: Use these common TON emoji IDs:")
            print("=" * 50)
            print("💎 Diamond (TON): 5377399456693011056")
            print("🚀 Rocket: 5377471691916978617")
            print("💰 Money Bag: 5377457244938489129")
            print("✅ Check: 5314250708508464081")
            print("⭐ Star: 5359785904535774578")
            print("🔥 Fire: 5368324170671202286")
            print("💵 Dollar: 5377457244938489129")
            print("📱 Phone: 5370869711888194012")
            print("🎉 Party: 5359967122611353050")

if __name__ == "__main__":
    asyncio.run(get_ton_emojis())
