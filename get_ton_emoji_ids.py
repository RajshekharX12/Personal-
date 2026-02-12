from pyrogram import Client, filters
from config import API_ID, API_HASH, BOT_TOKEN

app = Client("emoji_getter", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.private)
async def get_emoji_id(client, message):
    if message.entities:
        for entity in message.entities:
            if entity.type == "custom_emoji":
                emoji_id = entity.custom_emoji_id
                print(f"\n{'='*50}")
                print(f"Emoji: {message.text[entity.offset:entity.offset + entity.length]}")
                print(f"Emoji ID: {emoji_id}")
                print(f"{'='*50}\n")
                await message.reply(f"Emoji ID: `{emoji_id}`")

print("Bot started. Send premium emojis from TON Emoji pack to get their IDs...")
app.run()
