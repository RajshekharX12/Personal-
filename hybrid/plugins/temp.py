#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import asyncio


class temp(object):
    BOT_UN = None
    PAID_LOCK = set()
    INV_DICT = {}
    PENDING_INV = set()
    NUMBE_RS = []
    NUMBE_RS_SET = set()  # O(1) membership; keep in sync with NUMBE_RS
    AVAILABLE_NUM = set()
    RENTED_NUMS = set()
    UN_AV_NUMS = set()
    RESTRICTED_NUMS = set()
    _lock = asyncio.Lock()

    @classmethod
    def get_lock(cls):
        return cls._lock
    
