"""
Tests for Firebase service.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.firebase import (
    FirebaseService,
    FirebaseConfig,
    FirebaseError,
    FirebaseTimeoutError,
    FirebaseNotFoundError,
)


class TestFirebaseConfig:
    def test_default_config(self):
        cfg = FirebaseConfig()
        assert cfg.default_timeout == 10
        assert cfg.long_timeout == 20
        assert cfg.max_concurrent == 5

    def test_custom_config(self):
        cfg = FirebaseConfig(default_timeout=15, max_concurrent=10)
        assert cfg.default_timeout == 15
        assert cfg.max_concurrent == 10


class TestFirebaseService:
    @pytest.fixture
    def firebase_service(self):
        """Create a FirebaseService with mocked aiohttp session."""
        with patch('services.firebase.aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            service = FirebaseService()
            service._session = mock_session
            yield service, mock_session

    @pytest.mark.asyncio
    async def test_fetch_success(self, firebase_service):
        service, mock_session = firebase_service
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value='{"key": "value"}')
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        result = await service.fetch("https://example.firebaseio.com/test.json")
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_fetch_null_returns_empty(self, firebase_service):
        service, mock_session = firebase_service
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="null")
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        result = await service.fetch("https://example.firebaseio.com/test.json")
        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_404_raises_not_found(self, firebase_service):
        service, mock_session = firebase_service
        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        with pytest.raises(FirebaseNotFoundError):
            await service.fetch("https://example.firebaseio.com/test.json")

    @pytest.mark.asyncio
    async def test_fetch_500_raises_error(self, firebase_service):
        service, mock_session = firebase_service
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        with pytest.raises(FirebaseError, match="HTTP 500"):
            await service.fetch("https://example.firebaseio.com/test.json")

    @pytest.mark.asyncio
    async def test_fetch_timeout_raises_timeout_error(self, firebase_service):
        service, mock_session = firebase_service
        import asyncio
        mock_session.get.side_effect = asyncio.TimeoutError()

        with pytest.raises(FirebaseTimeoutError):
            await service.fetch("https://example.firebaseio.com/test.json", timeout=1)

    @pytest.mark.asyncio
    async def test_check_ping_success(self, firebase_service):
        service, mock_session = firebase_service
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        result = await service.check_ping("https://example.firebaseio.com")
        assert result.endswith("ms")

    @pytest.mark.asyncio
    async def test_check_ping_timeout(self, firebase_service):
        service, mock_session = firebase_service
        import asyncio
        mock_session.get.side_effect = asyncio.TimeoutError()

        result = await service.check_ping("https://example.firebaseio.com")
        assert result == "❌ Timeout"


class TestFirebaseExtractors:
    @pytest.fixture
    def service(self):
        return FirebaseService()

    def test_clean_mobile_valid_indian(self, service):
        assert service.clean_mobile("9876543210") == "9876543210"
        assert service.clean_mobile("+919876543210") == "9876543210"
        assert service.clean_mobile("09876543210") == "9876543210"

    def test_clean_mobile_invalid(self, service):
        assert service.clean_mobile("12345") is None
        assert service.clean_mobile("abcdefghij") is None
        assert service.clean_mobile("unknown") is None
        assert service.clean_mobile("") is None
        assert service.clean_mobile(None) is None

    def test_is_service_sender(self, service):
        assert service.is_service_sender("12345") is True  # shortcode
        assert service.is_service_sender("AB-CD-E") is True  # DLT
        assert service.is_service_sender("AB-CDEFG") is True  # alnum
        assert service.is_service_sender("9876543210") is False  # regular number
        assert service.is_service_sender("") is True

    def test_extract_otp(self, service):
        assert service.extract_otp("Your OTP is 123456") == "123456"
        assert service.extract_otp("OTP: 7890") == "7890"
        assert service.extract_otp("Code is 1234") == "1234"
        assert service.extract_otp("123456 is your verification code") == "123456"
        assert service.extract_otp("No OTP here") is None
        assert service.extract_otp("") is None
        assert service.extract_otp(None) is None

    def test_extract_service_name(self, service):
        assert service.extract_service_name("WhatsApp code: 123456", "") == "WhatsApp"
        assert service.extract_service_name("Telegram login code", "") == "Telegram"
        assert service.extract_service_name("Amazon OTP", "") == "Amazon"
        assert service.extract_service_name("Random text", "SENDER-FACEBOOK") == "FACEBOOK"
        assert service.extract_service_name("Unknown", "") == "Unknown"

    def test_calculate_health_no_msgs(self, service):
        assert service.calculate_health([]) == 1
        assert service.calculate_health(None) == 1

    def test_calculate_health_recent(self, service):
        # Recent message (id > 10^12 treated as timestamp)
        msgs = [{"id": str(int(1_000_000_000_000))}]
        # Should return 10 for < 1 hour
        health = service.calculate_health(msgs)
        assert 1 <= health <= 10

    def test_get_ws_chance(self, service):
        # No WhatsApp messages
        assert service.get_ws_chance([]) == 97

    def test_extract_best_numbers_from_dev_data(self, service):
        dev_data = {"mobNo": "9876543210"}
        result = service.extract_best_numbers(dev_data, [])
        assert len(result) == 1
        assert result[0][0] == "9876543210"
        assert result[0][1] == 100

    def test_extract_best_numbers_from_sims(self, service):
        dev_data = {"sims": [{"phoneNumber": "9876543210"}]}
        result = service.extract_best_numbers(dev_data, [])
        assert len(result) == 1
        assert result[0][0] == "9876543210"

    def test_get_ist_time_str(self, service):
        # Test with a known timestamp
        ts = 1704067200  # 2024-01-01 00:00:00 UTC
        result = service.get_ist_time_str(ts)
        assert "Jan" in result or "01" in result
        assert "2024" in result

    def test_decode_panel_url_base64(self, service):
        import base64
        # Create a simple encoded URL
        original = "https://example.firebaseio.com|||secretkey"
        encoded = base64.b64encode(original.encode()).decode()
        url = f"https://panel.com/?data={encoded}"

        result = service.decode_panel_url(url)
        assert result is not None
        assert result[0] == "https://example.firebaseio.com"
        assert result[1] == "secretkey"