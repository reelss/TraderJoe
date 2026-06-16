"""Economic calendar — upcoming high-impact macro events.

Fetches Fed, CPI, NFP, and other market-moving US events from Finnhub's
economic calendar. Surfaced in the hourly regime block so Joe can factor
in scheduled macro risk before opening new positions.

Requires FINNHUB_API_KEY. Returns [] silently on any failure — free-tier
keys may not include this endpoint, and a missing calendar never blocks a cycle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import requests

from .config import CREDS

_TIMEOUT = 5

# Substrings that identify genuinely market-moving US events.
_KEYWORDS = frozenset({
    "federal", "fed funds", "fomc", "cpi", "consumer price",
    "nonfarm", "non-farm", "payroll", "gdp", "pce", "ppi",
    "unemployment", "retail sales", "interest rate", "treasury",
    "jobs", "inflation",
})


@lru_cache(maxsize=1)
def upcoming_macro_events(days_ahead: int = 5) -> list[dict]:
    """High-impact US economic events in the next N days.

    Returns list of dicts: {event, date, days_until}.
    Each call within a process lifetime is free (lru_cache).
    """
    if not CREDS.finnhub_key:
        return []
    try:
        now = datetime.now(timezone.utc)
        from_date = now.date().isoformat()
        to_date = (now + timedelta(days=days_ahead)).date().isoformat()
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": from_date, "to": to_date, "token": CREDS.finnhub_key},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return []
        events = r.json().get("economicCalendar", [])
        out = []
        for e in events:
            if e.get("country") != "US":
                continue
            if e.get("impact") not in ("high", "medium"):
                continue
            name = (e.get("event") or "").lower()
            if not any(kw in name for kw in _KEYWORDS):
                continue
            try:
                ev_time_str = e.get("time") or ""
                if not ev_time_str:
                    continue
                ev_time = datetime.fromisoformat(ev_time_str.replace("Z", "+00:00"))
                days_until = (ev_time.date() - now.date()).days
                if days_until < 0:
                    continue
                out.append({
                    "event": e.get("event"),
                    "date": ev_time.date().isoformat(),
                    "days_until": days_until,
                    "impact": e.get("impact", "medium"),
                })
            except (KeyError, ValueError):
                continue
        out.sort(key=lambda x: x["days_until"])
        return out
    except Exception:
        return []
