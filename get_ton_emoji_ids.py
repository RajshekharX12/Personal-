#!/usr/bin/env python3
"""
Get custom emoji IDs from TON Emoji pack
https://t.me/addemoji/TONEmoji
"""
from pyrogram import Client
from pyrogram.raw import functions, types
import asyncio

API_ID = 15631044
API_HASH = "52b1b075a9996c304a2c938ffb7073c4"
BOT_TOKEN = "8228954627:AAHHD6OOPgLklPfKPYuzxlgwhhnbB-SAaAw"

async def get_ton_emoji_ids():
    app = Client("emoji_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    
    await app.start()
    
    try:
        # Get the TON Emoji sticker set
        result = await app.invoke(
            functions.messages.GetStickerSet(
                stickerset=types.InputStickerSetShortName(short_name="TONEmoji"),
                hash=0
            )
        )
        
        print("=" * 60)
        print("TON EMOJI PACK - Custom Emoji IDs")
        print("=" * 60)
        
        emoji_map = {}
        
        for document in result.documents:
            # Get the emoji character
            emoji_char = None
            for attr in document.attributes:
                if isinstance(attr, types.DocumentAttributeCustomEmoji):
                    # This is a custom emoji
                    pass
                elif isinstance(attr, types.DocumentAttributeSticker):
                    emoji_char = attr.alt
            
            if emoji_char:
                emoji_map[emoji_char] = document.id
                print(f"{emoji_char} -> {document.id}")
        
        print("\n" + "=" * 60)
        print(f"Total emojis found: {len(emoji_map)}")
        print("=" * 60)
        
        # Save to file
        with open("ton_emoji_ids.txt", "w", encoding="utf-8") as f:
            f.write("TON Emoji Pack IDs\n")
            f.write("=" * 60 + "\n\n")
            for emoji, emoji_id in emoji_map.items():
                f.write(f"{emoji} -> {emoji_id}\n")
        
        print("\n✅ Saved to ton_emoji_ids.txt")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nNote: Make sure the bot has access to the sticker pack.")
        print("You may need to add the pack to a chat the bot is in first.")
    
    await app.stop()

if __name__ == "__main__":
    asyncio.run(get_ton_emoji_ids())
