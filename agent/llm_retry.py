"""Tiny retry helper for Anthropic calls — handles transient 429 rate limits.

Pure: no logging or Slack side effects. The caller decides what to do when
retries are exhausted (the last RateLimitError is re-raised).
"""
from __future__ import annotations

import time

from anthropic import RateLimitError


def create_with_retry(client, *, max_retries: int = 4, base_delay: float = 2.0, **kwargs):
    """Call client.messages.create(**kwargs), retrying on 429 with backoff.

    On RateLimitError, sleeps base_delay * 2**attempt and retries up to
    max_retries times. After the last attempt fails, re-raises the error.
    """
    last_exc: RateLimitError | None = None
    for attempt in range(max_retries + 1):
        try:
            return client.messages.create(**kwargs)
        except RateLimitError as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            time.sleep(base_delay * (2 ** attempt))
    assert last_exc is not None
    raise last_exc
