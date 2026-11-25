"""
Tests for constants module.
"""
import pytest
from constants import (
    AccountStatus,
    ServiceFilter,
    TaskStatus,
    Timeouts,
    Intervals,
    Limits,
    FirebasePaths,
    PLATFORM_LOGIN_URLS,
    PLATFORM_DOMAIN_MAP,
    SUPPORTED_PLATFORMS,
    PATTERNS,
    HEALTH_THRESHOLDS,
    WS_CHANCE_THRESHOLDS,
    DEFAULTS,
    CACHE_KEYS,
)


class TestEnums:
    def test_account_status_values(self):
        assert AccountStatus.ACTIVE.value == "active"
        assert AccountStatus.LOGGING_IN.value == "logging_in"
        assert AccountStatus.WAITING_7_DAYS.value == "waiting_7_days"
        assert AccountStatus.FAILED.value == "failed"
        assert AccountStatus.UNKNOWN.value == "unknown"

    def test_service_filter_values(self):
        assert ServiceFilter.WHATSAPP.value == "whatsapp"
        assert ServiceFilter.TELEGRAM.value == "telegram"
        assert ServiceFilter.ANY.value == "any"

    def test_task_status_values(self):
        assert TaskStatus.IDLE.value == "Idle"
        assert TaskStatus.SCANNING.value == "Scanning"
        assert TaskStatus.HUNTING.value == "Hunting"


class TestTimeouts:
    def test_firebase_timeouts(self):
        assert Timeouts.FIREBASE_REQUEST == 10
        assert Timeouts.FIREBASE_LONG_REQUEST == 20

    def test_other_timeouts(self):
        assert Timeouts.PROXY_CHECK == 6
        assert Timeouts.AI_API_REQUEST == 20
        assert Timeouts.OTP_WAIT == 300


class TestIntervals:
    def test_scanner_intervals(self):
        assert Intervals.SCANNER_POLL == 1.0
        assert Intervals.BACKUP_SCANNER == 10
        assert Intervals.WHATSAPP_SCANNER == 60

    def test_other_intervals(self):
        assert Intervals.PROXY_SCANNER == 300
        assert Intervals.SELF_PING == 600
        assert Intervals.DB_FLUSH == 60


class TestLimits:
    def test_max_values(self):
        assert Limits.MAX_OTPS_PER_ACCOUNT == 20
        assert Limits.MAX_OTP_HISTORY_PER_USER == 20
        assert Limits.MAX_ACTIVITY_FEED == 50
        assert Limits.MAX_WORKING_PROXIES == 10


class TestFirebasePaths:
    def test_static_paths(self):
        assert FirebasePaths.CLIENTS == "clients"
        assert FirebasePaths.MESSAGES == "messages"

    def test_messages_for_device(self):
        path = FirebasePaths.messages_for_device("dev123", 5)
        assert "messages/dev123.json" in path
        assert "limitToLast=5" in path

    def test_messages_full(self):
        path = FirebasePaths.messages_full("dev123", 100)
        assert "messages/dev123.json" in path
        assert "limitToLast=100" in path


class TestPlatformConfig:
    def test_login_urls_exist(self):
        assert "PayPal" in PLATFORM_LOGIN_URLS
        assert "Facebook" in PLATFORM_LOGIN_URLS
        assert "Instagram" in PLATFORM_LOGIN_URLS
        assert "Telegram" in PLATFORM_LOGIN_URLS
        assert "Google" in PLATFORM_LOGIN_URLS
        assert "GitHub" in PLATFORM_LOGIN_URLS

    def test_supported_platforms(self):
        assert "PayPal" in SUPPORTED_PLATFORMS
        assert "Facebook" in SUPPORTED_PLATFORMS
        assert len(SUPPORTED_PLATFORMS) >= 7

    def test_domain_map(self):
        assert PLATFORM_DOMAIN_MAP["paypal"] == "PayPal"
        assert PLATFORM_DOMAIN_MAP["facebook"] == "Facebook"
        assert PLATFORM_DOMAIN_MAP["instagram"] == "Instagram"
        assert PLATFORM_DOMAIN_MAP["t.me"] == "Telegram"


class TestPatterns:
    def test_otp_patterns_exist(self):
        assert "OTP" in PATTERNS
        assert len(PATTERNS["OTP"]) >= 3

    def test_other_patterns(self):
        assert "WHATSAPP_CODE" in PATTERNS
        assert "DLT_ID" in PATTERNS
        assert "SHORTCODE" in PATTERNS
        assert "CARRIER" in PATTERNS
        assert "DIGITS_ONLY" in PATTERNS
        assert "URL_BASE64" in PATTERNS


class TestHealthThresholds:
    def test_thresholds_ordered(self):
        # Should be ordered by max_h ascending
        hours = [h for h, _ in HEALTH_THRESHOLDS]
        assert hours == sorted(hours)

    def test_last_is_infinity(self):
        assert HEALTH_THRESHOLDS[-1][0] == float('inf')
        assert HEALTH_THRESHOLDS[-1][1] == 1


class TestWSChanceThresholds:
    def test_thresholds_ordered(self):
        hours = [h for h, _ in WS_CHANCE_THRESHOLDS]
        assert hours == sorted(hours)


class TestDefaults:
    def test_key_defaults(self):
        assert DEFAULTS["POLL_INTERVAL"] == 3
        assert DEFAULTS["SOUND_ENABLED"] is True
        assert DEFAULTS["OWNER_USERNAME"] == "operator"
        assert DEFAULTS["OWNER_RANK"] == "S-RANK HUNTER"


class TestCacheKeys:
    def test_all_keys_defined(self):
        expected_keys = [
            "FIREBASES", "TELEGRAM_ACCOUNTS", "TARGET_ACCOUNTS",
            "USER_LEASES", "WORKING_PROXIES", "ACTIVITY_FEED",
            "OWNER_PROFILE", "OWNER_SETTINGS", "HUNTING_ENABLED"
        ]
        for key in expected_keys:
            assert key in CACHE_KEYS