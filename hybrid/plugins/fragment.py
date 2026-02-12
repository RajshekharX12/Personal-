 (©) @Hybrid_Vamp - https://github.com/hybridvamp
# Fragment.com interaction library by Hybrid_Vamp
# Requires cookies exported from browser in Chromium JSON format (frag.json)

import json
import time
import random
import logging
import re
from typing import List, Dict, Tuple, Optional
from httpx import AsyncClient
import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException, Timeout, SSLError, ConnectionError

# from config import FRAGMENT_API_HASH

FRAGMENT_API_HASH = "38f80e92d2dbe5065b"

DATA_T = dict[str, str | int]

# ----- Configure logging for library usage (caller can reconfigure) -----
logger = logging.getLogger(__name__)
if not logger.handlers:
    # basic config if user didn't set logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class FragmentAuthError(Exception):
    """Raised when cookies are invalid / expired or site requires login."""
    pass

class FragmentRateLimitError(Exception):
    """Raised when server responds with 429 and we shouldn't continue."""
    pass


def _load_cookies_from_file(path: str = "frag.json") -> Dict[str, str]:
    """Load cookies from Chromium-style JSON export (frag.json)."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cookies = {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}
    return cookies

def _default_user_agent() -> str:
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def _parse_numbers_from_html(html: str) -> List[str]:
    """Try multiple parsing strategies to find +888... numbers."""
    soup = BeautifulSoup(html, "html.parser")
    found = set()

    # 1) Look for visible text patterns using regex
    for match in re.findall(r"\+888\d{4,15}", soup.get_text(separator=" ")):
        found.add(match)

    # 2) Look for links or hrefs that reference number pages like /number/888...
    for a in soup.select("a[href]"):
        href = a["href"]
        # match either /number/888123456 or /number/+8881234 form in text or href
        m = re.search(r"(?:/number/|\b)(\+?888\d{4,15})", href)
        if m:
            num = m.group(1)
            if not num.startswith("+"):
                num = "+" + num
            found.add(num)
        # also try anchor text
        text = a.get_text(strip=True)
        m2 = re.search(r"\+888\d{4,15}", text)
        if m2:
            found.add(m2.group(0))

    # 3) Look for specific class names that might hold numbers (heuristic)
    for candidate in soup.select(".number, .tm-number, .number-item, .my-number, .phone"):
        txt = candidate.get_text(" ", strip=True)
        m = re.search(r"\+888\d{4,15}", txt)
        if m:
            found.add(m.group(0))

    # 4) Final fallback: any 888... sequences in attributes e.g., data-number
    for tag in soup.find_all(attrs=True):
        for attr_val in tag.attrs.values():
            if isinstance(attr_val, (list, tuple)):
                attr_val = " ".join(attr_val)
            if isinstance(attr_val, str):
                m = re.search(r"\+888\d{4,15}", attr_val)
                if m:
                    found.add(m.group(0))

    # Normalize formatting and sort
    normalized = sorted({re.sub(r"\s+", "", n) for n in found})
    return normalized


def get_fragment_numbers(
    cookies_file: str = "frag.json",
    url: str = "https://fragment.com/my/numbers",
    timeout: int = 15,
    max_retries: int = 5,
    backoff_base: float = 0.6,
    user_agent: Optional[str] = None,
    verify_ssl: bool = True,
    verbose: bool = False,
) -> Tuple[List[str], Dict]:
    """
    Fetch and return list of +888 numbers from fragment.com/my/numbers.

    Returns:
        (numbers_list, meta)
        - numbers_list: List[str] (deduplicated, normalized)
        - meta: dict with information about status, attempts, last_status_code, message
    Raises:
        FragmentAuthError if server indicates login required / cookie invalid.
        FragmentRateLimitError if server returns 429 and Retry-After suggests waiting.
        RequestException for other network-level failures (after retries).
    """
    ua = user_agent or _default_user_agent()
    cookies = _load_cookies_from_file(cookies_file)

    session = requests.Session()
    # Attach cookies in a manner that doesn't mutate storage file
    session.cookies.update(cookies)

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # common headers to mimic a browser read-only GET
        "Referer": "https://fragment.com/",
    }

    attempt = 0
    last_exc = None
    meta = {"attempts": 0, "last_status_code": None, "message": ""}

    while attempt < max_retries:
        attempt += 1
        meta["attempts"] = attempt
        try:
            if verbose:
                logger.info("GET %s (attempt %d)", url, attempt)
            resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True, verify=verify_ssl)

            meta["last_status_code"] = resp.status_code

            # Handle rate limiting
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                msg = f"Rate limited (429). Retry-After: {retry_after}"
                meta["message"] = msg
                # If Retry-After specified and small, raise so caller can respect; else backoff and retry
                if retry_after:
                    # If server explicitly wants us to wait, bail out with a specific exception
                    raise FragmentRateLimitError(msg)
                else:
                    sleep_for = backoff_base * (2 ** (attempt - 1)) + random.random() * 0.5
                    logger.warning("429 received, backing off for %.1fs", sleep_for)
                    time.sleep(sleep_for)
                    continue

            # If not OK, detect auth issues
            if resp.status_code in (401, 403):
                meta["message"] = f"Auth failure HTTP {resp.status_code}"
                raise FragmentAuthError(f"Authentication/permission failure: HTTP {resp.status_code}")

            # Some sites redirect to /login or show a login page with status 200 — detect common signs
            if resp.status_code == 200:
                body = resp.text
                # Heuristics for login page detection
                login_signs = ["login", "sign in", "sign-in", "/login", "stel_ssid", "stel_token"]
                lower = body.lower()
                if ("/login" in resp.url.lower()) or ("please log" in lower) or ("sign in" in lower and "password" in lower):
                    meta["message"] = "Detected login page — cookies may be expired/invalid."
                    raise FragmentAuthError("Detected login page. Cookies likely expired or invalid.")
                # If looks like the numbers page, parse
                numbers = _parse_numbers_from_html(body)

                meta["message"] = "OK"
                # Optionally return an enriched dict if caller wants more details; here we return the numbers and meta
                return numbers, meta

            # Unexpected status code — treat as transient for 5xx, fatal for others
            if 500 <= resp.status_code < 600:
                sleep_for = backoff_base * (2 ** (attempt - 1)) + random.random() * 0.5
                logger.warning("Server error %d, backing off %.1fs", resp.status_code, sleep_for)
                time.sleep(sleep_for)
                continue

            # Any other status: treat as fatal
            meta["message"] = f"Unexpected HTTP status: {resp.status_code}"
            raise RequestException(f"Unexpected HTTP status: {resp.status_code}")

        except (ConnectionError, Timeout, SSLError) as exc:
            last_exc = exc
            sleep_for = backoff_base * (2 ** (attempt - 1)) + random.random() * 0.5
            logger.warning("Network error on attempt %d: %s — backing off %.1fs", attempt, exc, sleep_for)
            time.sleep(sleep_for)
            continue
        except FragmentRateLimitError:
            # Respect server instruction: propagate so caller can handle wait externally
            raise
        except FragmentAuthError:
            # Auth problems should be handled by caller (do not retry silently)
            raise
        except RequestException as exc:
            # Non-network fatal exceptions: break and rethrow
            logger.exception("Fatal request exception: %s", exc)
            raise
    # exhausted retries
    meta["message"] = f"Exhausted {max_retries} retries"
    if last_exc:
        raise RequestException(f"Failed after {max_retries} attempts: {last_exc}")
    else:
        raise RequestException(f"Failed after {max_retries} attempts: last status {meta.get('last_status_code')}")


def _parse_usernames_from_html(html: str) -> List[str]:
    """Extract Telegram usernames (starting with @) from the convert page."""
    soup = BeautifulSoup(html, "html.parser")
    found = set()

    # 1) regex scan for @username
    for match in re.findall(r"@[a-zA-Z0-9_]{5,32}", soup.get_text(" ")):
        found.add(match)

    # 2) anchor texts / href attributes
    for a in soup.select("a[href]"):
        text = a.get_text(strip=True)
        href = a["href"]
        for candidate in (text, href):
            if not candidate:
                continue
            m = re.findall(r"@[a-zA-Z0-9_]{5,32}", candidate)
            found.update(m)

    # 3) specific class selectors (heuristic, e.g., .tm-username)
    for tag in soup.select(".username, .tm-username, .user, .handle"):
        txt = tag.get_text(" ", strip=True)
        m = re.findall(r"@[a-zA-Z0-9_]{5,32}", txt)
        found.update(m)

    return sorted(found)


def get_fragment_usernames(
    cookies_file: str = "frag.json",
    url: str = "https://fragment.com/convert",
    timeout: int = 15,
    max_retries: int = 5,
    backoff_base: float = 0.6,
    user_agent: Optional[str] = None,
    verify_ssl: bool = True,
    verbose: bool = False,
) -> Tuple[List[str], Dict]:
    """
    Fetch and return list of usernames (@...) from fragment.com/convert.

    Returns:
        (usernames_list, meta)
    Raises:
        FragmentAuthError, FragmentRateLimitError, RequestException
    """
    ua = user_agent or _default_user_agent()
    cookies = _load_cookies_from_file(cookies_file)

    session = requests.Session()
    session.cookies.update(cookies)

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://fragment.com/",
    }

    attempt = 0
    last_exc = None
    meta = {"attempts": 0, "last_status_code": None, "message": ""}

    while attempt < max_retries:
        attempt += 1
        meta["attempts"] = attempt
        try:
            if verbose:
                logger.info("GET %s (attempt %d)", url, attempt)
            resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True, verify=verify_ssl)
            meta["last_status_code"] = resp.status_code

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                meta["message"] = f"Rate limited (429). Retry-After: {retry_after}"
                raise FragmentRateLimitError(meta["message"])

            if resp.status_code in (401, 403):
                meta["message"] = f"Auth failure HTTP {resp.status_code}"
                raise FragmentAuthError(meta["message"])

            if resp.status_code == 200:
                body = resp.text
                # detect login page
                if ("/login" in resp.url.lower()) or ("sign in" in body.lower() and "password" in body.lower()):
                    meta["message"] = "Detected login page"
                    raise FragmentAuthError("Cookies expired or invalid.")

                usernames = _parse_usernames_from_html(body)
                meta["message"] = "OK"
                return usernames, meta

            if 500 <= resp.status_code < 600:
                sleep_for = backoff_base * (2 ** (attempt - 1)) + random.random() * 0.5
                logger.warning("Server error %d, backing off %.1fs", resp.status_code, sleep_for)
                time.sleep(sleep_for)
                continue

            meta["message"] = f"Unexpected HTTP {resp.status_code}"
            raise RequestException(meta["message"])

        except (ConnectionError, Timeout, SSLError) as exc:
            last_exc = exc
            sleep_for = backoff_base * (2 ** (attempt - 1)) + random.random() * 0.5
            logger.warning("Network error on attempt %d: %s — backing off %.1fs", attempt, exc, sleep_for)
            time.sleep(sleep_for)
            continue
    # retries exhausted
    meta["message"] = f"Exhausted {max_retries} retries"
    if last_exc:
        raise RequestException(f"Failed after {max_retries} attempts: {last_exc}")
    else:
        raise RequestException(f"Failed after {max_retries} attempts, last code {meta['last_status_code']}")

def get_login_code(number: str, cookies_file="frag.json") -> str:
    """Fetch the login code for a given +888 number from fragment.com."""
    cookies = _load_cookies_from_file(cookies_file)
    session = requests.Session()
    session.cookies.update(cookies)

    num_path = number.replace("+", "").replace(" ", "")
    url = f"https://fragment.com/number/{num_path}/code"

    resp = session.get(url, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch code page: HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Try to extract code
    code_div = soup.find("div", class_="tm-number-code-field")
    if code_div:
        code_text = code_div.get_text(strip=True)
        match = re.search(r"\d+", code_text)
        if match:
            return match.group(0)
    return None

def disable_receive_login_codes(number: str, cookies_file="frag.json") -> bool:
    cookies = _load_cookies_from_file(cookies_file)
    session = requests.Session()
    session.cookies.update(cookies)

    num_path = number.replace("+", "").replace(" ", "")
    url = "https://fragment.com/api"
    formdata = {
        "method": "setPhoneFlag",
        "number": num_path,
        "flag": "receive_codes",
        "value": "false",
    }

    resp = session.post(url, data=formdata, timeout=15)
    if resp.status_code == 200 and resp.json().get("ok"):
        return True
    return False

def terminate_all_sessions(number: str, cookies_file="frag.json") -> str:
    """Terminate all active sessions for the given number."""
    cookies = _load_cookies_from_file(cookies_file)
    session = requests.Session()
    session.cookies.update(cookies)

    num_path = number.replace("+", "").replace(" ", "")
    url = "https://fragment.com/api"

    # Step 1: initiate
    formdata = {
        "method": "terminatePhoneSessions",
        "number": num_path,
    }
    resp = session.post(url, data=formdata, timeout=15)
    data = resp.json()
    if not data.get("ok"):
        raise Exception("Failed to start termination")

    # Step 2: confirm with terminate_hash
    terminate_hash = data.get("terminate_hash")
    formdata["terminate_hash"] = terminate_hash
    resp = session.post(url, data=formdata, timeout=15)

    return resp.json().get("msg", "No message")



class FragmentAPI:
    BASE_URL = "https://fragment.com/api"

    def __init__(self, hash: str, stel_ssid: str, stel_ton_token: str, stel_token: str) -> None:
        self.client = AsyncClient(
            params = {
                "hash": hash
            },
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://fragment.com",
                "Connection": "keep-alive",
                "Referer": "https://fragment.com/my/numbers",
                "Cookie": f"stel_ssid={stel_ssid}; stel_dt=-300; stel_ton_token={stel_ton_token}; stel_token={stel_token}"
            }
        )

    async def _request(self, data: DATA_T) -> DATA_T:
        response = await self.client.post(
            url = self.BASE_URL,
            data = data
        )

        response_data = response.json()

        if "error" in response_data:
            raise Exception(f"""Fragment API error: {response_data["error"]} (request = {data!r})""")

        return response_data

    async def check_is_number_free(self, number: str) -> bool:
        response_data = await self._request(
            data = {
                "type": 3,
                "username": number,
                "auction": "true",
                "method": "canSellItem"
            }
        )

        return response_data.get("confirm_button") != "Proceed anyway"


def extract_fragment_tokens(path: str = "frag.json") -> Dict[str, Optional[str]]:
    """
    Extract key Fragment cookies (stel_ssid, stel_ton_token, stel_token, stel_dt) 
    from a cookies JSON file exported by the browser.

    Returns:
        dict with cookie names as keys and their values (or None if not found).
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Turn list of cookies into a dict {name: value}
    cookies = {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}

    important = ["stel_ssid", "stel_ton_token", "stel_token", "stel_dt"]
    return {k: cookies.get(k) for k in important}


