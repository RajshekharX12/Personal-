# Premium emoji / test handler
from pyrogram import filters
from pyrogram.enums import ParseMode
from hybrid import Bot

@Bot.on_message(filters.command("test") & filters.private)
async def test_premium_emoji(client, message):
    await message.reply(
        '<emoji id="5440410042773824003">✅</emoji> Success — Premium emoji is working!',
        parse_mode=ParseMode.HTML,
    )
