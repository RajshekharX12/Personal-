# Premium emoji / test handler
from pyrogram import filters
from pyrogram.enums import ParseMode
from hybrid import Bot

@Bot.on_message(filters.command("test") & filters.private)
async def test_premium_emoji(client, message):
    """Test premium emoji rendering."""
    await message.reply(
        '<tg-emoji emoji-id="5323628709469495421">✅</tg-emoji> Success — Premium emoji is working!',
        parse_mode=ParseMode.HTML,
    )
