"""
Tests for OTP scanner.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from core.scanner import (
    check_device,
    send_otp_to_user,
    start_scanner,
    whatsapp_scanner,
    backup_scanner,
)
import constants as C


class TestCheckDevice:
    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def mock_firebase(self):
        with patch('core.scanner.get_firebase') as mock_get:
            mock_firebase = AsyncMock()
            mock_get.return_value = mock_firebase
            yield mock_firebase

    @pytest.mark.asyncio
    async def test_check_device_no_messages(self, mock_bot, mock_firebase):
        mock_firebase.fetch_messages.return_value = {}

        result = await check_device(
            mock_bot, "https://fb.url", "auth", "dev123",
            [123], 0, "9876543210", "any"
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_check_device_new_otp(self, mock_bot, mock_firebase):
        mock_firebase.fetch_messages.return_value = {
            "1": {"id": "1", "type": "incoming", "message": "Your OTP is 123456", "sender": "WHATSAPP"}
        }
        mock_firebase.extract_otp.return_value = "123456"
        mock_firebase.extract_service_name.return_value = "WhatsApp"

        with patch('core.scanner.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.push_activity = MagicMock()
            mock_db.transaction = MagicMock()
            mock_get_db.return_value = mock_db

            # Mock the transaction context manager
            async def mock_transaction():
                yield {"users": {"123": {}}, "telegram_accounts": {}}
            mock_db.transaction = mock_transaction

            result = await check_device(
                mock_bot, "https://fb.url", "auth", "dev123",
                [123], 0, "9876543210", "any"
            )
            assert result == 1

    @pytest.mark.asyncio
    async def test_check_device_service_filter_whatsapp(self, mock_bot, mock_firebase):
        # Message without whatsapp keyword should be filtered
        mock_firebase.fetch_messages.return_value = {
            "1": {"id": "1", "type": "incoming", "message": "Your OTP is 123456", "sender": "TELEGRAM"}
        }
        mock_firebase.extract_otp.return_value = "123456"

        result = await check_device(
            mock_bot, "https://fb.url", "auth", "dev123",
            [123], 0, "9876543210", "whatsapp"
        )
        # Should not process non-whatsapp messages
        assert result == 0  # last_msg_id unchanged

    @pytest.mark.asyncio
    async def test_check_device_whatsapp_code_format(self, mock_bot, mock_firebase):
        # WhatsApp code format: "code: 123-456"
        mock_firebase.fetch_messages.return_value = {
            "1": {"id": "1", "type": "incoming", "message": "Your code: 123-456", "sender": "WHATSAPP"}
        }
        mock_firebase.extract_otp.return_value = "123456"
        mock_firebase.extract_service_name.return_value = "WhatsApp"

        with patch('core.scanner.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.push_activity = MagicMock()
            mock_get_db.return_value = mock_db

            result = await check_device(
                mock_bot, "https://fb.url", "auth", "dev123",
                [123], 0, "9876543210", "whatsapp"
            )
            assert result == 1


class TestSendOTPToUser:
    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.mark.asyncio
    async def test_send_otp_to_user(self, mock_bot):
        with patch('core.scanner.get_db') as mock_get_db:
            mock_db = AsyncMock()
            async def mock_transaction():
                yield {"users": {"123": {}}, "telegram_accounts": {}}
            mock_db.transaction = mock_transaction
            mock_get_db.return_value = mock_db

            with patch('core.scanner._push_otp_to_account') as mock_push:
                mock_push.return_value = None

                await send_otp_to_user(
                    mock_bot, 123, "WhatsApp", "123456",
                    "Your WhatsApp code is 123456", "dev123", "9876543210"
                )

                mock_bot.send_message.assert_called_once()
                call_args = mock_bot.send_message.call_args
                assert call_args[1]['parse_mode'] == 'HTML'
                assert '123456' in call_args[1]['text']


class TestStartScanner:
    @pytest.mark.asyncio
    async def test_start_scanner_no_leases(self):
        with patch('core.scanner.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.load.return_value = {"user_leases": {}, "firebases": []}
            mock_get_db.return_value = mock_db

            # Run for a short time
            import asyncio
            task = asyncio.create_task(start_scanner(None))
            await asyncio.sleep(0.1)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            mock_db.load.assert_called()


class TestWhatsAppScanner:
    @pytest.mark.asyncio
    async def test_whatsapp_scanner_no_firebases(self):
        with patch('core.scanner.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.load.return_value = {"firebases": []}
            mock_db.transaction = AsyncMock()
            mock_get_db.return_value = mock_db

            import asyncio
            task = asyncio.create_task(whatsapp_scanner(None))
            await asyncio.sleep(0.1)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass


class TestBackupScanner:
    @pytest.mark.asyncio
    async def test_backup_scanner_no_firebases(self):
        with patch('core.scanner.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.load.return_value = {
                "firebases": [],
                "device_backups": {},
                "upcoming_timers": {}
            }
            mock_get_db.return_value = mock_db

            import asyncio
            task = asyncio.create_task(backup_scanner(None))
            await asyncio.sleep(0.1)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_backup_scanner_timer_alerts(self):
        with patch('core.scanner.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.load.return_value = {
                "firebases": [],
                "device_backups": {},
                "upcoming_timers": {
                    "timer1": {
                        "user_id": 123,
                        "number": "9876543210",
                        "target_time": 9999999999,  # Far future
                        "alert_5m": False,
                        "alert_2m": False,
                        "alert_now": False
                    }
                }
            }
            mock_db.save = AsyncMock()
            mock_get_db.return_value = mock_db

            import asyncio
            task = asyncio.create_task(backup_scanner(None))
            await asyncio.sleep(0.1)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass