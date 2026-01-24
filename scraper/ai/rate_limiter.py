"""
Rate limiter for Groq API calls
Conservative limits: 15 RPM (50% of free tier), 14.4k RPD, 6k TPM, 500k TPD
Note: Limits are conservative to work with both 8b-instant and 70b-versatile models
"""

import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Optional


class GroqRateLimiter:
    """
    Thread-safe rate limiter for Groq API

    Limits:
    - 30 requests per minute (RPM)
    - 14,400 requests per day (RPD)
    - 6,000 tokens per minute (TPM)
    - 500,000 tokens per day (TPD)
    """

    def __init__(self):
        self.lock = threading.Lock()

        # Request tracking (sliding window)
        self.request_times = deque()  # Timestamps of recent requests
        self.daily_requests = 0
        self.daily_reset_time = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        # Token tracking (sliding window)
        self.token_times = deque()  # (timestamp, token_count) pairs
        self.daily_tokens = 0

        # Limits (conservative: 50% of free tier to be extra safe)
        self.rpm_limit = 15  # Reduced from 30 to 15 (50% of free tier)
        self.rpd_limit = 14400
        self.tpm_limit = 6000
        self.tpd_limit = 500000

        # Safety margin (use 90% of limits to avoid hitting them)
        self.rpm_limit_safe = int(self.rpm_limit * 0.9)  # ~13 RPM (conservative)
        self.rpd_limit_safe = int(self.rpd_limit * 0.9)  # 12,960 RPD
        self.tpm_limit_safe = int(self.tpm_limit * 0.9)  # 5,400 TPM
        self.tpd_limit_safe = int(self.tpd_limit * 0.9)  # 450,000 TPD

    def _clean_old_requests(self):
        """Remove requests older than 1 minute"""
        now = time.time()
        while self.request_times and now - self.request_times[0] > 60:
            self.request_times.popleft()

    def _clean_old_tokens(self):
        """Remove token counts older than 1 minute"""
        now = time.time()
        while self.token_times and now - self.token_times[0][0] > 60:
            self.token_times.popleft()

    def _reset_daily_counters(self):
        """Reset daily counters if new day"""
        now = datetime.now()
        if now >= self.daily_reset_time:
            self.daily_requests = 0
            self.daily_tokens = 0
            self.daily_reset_time = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)

    def can_make_request(
        self, estimated_tokens: int = 500
    ) -> tuple[bool, Optional[str]]:
        """
        Check if we can make a request without exceeding limits

        Args:
            estimated_tokens: Estimated tokens for this request (input + output)

        Returns:
            (can_proceed, reason_if_not)
        """
        with self.lock:
            self._reset_daily_counters()
            self._clean_old_requests()
            self._clean_old_tokens()

            # Check daily request limit
            if self.daily_requests >= self.rpd_limit_safe:
                return (
                    False,
                    f"Daily request limit reached ({self.daily_requests}/{self.rpd_limit_safe})",
                )

            # Check daily token limit
            if self.daily_tokens + estimated_tokens > self.tpd_limit_safe:
                return (
                    False,
                    f"Daily token limit would be exceeded ({self.daily_tokens + estimated_tokens}/{self.tpd_limit_safe})",
                )

            # Check requests per minute
            if len(self.request_times) >= self.rpm_limit_safe:
                return (
                    False,
                    f"Rate limit: {len(self.request_times)}/{self.rpm_limit_safe} requests in last minute",
                )

            # Check tokens per minute
            minute_tokens = sum(tokens for _, tokens in self.token_times)
            if minute_tokens + estimated_tokens > self.tpm_limit_safe:
                return (
                    False,
                    f"Token limit: {minute_tokens + estimated_tokens}/{self.tpm_limit_safe} tokens in last minute",
                )

            return True, None

    def wait_if_needed(self, estimated_tokens: int = 500) -> float:
        """
        Wait if necessary to stay within rate limits

        Returns:
            seconds waited
        """
        wait_time = 0.0

        with self.lock:
            self._reset_daily_counters()
            self._clean_old_requests()
            self._clean_old_tokens()

            # Wait for RPM limit
            if len(self.request_times) >= self.rpm_limit_safe:
                oldest_request = self.request_times[0]
                wait_seconds = (
                    60 - (time.time() - oldest_request) + 1
                )  # +1 for safety margin
                if wait_seconds > 0:
                    wait_time = max(wait_time, wait_seconds)

            # Wait for TPM limit
            minute_tokens = sum(tokens for _, tokens in self.token_times)
            if minute_tokens + estimated_tokens > self.tpm_limit_safe:
                # Calculate how long to wait for oldest tokens to expire
                if self.token_times:
                    oldest_token_time = self.token_times[0][0]
                    wait_seconds = 60 - (time.time() - oldest_token_time) + 1
                    if wait_seconds > 0:
                        wait_time = max(wait_time, wait_seconds)

        if wait_time > 0:
            time.sleep(wait_time)

        return wait_time

    def record_request(self, actual_tokens: int):
        """
        Record that a request was made

        Args:
            actual_tokens: Actual tokens used (input + output)
        """
        with self.lock:
            now = time.time()
            self.request_times.append(now)
            self.token_times.append((now, actual_tokens))
            self.daily_requests += 1
            self.daily_tokens += actual_tokens

    def get_status(self) -> dict:
        """Get current rate limit status"""
        with self.lock:
            self._reset_daily_counters()
            self._clean_old_requests()
            self._clean_old_tokens()

            minute_tokens = sum(tokens for _, tokens in self.token_times)

            return {
                "requests_last_minute": len(self.request_times),
                "requests_today": self.daily_requests,
                "tokens_last_minute": minute_tokens,
                "tokens_today": self.daily_tokens,
                "rpm_limit": self.rpm_limit_safe,
                "rpd_limit": self.rpd_limit_safe,
                "tpm_limit": self.tpm_limit_safe,
                "tpd_limit": self.tpd_limit_safe,
                "rpm_remaining": self.rpm_limit_safe - len(self.request_times),
                "rpd_remaining": self.rpd_limit_safe - self.daily_requests,
                "tpm_remaining": self.tpm_limit_safe - minute_tokens,
                "tpd_remaining": self.tpd_limit_safe - self.daily_tokens,
            }


# Global rate limiter instance
_rate_limiter = None


def get_rate_limiter() -> GroqRateLimiter:
    """Get or create global rate limiter instance"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = GroqRateLimiter()
    return _rate_limiter
