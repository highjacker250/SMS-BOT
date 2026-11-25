"""
Retry utilities with exponential backoff for external service calls.
"""
import asyncio
import logging
import random
from typing import Callable, TypeVar, Optional, Tuple, Type
from functools import wraps

log = logging.getLogger("Retry")

T = TypeVar("T")


class RetryError(Exception):
    """Raised when all retry attempts are exhausted."""
    def __init__(self, message: str, last_exception: Exception, attempts: int):
        super().__init__(message)
        self.last_exception = last_exception
        self.attempts = attempts


class RetryPolicy:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
        should_retry: Optional[Callable[[Exception], bool]] = None,
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions
        self.should_retry = should_retry or (lambda e: True)

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and optional jitter."""
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        if self.jitter:
            delay *= (0.5 + random.random())  # 50-150% of calculated delay
        return delay


# Pre-defined policies for common scenarios
POLICIES = {
    "firebase": RetryPolicy(
        max_attempts=3,
        base_delay=1.0,
        max_delay=10.0,
        exponential_base=2.0,
        retryable_exceptions=(TimeoutError, ConnectionError, OSError),
    ),
    "ai_api": RetryPolicy(
        max_attempts=3,
        base_delay=2.0,
        max_delay=30.0,
        exponential_base=2.0,
        retryable_exceptions=(TimeoutError, ConnectionError, OSError),
    ),
    "proxy_check": RetryPolicy(
        max_attempts=2,
        base_delay=0.5,
        max_delay=3.0,
        exponential_base=2.0,
        retryable_exceptions=(TimeoutError, ConnectionError, OSError),
    ),
    "telegram": RetryPolicy(
        max_attempts=3,
        base_delay=1.0,
        max_delay=15.0,
        exponential_base=2.0,
        retryable_exceptions=(TimeoutError, ConnectionError, OSError),
    ),
    "browser": RetryPolicy(
        max_attempts=2,
        base_delay=3.0,
        max_delay=30.0,
        exponential_base=2.0,
        retryable_exceptions=(TimeoutError, ConnectionError, OSError),
    ),
    "database": RetryPolicy(
        max_attempts=3,
        base_delay=0.5,
        max_delay=5.0,
        exponential_base=2.0,
        retryable_exceptions=(TimeoutError, ConnectionError, OSError),
    ),
}


async def retry_async(
    func: Callable[..., T],
    *args,
    policy: Optional[RetryPolicy] = None,
    policy_name: Optional[str] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
    **kwargs
) -> T:
    """
    Execute an async function with retry logic.
    """
    if policy is None:
        policy = POLICIES.get(policy_name, RetryPolicy())

    last_exception = None

    for attempt in range(policy.max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # Check if exception type matches retryable exceptions
            if not isinstance(e, policy.retryable_exceptions):
                raise e

            # Check if custom filter allows retry
            if not policy.should_retry(e):
                raise e

            last_exception = e

            if attempt < policy.max_attempts - 1:
                delay = policy.calculate_delay(attempt)
                log.warning(
                    f"Attempt {attempt + 1}/{policy.max_attempts} failed for {func.__name__}: {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                if on_retry:
                    on_retry(e, attempt + 1)
                await asyncio.sleep(delay)
            else:
                # Max retries reached, re-raise the last exception
                log.error(
                    f"All {policy.max_attempts} attempts failed for {func.__name__}: {e}"
                )
                raise e

    raise RetryError(
        f"Failed after {policy.max_attempts} attempts: {last_exception}",
        last_exception,
        policy.max_attempts
    )


def with_retry(
    policy: Optional[RetryPolicy] = None,
    policy_name: Optional[str] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Decorator to add retry logic to an async function.

    Usage:
        @with_retry(policy_name="firebase")
        async def fetch_data(url: str) -> dict:
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await retry_async(
                func, *args,
                policy=policy,
                policy_name=policy_name,
                on_retry=on_retry,
                **kwargs
            )
        return wrapper
    return decorator


# Convenience decorators for common policies
retry_firebase = lambda f: with_retry(policy_name="firebase")(f)
retry_ai_api = lambda f: with_retry(policy_name="ai_api")(f)
retry_proxy = lambda f: with_retry(policy_name="proxy_check")(f)
retry_telegram = lambda f: with_retry(policy_name="telegram")(f)
retry_browser = lambda f: with_retry(policy_name="browser")(f)
retry_database = lambda f: with_retry(policy_name="database")(f)