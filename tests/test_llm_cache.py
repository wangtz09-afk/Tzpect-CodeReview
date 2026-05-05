"""Tests for utils.llm module - cache and retry logic."""
import json
import os
import tempfile
import time
import pytest
from utils.llm import PromptCache, LLMResponse, CacheStats


class TestPromptCache:
    def test_cache_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PromptCache(cache_dir=tmpdir)
            cache.save("system", "user", "model", 0.3, 100, LLMResponse(content="test", model="model", tokens_used=10))
            result = cache.get("system", "user", "model", 0.3, 100)
            assert result is not None
            assert result.content == "test"
            assert result.cached is True

    def test_cache_miss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PromptCache(cache_dir=tmpdir)
            result = cache.get("system", "user", "model", 0.3, 100)
            assert result is None
            assert cache.stats.misses == 1

    def test_cache_miss_different_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PromptCache(cache_dir=tmpdir)
            cache.save("system", "user1", "model", 0.3, 100, LLMResponse(content="test", model="model"))
            result = cache.get("system", "user2", "model", 0.3, 100)
            assert result is None

    def test_cache_miss_different_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PromptCache(cache_dir=tmpdir)
            cache.save("system", "user", "model1", 0.3, 100, LLMResponse(content="test", model="model1"))
            result = cache.get("system", "user", "model2", 0.3, 100)
            assert result is None

    def test_cache_doesnt_save_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PromptCache(cache_dir=tmpdir)
            cache.save("system", "user", "model", 0.3, 100, LLMResponse(content="", model="model", success=False, error="test"))
            result = cache.get("system", "user", "model", 0.3, 100)
            assert result is None

    def test_cache_ttl_expiration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set TTL to 1 second
            cache = PromptCache(cache_dir=tmpdir, ttl_seconds=1)
            cache.save("system", "user", "model", 0.3, 100, LLMResponse(content="test", model="model"))

            # Should be cached
            result = cache.get("system", "user", "model", 0.3, 100)
            assert result is not None

            # Wait for TTL to expire
            time.sleep(1.1)
            result = cache.get("system", "user", "model", 0.3, 100)
            assert result is None

    def test_cache_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PromptCache(cache_dir=tmpdir)
            cache.save("system", "user", "model", 0.3, 100, LLMResponse(content="test", model="model"))
            cache.save("system2", "user2", "model", 0.3, 100, LLMResponse(content="test2", model="model"))
            count = cache.clear()
            assert count == 2

    def test_cache_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PromptCache(cache_dir=tmpdir)
            cache.get("system", "user", "model", 0.3, 100)  # miss
            cache.save("system", "user", "model", 0.3, 100, LLMResponse(content="test", model="model"))
            cache.get("system", "user", "model", 0.3, 100)  # hit
            summary = cache.get_summary()
            assert "hits" in summary
            assert "misses" in summary

    def test_corrupted_cache_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PromptCache(cache_dir=tmpdir)
            # Write invalid JSON
            cache_file = os.path.join(tmpdir, "test.json")
            with open(cache_file, "w") as f:
                f.write("not valid json{{{")

            result = cache.get("system", "user", "model", 0.3, 100)
            assert result is None

    def test_cache_hit_rate(self):
        stats = CacheStats(hits=8, misses=2)
        assert stats.hit_rate == 0.8

        stats = CacheStats(hits=0, misses=0)
        assert stats.hit_rate == 0.0
