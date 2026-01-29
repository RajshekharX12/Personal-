import asyncio
from hybrid import Bot, CRYPTO_STAT

async def main():
    bot = Bot()
    await bot.start()
    if CRYPTO_STAT:
        from hybrid.__init__ import cp
        await cp.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
