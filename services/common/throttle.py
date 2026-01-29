"""
Simple process-wide throttler for external API calls.
"""

import os
import random
import threading
import time

_lock = threading.Lock()
_last_call = 0.0


def throttle(_key: str, min_seconds: float = 0.5, max_seconds: float = 1.0) -> None:
    """
    Enforce a minimum delay between calls (global, process-wide).
    """
    if os.getenv("THROTTLE_DISABLED") == "1":
        return
    delay = random.uniform(min_seconds, max_seconds)
    now = time.monotonic()
    with _lock:
        global _last_call
        wait_for = (_last_call + delay) - now
        if wait_for > 0:
            time.sleep(wait_for)
            now = time.monotonic()
        _last_call = now


def backoff(_key: str = "backoff", min_seconds: float = 30.0, max_seconds: float = 60.0) -> None:
    throttle(_key, min_seconds, max_seconds)
