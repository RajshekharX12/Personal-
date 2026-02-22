# Entry point: python -m hybrid.main or run this file directly.
# Uses uvloop when available for a faster event loop.

import asyncio

try:
    import uvloop
    _has_uvloop = True
except ImportError:
    _has_uvloop = False

from hybrid.__main__ import main

if __name__ == "__main__":
    if _has_uvloop:
        uvloop.run(main())
    else:
        asyncio.run(main())
