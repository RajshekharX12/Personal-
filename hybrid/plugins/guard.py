# (©) @Hybrid_Vamp - https://github.com/hybridvamp
# Standalone number checker (Guard) — own cookies, hash, HTTP client, cache.
# If guard breaks, main bot keeps working. If main cookies die, guard still checks numbers.

import asyncio
import hashlib
import logging
import random
import re
from typing import Any, Dict, Optional, Tuple

import httpx

# ----- 2a. AsyncTimedCache (inspired by NFTNumberBot cache.py) -----

class AsyncTimedCache:
    """Generic K,V cache with per-entry expiration using asyncio.get_event_loop().time()."""

    def __init__(self, default_ttl_seconds: float = 300):
        self._store: Dict[Any, Tuple[Any, float]] = {}  # key -> (value, expiration_time)
        self._default_ttl = default_ttl_seconds

    def _now(self) -> float:
        return asyncio.get_event_loop().time()

    def get(self, key: Any) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, exp = entry
        if self._now() >= exp:
            del self._store[key]
            return None
        return value

    def set(self, key: Any, value: Any, ttl_seconds: Optional[float] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._store[key] = (value, self._now() + ttl)

    def remove(self, key: Any) -> None:
        self._store.pop(key, None)

    def clean_expired(self) -> int:
        now = self._now()
        to_remove = [k for k, (_, exp) in self._store.items() if now >= exp]
        for k in to_remove:
            del self._store[k]
        return len(to_remove)

    def clear_all(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


# ----- 2b. Number validation (inspired by NFTNumberBot utils.py) -----

ANON_NUMBER_RE = re.compile(r"^\+?888[-\s]?\d{4}([-.\\s]?\d{4})?$")
ANON_NUMBER_RAW_RE = re.compile(r"[^\d]")


def parse_anon_number(raw: str) -> Optional[str]:
    """Parse and normalize +888 number. Returns digits-only string or None if invalid."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not ANON_NUMBER_RE.match(s):
        return None
    digits = ANON_NUMBER_RAW_RE.sub("", s)
    if digits.startswith("888") and len(digits) >= 11:
        return digits
    return None


def format_display(digits: str) -> str:
    """Format digits as +888 1234 5678."""
    if not digits or len(digits) < 11:
        return digits or ""
    if digits.startswith("888"):
        return f"+888 {digits[3:7]} {digits[7:]}"
    return f"+{digits[:3]} {digits[3:7]} {digits[7:]}"


# ----- 2c. GuardFragmentAPI (inspired by NFTNumberBot fragment_api.py) -----

DATA_T = Dict[str, str | int | bool]


class GuardFragmentAPI:
    BASE_URL = "https://fragment.com/api"

    def __init__(
        self,
        hash_val: str,
        stel_ssid: str,
        stel_ton_token: str,
        stel_token: str,
    ) -> None:
        self._hash = hash_val
        self._stel_ssid = stel_ssid
        self._stel_ton_token = stel_ton_token
        self._stel_token = stel_token
        self._client: Optional[httpx.AsyncClient] = self._build_client()

    def _build_client(self) -> Optional[httpx.AsyncClient]:
        if not all([self._stel_ssid, self._stel_ton_token, self._stel_token]):
            return None
        cookie = f"stel_ssid={self._stel_ssid}; stel_dt=-300; stel_ton_token={self._stel_ton_token}; stel_token={self._stel_token}"
        return httpx.AsyncClient(
            params={"hash": self._hash},
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.5",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://fragment.com",
                "Referer": "https://fragment.com/my/numbers",
                "Cookie": cookie,
            },
            timeout=10.0,
        )

    @property
    def ready(self) -> bool:
        return self._client is not None and all(
            [self._stel_ssid, self._stel_ton_token, self._stel_token]
        )

    async def _request(self, data: DATA_T) -> DATA_T:
        if self._client is None:
            raise RuntimeError("Guard API not ready (missing cookies).")
        response = await self._client.post(self.BASE_URL, data=data)
        response_data = response.json()
        if "error" in response_data:
            raise Exception(
                f"Fragment API error: {response_data['error']} (request = {data!r})"
            )
        return response_data

    async def check_is_number_free(self, number: str) -> bool:
        num_clean = number.replace("+", "").replace(" ", "")
        response_data = await self._request(
            data={
                "type": 3,
                "username": num_clean,
                "auction": "true",
                "method": "canSellItem",
            }
        )
        return response_data.get("confirm_button") != "Proceed anyway"

    async def reload_cookies(self) -> None:
        """Hot-reload: read config again, close old client, build new one. Caller should clear cache."""
        import importlib
        import config
        importlib.reload(config)
        self._hash = getattr(config, "GUARD_HASH", "") or ""
        self._stel_ssid = getattr(config, "GUARD_STEL_SSID", "") or ""
        self._stel_ton_token = getattr(config, "GUARD_STEL_TON_TOKEN", "") or ""
        self._stel_token = getattr(config, "GUARD_STEL_TOKEN", "") or ""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        self._client = self._build_client()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ----- 2d. Module-level init -----

_api: Optional[GuardFragmentAPI] = None
_cache: Optional[AsyncTimedCache] = None

try:
    from config import (
        GUARD_HASH,
        GUARD_STEL_SSID,
        GUARD_STEL_TOKEN,
        GUARD_STEL_TON_TOKEN,
        GUARD_CACHE_TTL,
    )
    _api = GuardFragmentAPI(
        hash_val=GUARD_HASH or "",
        stel_ssid=GUARD_STEL_SSID or "",
        stel_ton_token=GUARD_STEL_TON_TOKEN or "",
        stel_token=GUARD_STEL_TOKEN or "",
    )
    _cache = AsyncTimedCache(default_ttl_seconds=float(GUARD_CACHE_TTL))
    if not _api.ready:
        _api = None
except Exception as e:
    logging.warning("Guard module init failed: %s — number checks via guard disabled.", e)
    _api = None
    _cache = AsyncTimedCache(default_ttl_seconds=300)


# ----- 2e. Public API -----

async def guard_is_free(number: str) -> bool:
    """
    DROP-IN REPLACEMENT for fragment_api.check_is_number_free().
    Checks cache first, then hits Fragment API.
    Returns True = free, False = busy.
    Raises RuntimeError if guard not ready.
    """
    if _api is None or not _api.ready:
        raise RuntimeError("Guard not ready (missing or invalid GUARD_* config).")
    normalized = parse_anon_number(number)
    if not normalized:
        raise ValueError(f"Invalid +888 number: {number!r}")
    cache_key = f"free:{normalized}"
    if _cache is not None:
        cached = _cache.get(cache_key)
        if cached is not None:
            return bool(cached)
    result = await _api.check_is_number_free(number)
    if _cache is not None:
        from config import GUARD_CACHE_TTL
        _cache.set(cache_key, result, ttl_seconds=float(GUARD_CACHE_TTL))
    return result


async def guard_check(number: str) -> Tuple[Optional[bool], str]:
    """
    Check if number is free. Returns (True, msg) if free, (False, msg) if busy,
    (None, error_msg) on error.
    """
    try:
        is_free = await guard_is_free(number)
        if is_free:
            return True, f"Number {format_display(parse_anon_number(number) or number)} is available (free on Fragment)."
        return False, f"Number {format_display(parse_anon_number(number) or number)} is not available (busy on Fragment)."
    except RuntimeError as e:
        return None, f"Guard not ready: {e}"
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        logging.exception("guard_check failed for %s", number)
        return None, f"Check failed: {e}"


# ----- 2f. Bot commands and inline handler (register on Bot from hybrid) -----

def _register_guard_handlers() -> None:
    from pyrogram import filters
    from pyrogram.enums import ParseMode
    from pyrogram.types import (
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        InlineQueryResultArticle,
        InputTextMessageContent,
    )
    from hybrid import Bot, ADMINS

    @Bot.on_message(filters.command("checknum") & filters.user(ADMINS))
    async def cmd_checknum(_, message):
        try:
            text = (message.text or "").strip().split(maxsplit=1)
            if len(text) >= 2 and (text[1].startswith("+888") or text[1].replace(" ", "").startswith("888")):
                number = text[1].strip().replace(" ", "")
                if not number.startswith("+"):
                    number = "+" + number
            else:
                response = await message.chat.ask(
                    "⚠️ Send the number you want to check (e.g. +888 1234 5678):",
                    timeout=30,
                )
                number = (response.text or "").strip().replace(" ", "")
                if not number.startswith("+"):
                    number = "+" + number
            if not number.startswith("+888"):
                await message.reply_text(
                    "<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Invalid number. Use a +888 number.",
                    parse_mode=ParseMode.HTML,
                )
                return
            ok, status_msg = await guard_check(number)
            if ok is True:
                await message.reply_text(
                    f"<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> {status_msg}",
                    parse_mode=ParseMode.HTML,
                )
            elif ok is False:
                await message.reply_text(
                    f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> {status_msg}",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.reply_text(
                    f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> {status_msg}",
                    parse_mode=ParseMode.HTML,
                )
        except asyncio.TimeoutError:
            await message.reply_text(
                "<tg-emoji emoji-id=\"5242628160297641831\">⏰</tg-emoji> Timeout. Try again.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.exception("checknum command failed")
            await message.reply_text(
                f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Error: {e}",
                parse_mode=ParseMode.HTML,
            )

    @Bot.on_message(filters.command("reload_guard") & filters.user(ADMINS))
    async def cmd_reload_guard(_, message):
        global _api, _cache
        try:
            if _api is None:
                await message.reply_text(
                    "Guard was not initialized. Set GUARD_* env vars and restart.",
                    parse_mode=ParseMode.HTML,
                )
                return
            await _api.reload_cookies()
            if _cache is not None:
                _cache.clear_all()
            await message.reply_text(
                "<tg-emoji emoji-id=\"5323628709469495421\">✅</tg-emoji> Guard credentials reloaded and cache cleared.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.exception("reload_guard failed")
            await message.reply_text(
                f"<tg-emoji emoji-id=\"5767151002666929821\">❌</tg-emoji> Reload failed: {e}",
                parse_mode=ParseMode.HTML,
            )

    @Bot.on_message(filters.command("guard_status") & filters.user(ADMINS))
    async def cmd_guard_status(_, message):
        try:
            api_ready = _api is not None and _api.ready
            cookies_loaded = bool(
                _api is not None
                and getattr(_api, "_stel_ssid", None)
                and getattr(_api, "_stel_token", None)
                and getattr(_api, "_stel_ton_token", None)
            )
            cache_size = _cache.size if _cache is not None else 0
            from config import GUARD_CACHE_TTL
            ttl = GUARD_CACHE_TTL
            text = (
                "🛡️ <b>Guard status</b>\n\n"
                f"• API ready: {api_ready}\n"
                f"• Cookies loaded: {cookies_loaded}\n"
                f"• Cache size: {cache_size}\n"
                f"• Cache TTL: {ttl}s\n"
            )
            await message.reply_text(text, parse_mode=ParseMode.HTML)
        except Exception as e:
            await message.reply_text(f"Error: {e}", parse_mode=ParseMode.HTML)

    @Bot.on_inline_query()
    async def inline_query_handler(_, inline_query):
        query = (inline_query.query or "").strip()
        number = parse_anon_number(query)
        if not number:
            await inline_query.answer(
                [],
                cache_time=0,
                switch_pm_text="Enter a +888 number (e.g. +888 1234 5678)",
                switch_pm_parameter="guard",
            )
            return
        display = format_display(number)
        try:
            is_free = await guard_is_free(number)
            if is_free:
                title = "✅ FREE"
                desc = f"{display} is available on Fragment."
            else:
                title = "❌ BUSY"
                desc = f"{display} is not available (linked to account)."
        except Exception as e:
            title = "❓ Error"
            desc = str(e)[:200]
        result_id = hashlib.md5(
            f"{number}{random.random()}{inline_query.id}".encode()
        ).hexdigest()
        results = [
            InlineQueryResultArticle(
                id=result_id,
                title=title,
                description=desc,
                input_message_content=InputTextMessageContent(
                    message_text=f"{title} — {display}",
                    parse_mode=None,
                ),
            )
        ]
        await inline_query.answer(results, cache_time=0)


# Register when module is loaded (hybrid/plugins is the plugin root, so this runs on import)
try:
    _register_guard_handlers()
except Exception as e:
    logging.warning("Guard handler registration failed: %s", e)
