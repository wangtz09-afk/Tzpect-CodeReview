"""Tests for utils.rate_limiter module."""
import time
import pytest
from utils.rate_limiter import TokenBucket, RateLimiter


class TestTokenBucket:
    def test_initial_capacity(self):
        bucket = TokenBucket(rate=1.0, capacity=5)
        assert bucket.tokens == 5.0

    def test_consume_tokens(self):
        bucket = TokenBucket(rate=1.0, capacity=5)
        assert bucket.acquire(1) is True
        assert bucket.acquire(1) is True
        # Tokens should have decreased
        assert bucket.tokens <= 3.0

    def test_consume_all_tokens(self):
        bucket = TokenBucket(rate=0.1, capacity=2)
        assert bucket.acquire(2) is True
        # Should be empty now (or close to it)
        assert bucket.tokens < 0.5

    def test_timeout_when_empty(self):
        bucket = TokenBucket(rate=0.1, capacity=1)
        bucket.acquire(1)  # Use the only token
        # Should timeout quickly with short timeout
        result = bucket.acquire(1, timeout=0.5)
        assert result is False  # Not enough time to refill

    def test_refill_over_time(self):
        bucket = TokenBucket(rate=100.0, capacity=5)  # Fast refill
        bucket.acquire(5)  # Use all
        time.sleep(0.1)  # Wait for refill (should add ~10 tokens, capped at 5)
        # Should have refilled some tokens
        bucket._refill()  # Force refill to update state
        assert bucket.tokens > 0

    def test_capacity_cap(self):
        """Tokens should not exceed capacity even after long wait."""
        bucket = TokenBucket(rate=1000.0, capacity=5)
        time.sleep(0.1)  # Would add 100 tokens if uncapped
        assert bucket.tokens <= 5.0

    def test_wait_blocks(self):
        bucket = TokenBucket(rate=100.0, capacity=1)
        bucket.acquire(1)  # Use the only token
        start = time.monotonic()
        bucket.wait(1)  # Should wait for refill
        elapsed = time.monotonic() - start
        assert elapsed < 1.0  # Should be fast with high rate


class TestRateLimiter:
    def test_initialization(self):
        limiter = RateLimiter(calls_per_second=2.0, burst_capacity=5)
        assert limiter.call_limiter.capacity == 5

    def test_acquire_call(self):
        limiter = RateLimiter(calls_per_second=10.0, burst_capacity=3)
        # Should not block
        limiter.acquire_call()
        limiter.acquire_call()
        limiter.acquire_call()
