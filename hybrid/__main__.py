import asyncio
import os
import shutil

try:
    import uvloop
    _has_uvloop = True
except ImportError:
    _has_uvloop = False

from hybrid import Bot, CRYPTO_STAT
from hybrid.plugins.func import run_7day_deletion_scheduler

def _remove_bot_session_files():
    session_name = "rental-bot"
    for base in [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]:
        for name in [f"{session_name}.session", session_name]:
            path = os.path.join(base, name)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    print(f"Removed session file: {path}")
                except Exception as e:
                    print(f"Could not remove {path}: {e}")
            elif os.path.isdir(path):
                try:
                    shutil.rmtree(path)
                    print(f"Removed session dir: {path}")
                except Exception as e:
                    print(f"Could not remove {path}: {e}")

async def main():
    if os.environ.get("RESET_BOT_SESSION", "").strip().lower() in ("1", "true", "yes"):
        _remove_bot_session_files()

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
