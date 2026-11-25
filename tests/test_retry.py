"""
Tests for retry utilities.
"""
import asyncio
import pytest
from utils.retry import (
    retry_async,
    RetryPolicy,
    RetryError,
    POLICIES,
    with_retry,
)


class TestRetryPolicy:
    def test_default_policy(self):
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.base_delay == 1.0
        assert policy.max_delay == 60.0
        assert policy.exponential_base == 2.0
        assert policy.jitter is True

    def test_custom_policy(self):
        policy = RetryPolicy(
            max_attempts=5,
            base_delay=0.5,
            max_delay=10.0,
            exponential_base=3.0,
            jitter=False
        )
        assert policy.max_attempts == 5
        assert policy.base_delay == 0.5
        assert policy.max_delay == 10.0
        assert policy.exponential_base == 3.0
        assert policy.jitter is False

    def test_calculate_delay_no_jitter(self):
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, max_delay=100.0, jitter=False)
        assert policy.calculate_delay(0) == 1.0
        assert policy.calculate_delay(1) == 2.0
        assert policy.calculate_delay(2) == 4.0
        assert policy.calculate_delay(3) == 8.0

    def test_calculate_delay_with_jitter(self):
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, max_delay=100.0, jitter=True)
        # With jitter, delay should be between 0.5x and 1.5x of base
        for _ in range(100):
            delay = policy.calculate_delay(0)
            assert 0.5 <= delay <= 1.5

    def test_max_delay_cap(self):
        policy = RetryPolicy(base_delay=10.0, exponential_base=2.0, max_delay=15.0, jitter=False)
        assert policy.calculate_delay(0) == 10.0
        assert policy.calculate_delay(1) == 15.0  # capped
        assert policy.calculate_delay(2) == 15.0  # capped


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        call_count = 0

        async def succeed():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await retry_async(succeed, policy=RetryPolicy(max_attempts=3))
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "success"

        result = await retry_async(
            fail_twice,
            policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter=False)
        )
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_failure_after_max_attempts(self):
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        with pytest.raises(RetryError) as exc_info:
            await retry_async(
                always_fail,
                policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter=False)
            )

        assert exc_info.value.attempts == 3
        assert call_count == 3
        assert isinstance(exc_info.value.last_exception, ConnectionError)

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        call_count = 0

        async def value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        # ValueError not in default retryable_exceptions
        with pytest.raises(ValueError, match="not retryable"):
            await retry_async(
                value_error,
                policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter=False)
            )
        assert call_count == 1  # Should not retry

    @pytest.mark.asyncio
    async def test_custom_retryable_exceptions(self):
        call_count = 0

        async def value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("now retryable")

        with pytest.raises(RetryError):
            await retry_async(
                value_error,
                policy=RetryPolicy(
                    max_attempts=3,
                    base_delay=0.01,
                    jitter=False,
                    retryable_exceptions=(ValueError,)
                )
            )
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_should_retry_callback(self):
        call_count = 0

        async def fail_with_reason():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("reason")

        # Only retry if error message contains "reason"
        with pytest.raises(RetryError):
            await retry_async(
                fail_with_reason,
                policy=RetryPolicy(
                    max_attempts=3,
                    base_delay=0.01,
                    jitter=False,
                    should_retry=lambda e: "reason" in str(e)
                )
            )
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_should_retry_callback_false(self):
        call_count = 0

        async def fail_no_retry():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("no retry")

        with pytest.raises(ConnectionError):
            await retry_async(
                fail_no_retry,
                policy=RetryPolicy(
                    max_attempts=3,
                    base_delay=0.01,
                    jitter=False,
                    should_retry=lambda e: "reason" in str(e)
                )
            )
        assert call_count == 1  # Should not retry

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        retry_count = []
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "success"

        def on_retry(exc, attempt):
            retry_count.append((attempt, str(exc)))

        result = await retry_async(
            fail_twice,
            policy=RetryPolicy(
                max_attempts=3,
                base_delay=0.01,
                jitter=False,
                retryable_exceptions=(ConnectionError,)
            ),
            on_retry=on_retry
        )
        assert result == "success"
        assert len(retry_count) == 2
        assert retry_count[0][0] == 1
        assert retry_count[1][0] == 2


class TestPredefinedPolicies:
    def test_firebase_policy_exists(self):
        assert "firebase" in POLICIES
        policy = POLICIES["firebase"]
        assert policy.max_attempts == 3

    def test_ai_api_policy_exists(self):
        assert "ai_api" in POLICIES

    def test_proxy_policy_exists(self):
        assert "proxy_check" in POLICIES

    def test_telegram_policy_exists(self):
        assert "telegram" in POLICIES

    def test_browser_policy_exists(self):
        assert "browser" in POLICIES

    def test_database_policy_exists(self):
        assert "database" in POLICIES


class TestWithRetryDecorator:
    @pytest.mark.asyncio
    async def test_decorator_success(self):
        @with_retry(policy_name="firebase")
        async def succeed():
            return "ok"

        result = await succeed()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_decorator_retry(self):
        call_count = 0

        @with_retry(policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter=False))
        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "success"

        result = await fail_twice()
        assert result == "success"
        assert call_count == 3