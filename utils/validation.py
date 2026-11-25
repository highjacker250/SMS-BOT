"""
Input validation and sanitization utilities.
"""
import re
import html
from typing import Optional
from urllib.parse import urlparse

import constants as C

# Pre-compiled patterns for validation
PHONE_PATTERN = re.compile(r'^\+?[1-9]\d{1,14}$')  # E.164 format
OTP_PATTERN = re.compile(r'^\d{4,8}$')
URL_PATTERN = re.compile(
    r'^https?://'  # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
    r'localhost|'  # localhost
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or ip
    r'(?::\d+)?'  # optional port
    r'(?:/?|[/?]\S+)$', re.IGNORECASE
)
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{3,30}$')


class ValidationError(ValueError):
    """Raised when validation fails."""
    pass


def validate_phone(phone: str) -> str:
    """
    Validate and normalize phone number.
    Returns normalized phone (with + prefix).
    """
    if not phone or not isinstance(phone, str):
        raise ValidationError("Phone number is required")

    phone = phone.strip()

    # Must start with +
    if not phone.startswith('+'):
        raise ValidationError("Phone number must start with + (e.g., +919876543210)")

    # Validate E.164 format and length (min 8 digits, max 15 digits)
    digits = phone[1:]
    if not digits.isdigit() or len(digits) < 7 or len(digits) > 15:
        raise ValidationError("Invalid phone number format")

    return phone


def validate_otp(otp: str) -> str:
    """Validate OTP format."""
    if not otp or not isinstance(otp, str):
        raise ValidationError("OTP is required")

    otp = otp.strip()

    if not OTP_PATTERN.match(otp):
        raise ValidationError("OTP must be 4-8 digits")

    return otp


def validate_url(url: str, allowed_domains: Optional[list[str]] = None) -> str:
    """
    Validate URL format and optionally restrict to allowed domains.
    """
    if not url or not isinstance(url, str):
        raise ValidationError("URL is required")

    url = url.strip()

    # Add https:// if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    if not URL_PATTERN.match(url):
        raise ValidationError("Invalid URL format")

    # Check allowed domains
    if allowed_domains:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not any(domain == d or domain.endswith('.' + d) for d in allowed_domains):
            raise ValidationError(f"Domain not allowed. Allowed: {', '.join(allowed_domains)}")

    return url


def validate_email(email: str) -> str:
    """Validate email format."""
    if not email or not isinstance(email, str):
        raise ValidationError("Email is required")

    email = email.strip().lower()

    if not EMAIL_PATTERN.match(email):
        raise ValidationError("Invalid email format")

    return email


def validate_username(username: str) -> str:
    """Validate username format."""
    if not username or not isinstance(username, str):
        raise ValidationError("Username is required")

    username = username.strip()

    if not USERNAME_PATTERN.match(username):
        raise ValidationError("Username must be 3-30 chars, alphanumeric, underscore, hyphen only")

    return username


def sanitize_html(text: str) -> str:
    """Escape HTML special characters."""
    if not isinstance(text, str):
        text = str(text)
    return html.escape(text)


def sanitize_input(text: str, max_length: int = 1000) -> str:
    """Sanitize user input - strip, limit length, escape HTML."""
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()[:max_length]
    return sanitize_html(text)


def validate_platform(platform: str) -> str:
    """Validate platform name."""
    if not platform or not isinstance(platform, str):
        raise ValidationError("Platform is required")

    platform_lower = platform.strip().lower()
    for p in C.SUPPORTED_PLATFORMS:
        if p.lower() == platform_lower:
            return p

    raise ValidationError(f"Unsupported platform. Supported: {', '.join(sorted(C.SUPPORTED_PLATFORMS))}")


def validate_service_filter(service: str) -> str:
    """Validate service filter value."""
    valid = {C.ServiceFilter.WHATSAPP.value, C.ServiceFilter.TELEGRAM.value, C.ServiceFilter.ANY.value}
    if service not in valid:
        raise ValidationError(f"Invalid service filter. Must be one of: {', '.join(valid)}")
    return service


def validate_poll_interval(interval: int) -> int:
    """Validate poll interval (1-30 seconds)."""
    try:
        interval = int(interval)
    except (ValueError, TypeError):
        raise ValidationError("Poll interval must be an integer")

    if interval < 1 or interval > 30:
        raise ValidationError("Poll interval must be between 1 and 30 seconds")

    return interval


def validate_positive_int(value: int, name: str = "value", max_val: int = 1000000) -> int:
    """Validate positive integer within range."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        raise ValidationError(f"{name} must be an integer")

    if value <= 0:
        raise ValidationError(f"{name} must be positive")

    if value > max_val:
        raise ValidationError(f"{name} must be <= {max_val}")

    return value