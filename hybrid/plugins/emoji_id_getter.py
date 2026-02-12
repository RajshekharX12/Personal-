#(©) @Hybrid_Vamp - https://github.com/hybridvamp

from pyrogram import Client, filters
from pyrogram.types import Message
from hybrid import Bot, ADMINS

@Bot.on_message(filters.command("getemoji") & filters.user(ADMINS))
async def get_emoji_id_command(client: Client, message: Message):
    """
    Admin command to get custom emoji IDs
    Usage: /getemoji (then send a message with custom emojis)
    """
    await message.reply(
        "✅ **Emoji ID Getter Activated!**\n\n"
        "Now send me a message with custom/premium emojis.\n"
        "I'll extract and show you their IDs!"
    )

@Bot.on_message(filters.text & filters.user(ADMINS) & filters.private)
async def extract_emoji_ids(client: Client, message: Message):
    """
    Extract custom emoji IDs from any message
    """
    if message.text and message.text.startswith("/"):
        return  # Ignore commands
    
    if not message.entities:
        return  # No entities, no custom emojis
    
    custom_emojis = []
    
    for entity in message.entities:
        if entity.type.name == "CUSTOM_EMOJI":
            # Get the emoji character
            emoji_char = message.text[entity.offset:entity.offset + entity.length]
            emoji_id = entity.custom_emoji_id
            custom_emojis.append((emoji_char, emoji_id))
    
    if custom_emojis:
        response = "🎯 **Custom Emoji IDs Found:**\n\n"
        for emoji, emoji_id in custom_emojis:
            response += f"{emoji} → `{emoji_id}`\n"
            response += f'`<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji>`\n\n'
        
        await message.reply(response)
    # If no custom emojis, don't respond (to avoid spam)
