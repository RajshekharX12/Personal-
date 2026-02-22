import asyncio

try:
    import uvloop
    _has_uvloop = True
except ImportError:
    _has_uvloop = False

from hybrid import Bot, CRYPTO_STAT
from hybrid.plugins.func import run_7day_deletion_scheduler

async def main():
    bot = Bot()
    await bot.start()
    asyncio.create_task(run_7day_deletion_scheduler(bot))
    if CRYPTO_STAT:
        from hybrid.__init__ import cp
        await cp.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    if _has_uvloop:
        uvloop.run(main())
    else:
        asyncio.run(main())
