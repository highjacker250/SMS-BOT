"""
Tests for database service.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.database import DatabaseService, DatabaseConfig, BotStatus


class TestDatabaseConfig:
    def test_default_config(self):
        cfg = DatabaseConfig()
        assert cfg.cache_ttl == 30
        assert cfg.save_throttle == 2.0
        assert cfg.max_activity_feed == 50
        assert cfg.activity_feed_throttle == 60.0

    def test_custom_config(self):
        cfg = DatabaseConfig(cache_ttl=60, save_throttle=5.0)
        assert cfg.cache_ttl == 60
        assert cfg.save_throttle == 5.0


class TestDatabaseService:
    @pytest.fixture
    def db_service(self):
        """Create a DatabaseService with mocked Supabase client."""
        with patch('services.database.create_client') as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client
            service = DatabaseService()
            service._client = mock_client
            yield service

    @pytest.fixture
    def mock_supabase_response(self):
        """Mock Supabase response."""
        mock_res = MagicMock()
        mock_res.data = [{"data": {"test": "value"}}]
        return mock_res

    def test_get_default_structure(self, db_service):
        """Test default data structure has all required keys."""
        data = db_service._get_default_structure()
        assert "owner_id" in data
        assert "users" in data
        assert "firebases" in data
        assert "telegram_accounts" in data
        assert "hunting_enabled" in data
        assert data["hunting_enabled"] is True

    def test_merge_with_defaults(self, db_service):
        """Test merging loaded data with defaults."""
        loaded = {"custom_key": "custom_value", "users": {"123": {"name": "Test"}}}
        defaults = db_service._get_default_structure()
        merged = db_service._merge_with_defaults(loaded, defaults)

        assert merged["custom_key"] == "custom_value"
        assert merged["users"]["123"]["name"] == "Test"
        assert "owner_id" in merged
        assert "firebases" in merged

    def test_bot_status_management(self, db_service):
        """Test bot status getter/setter."""
        db_service.set_bot_status("Testing", "Running tests")
        status = db_service.get_bot_status()

        assert status.task == "Testing"
        assert status.detail == "Running tests"
        assert status.last_update > 0

    def test_push_activity_throttling(self, db_service):
        """Test activity feed throttling."""
        # First push should work
        db_service.push_activity("Task 1", "Detail 1")
        state = db_service._feed_push_state
        assert state["last_task"] == "Task 1"
        assert state["last_detail"] == "Detail 1"

        # Immediate duplicate should be throttled
        db_service.push_activity("Task 1", "Detail 1")
        # State unchanged (still same timestamp essentially)
        assert state["last_task"] == "Task 1"

        # Different task should work
        db_service.push_activity("Task 2", "Detail 2")
        assert state["last_task"] == "Task 2"

    def test_invalidate_cache(self, db_service):
        """Test cache invalidation."""
        db_service._cache = {"test": "data"}
        db_service._cache_time = 1234567890
        db_service.invalidate_cache()
        assert db_service._cache is None
        assert db_service._cache_time == 0

    @pytest.mark.asyncio
    async def test_load_without_supabase(self, db_service):
        """Test load when Supabase not configured."""
        db_service._client = None
        # Mock config to not have Supabase
        with patch('services.database.config.SUPABASE_URL', ""), \
             patch('services.database.config.SUPABASE_KEY', ""):
            data = await db_service.load()
            assert "owner_id" in data
            assert data["hunting_enabled"] is True

    @pytest.mark.asyncio
    async def test_save_without_supabase(self, db_service):
        """Test save when Supabase not configured."""
        db_service._client = None
        with patch('services.database.config.SUPABASE_URL', ""), \
             patch('services.database.config.SUPABASE_KEY', ""):
            result = await db_service.save({"test": "data"})
            assert result is False  # Not saved

    @pytest.mark.asyncio
    async def test_save_throttling(self, db_service, mock_supabase_response):
        """Test save throttling."""
        mock_table = MagicMock()
        mock_table.update.return_value.eq.return_value.execute.return_value = mock_supabase_response
        db_service._client.table.return_value = mock_table

        # First save should work
        result1 = await db_service.save({"test": "data1"}, force=True)
        assert result1 is True

        # Immediate second save should be throttled
        result2 = await db_service.save({"test": "data2"})
        assert result2 is False  # Throttled

    @pytest.mark.asyncio
    async def test_flush_pending(self, db_service, mock_supabase_response):
        """Test flush_pending forces save."""
        db_service._pending_save = True
        db_service._cache = {"test": "data"}

        mock_table = MagicMock()
        mock_table.update.return_value.eq.return_value.execute.return_value = mock_supabase_response
        db_service._client.table.return_value = mock_table

        result = await db_service.flush_pending()
        assert result is True
        assert db_service._pending_save is False


class TestDatabaseTransaction:
    @pytest.mark.asyncio
    async def test_transaction_context_manager(self):
        """Test database_transaction context manager."""
        from services.database import database_transaction, get_db

        # This test requires a more complex mock setup
        # Skipping for now - would need to mock get_db() and its methods
        pass