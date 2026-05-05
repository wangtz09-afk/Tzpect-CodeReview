"""Rate limiter using token bucket algorithm."""
import time
import threading
from typing import Optional


class TokenBucket:
    """Token bucket rate limiter.

    Args:
        rate: Tokens added per second.
        capacity: Maximum tokens that can accumulate.

    Example:
        limiter = TokenBucket(rate=1.0, capacity=3)  # 3 burst, then 1/sec
        limiter.acquire()  # Blocks until token available
    """

    def __init__(self, rate: float = 2.0, capacity: int = 5):
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def acquire(self, tokens: int = 1, timeout: Optional[float] = 60.0) -> bool:
        """Acquire tokens. Returns True if acquired, False if timeout."""
        deadline = time.monotonic() + (timeout or 60.0)

        while True:
            with self._lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

            if time.monotonic() >= deadline:
                return False

            time.sleep(0.1)

    def wait(self, tokens: int = 1) -> None:
        """Wait until tokens are available (blocks indefinitely)."""
        while not self.acquire(tokens, timeout=10.0):
            pass


class RateLimiter:
    """Combined rate limiter for API calls.

    Tracks both call rate and token consumption rate.
    """

    def __init__(
        self,
        calls_per_second: float = 1.0,
        burst_capacity: int = 3,
        tokens_per_second: float = 500.0,
        token_capacity: int = 2000,
    ):
        self.call_limiter = TokenBucket(calls_per_second, burst_capacity)
        self.token_limiter = TokenBucket(tokens_per_second, token_capacity)

    def acquire_call(self) -> None:
        """Wait until a call can be made."""
        self.call_limiter.wait()

    def consume_tokens(self, tokens: int) -> None:
        """Consume tokens from the token budget."""
        self.token_limiter.wait()
