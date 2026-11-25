"""
Tests for validation utilities.
"""
import pytest
from utils.validation import (
    validate_phone,
    validate_otp,
    validate_url,
    validate_email,
    validate_username,
    validate_platform,
    validate_service_filter,
    validate_poll_interval,
    validate_positive_int,
    sanitize_html,
    sanitize_input,
    ValidationError,
)


class TestValidatePhone:
    def test_valid_indian_number(self):
        assert validate_phone("+919876543210") == "+919876543210"

    def test_valid_us_number(self):
        assert validate_phone("+15551234567") == "+15551234567"

    def test_missing_plus_raises(self):
        with pytest.raises(ValidationError, match="must start with"):
            validate_phone("919876543210")

    def test_empty_raises(self):
        with pytest.raises(ValidationError, match="required"):
            validate_phone("")

    def test_none_raises(self):
        with pytest.raises(ValidationError, match="required"):
            validate_phone(None)  # type: ignore

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError, match="Invalid phone number"):
            validate_phone("+123")


class TestValidateOTP:
    def test_valid_4_digit(self):
        assert validate_otp("1234") == "1234"

    def test_valid_6_digit(self):
        assert validate_otp("123456") == "123456"

    def test_valid_8_digit(self):
        assert validate_otp("12345678") == "12345678"

    def test_too_short_raises(self):
        with pytest.raises(ValidationError, match="4-8 digits"):
            validate_otp("123")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError, match="4-8 digits"):
            validate_otp("123456789")

    def test_non_digits_raises(self):
        with pytest.raises(ValidationError, match="4-8 digits"):
            validate_otp("12ab")


class TestValidateURL:
    def test_valid_https(self):
        assert validate_url("https://example.com") == "https://example.com"

    def test_valid_http(self):
        assert validate_url("http://example.com") == "http://example.com"

    def test_adds_https_when_missing(self):
        assert validate_url("example.com") == "https://example.com"

    def test_with_path(self):
        assert validate_url("https://example.com/path") == "https://example.com/path"

    def test_with_port(self):
        assert validate_url("https://example.com:8080") == "https://example.com:8080"

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError, match="Invalid URL"):
            validate_url("not a url")

    def test_domain_restriction(self):
        assert validate_url("https://allowed.com", ["allowed.com"]) == "https://allowed.com"

    def test_domain_restriction_blocks(self):
        with pytest.raises(ValidationError, match="not allowed"):
            validate_url("https://blocked.com", ["allowed.com"])

    def test_subdomain_allowed(self):
        assert validate_url("https://api.allowed.com", ["allowed.com"]) == "https://api.allowed.com"


class TestValidateEmail:
    def test_valid_email(self):
        assert validate_email("test@example.com") == "test@example.com"

    def test_normalizes_case(self):
        assert validate_email("TEST@EXAMPLE.COM") == "test@example.com"

    def test_invalid_raises(self):
        with pytest.raises(ValidationError, match="Invalid email"):
            validate_email("not-an-email")

    def test_missing_at_raises(self):
        with pytest.raises(ValidationError, match="Invalid email"):
            validate_email("testexample.com")


class TestValidateUsername:
    def test_valid_username(self):
        assert validate_username("user123") == "user123"

    def test_with_underscore(self):
        assert validate_username("user_name") == "user_name"

    def test_with_hyphen(self):
        assert validate_username("user-name") == "user-name"

    def test_too_short_raises(self):
        with pytest.raises(ValidationError, match="3-30"):
            validate_username("ab")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError, match="3-30"):
            validate_username("a" * 31)

    def test_invalid_chars_raises(self):
        with pytest.raises(ValidationError, match="alphanumeric"):
            validate_username("user@name")


class TestValidatePlatform:
    def test_valid_paypal(self):
        assert validate_platform("paypal") == "PayPal"

    def test_valid_facebook(self):
        assert validate_platform("facebook") == "Facebook"

    def test_valid_instagram(self):
        assert validate_platform("instagram") == "Instagram"

    def test_case_insensitive(self):
        assert validate_platform("PAYPAL") == "PayPal"

    def test_invalid_raises(self):
        with pytest.raises(ValidationError, match="Unsupported platform"):
            validate_platform("myspace")


class TestValidateServiceFilter:
    def test_whatsapp(self):
        assert validate_service_filter("whatsapp") == "whatsapp"

    def test_telegram(self):
        assert validate_service_filter("telegram") == "telegram"

    def test_any(self):
        assert validate_service_filter("any") == "any"

    def test_invalid_raises(self):
        with pytest.raises(ValidationError, match="Invalid service filter"):
            validate_service_filter("invalid")


class TestValidatePollInterval:
    def test_valid_default(self):
        assert validate_poll_interval(3) == 3

    def test_valid_min(self):
        assert validate_poll_interval(1) == 1

    def test_valid_max(self):
        assert validate_poll_interval(30) == 30

    def test_below_min_raises(self):
        with pytest.raises(ValidationError, match="1 and 30"):
            validate_poll_interval(0)

    def test_above_max_raises(self):
        with pytest.raises(ValidationError, match="1 and 30"):
            validate_poll_interval(31)

    def test_string_input(self):
        assert validate_poll_interval("5") == 5

    def test_invalid_string_raises(self):
        with pytest.raises(ValidationError, match="integer"):
            validate_poll_interval("abc")


class TestValidatePositiveInt:
    def test_valid(self):
        assert validate_positive_int(42) == 42

    def test_string_input(self):
        assert validate_positive_int("100") == 100

    def test_zero_raises(self):
        with pytest.raises(ValidationError, match="positive"):
            validate_positive_int(0)

    def test_negative_raises(self):
        with pytest.raises(ValidationError, match="positive"):
            validate_positive_int(-1)

    def test_above_max_raises(self):
        with pytest.raises(ValidationError, match="1000"):
            validate_positive_int(2000, max_val=1000)

    def test_custom_name(self):
        with pytest.raises(ValidationError, match="custom_field must be positive"):
            validate_positive_int(-5, name="custom_field")


class TestSanitizeHTML:
    def test_escapes_html(self):
        assert sanitize_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_escapes_quotes(self):
        assert sanitize_html('"quoted"') == "&quot;quoted&quot;"

    def test_handles_none(self):
        assert sanitize_html(None) == "None"

    def test_handles_int(self):
        assert sanitize_html(42) == "42"


class TestSanitizeInput:
    def test_strips_whitespace(self):
        assert sanitize_input("  hello  ") == "hello"

    def test_limits_length(self):
        long_text = "a" * 2000
        assert len(sanitize_input(long_text, max_length=100)) == 100

    def test_escapes_html(self):
        assert sanitize_input("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"

    def test_default_max_length(self):
        long_text = "a" * 2000
        assert len(sanitize_input(long_text)) == 1000