fragment_api = FragmentAPI(
    hash=FRAGMENT_API_HASH,
    stel_ssid=extract_fragment_tokens("frag.json")["stel_ssid"],
    stel_ton_token=extract_fragment_tokens("frag.json")["stel_ton_token"],
    stel_token=extract_fragment_tokens("frag.json")["stel_token"],
)

def get_restricted_numbers(
    cookies_file: str = "frag.json",
    timeout: int = 15,
    user_agent: Optional[str] = None,
    verify_ssl: bool = True,
    verbose: bool = False,
) -> Tuple[List[str], Dict]:
    
    ua = user_agent or _default_user_agent()
    cookies = _load_cookies_from_file(cookies_file)

    session = requests.Session()
    session.cookies.update(cookies)

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://fragment.com/",
    }

    meta = {"checked": 0, "restricted": 0, "message": ""}
    restricted_numbers = []

    numbers, _ = get_fragment_numbers(
        cookies_file=cookies_file,
        timeout=timeout,
        user_agent=ua,
        verify_ssl=verify_ssl,
        verbose=verbose,
    )

    for num in numbers:
        num_path = num.replace("+", "").replace(" ", "")
        url = f"https://fragment.com/number/{num_path}"

        if verbose:
            logger.info("Checking %s", url)

        resp = session.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
        meta["checked"] += 1

        if resp.status_code != 200:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        if soup.select_one("blockquote.tm-section-blockquote.tm-warning"):
            restricted_numbers.append(num)

    meta["restricted"] = len(restricted_numbers)
    meta["message"] = "OK"

    return restricted_numbers

