#(©) @Hybrid_Vamp - https://github.com/hybridvamp

import asyncio


class temp(object):
    BOT_UN = None
    TEMP_VAR1 = []
    TEMP_VAR2 = []
    PAID_LOCK = set()
    INV_DICT = {}
    PENDING_INV = set()
    NUMBE_RS = []
    AVAILABLE_NUM = set()
    RENTED_NUMS = set()
    UN_AV_NUMS = set()
    BLOCKED_NUMS = set()
    RESTRICTED_NUMS = set()
    _lock = asyncio.Lock()

    @classmethod
    def get_lock(cls):
        return cls._lock
    
