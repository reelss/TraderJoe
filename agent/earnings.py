"""Earnings calendar — fetches upcoming earnings dates via Finnhub.

One API call fetches the full earnings calendar for the next 14 days, then
symbol lookups are pure dict access. Falls back gracefully to None on any
network/parse error — never breaks a cycle. Requires FINNHUB_API_KEY in .env
(same key already used by the Finnhub news source).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import requests

from .config import CREDS

_TIMEOUT = 6  # seconds for the single calendar fetch


@lru_cache(maxsize=1)
def _fetch_calendar() -> dict[str, int]:
    """Fetch Finnhub earnings calendar for today + 14 days.

    Returns {symbol: days_to_earnings}. Cached for the process lifetime
    (one Task Scheduler run = one cycle), so all symbol lookups are free
    after the first call.
    """
    if not CREDS.finnhub_key:
        return {}
    try:
        now = datetime.now(timezone.utc)
        from_date = now.date().isoformat()
        to_date = (now + timedelta(days=14)).date().isoformat()
        url = (
            f"https://finnhub.io/api/v1/calendar/earnings"
            f"?from={from_date}&to={to_date}&token={CREDS.finnhub_key}"
        )
        r = requests.get(url, timeout=_TIMEOUT)
        if r.status_code != 200:
            return {}
        data = r.json()
        calendar: dict[str, int] = {}
        today = now.date()
        for item in data.get("earningsCalendar", []):
            sym = item.get("symbol", "")
            date_str = item.get("date", "")
            if not sym or not date_str:
                continue
            try:
                earnings_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                days = (earnings_date - today).days
                # Keep the nearest upcoming earnings if duplicates exist
                if sym not in calendar or days < calendar[sym]:
                    calendar[sym] = days
            except ValueError:
                continue
        return calendar
    except Exception:
        return {}


def earnings_context(symbols: list[str]) -> dict[str, dict]:
    """Return earnings metadata for a list of symbols.

    Result: {symbol: {"days_to_earnings": int|None, "earnings_soon": bool}}

    "earnings_soon" = earnings within 5 calendar days (including today).
    Joe uses this to avoid entering new positions into binary events.
    """
    calendar = _fetch_calendar()
    result: dict[str, dict] = {}
    for sym in symbols:
        days = calendar.get(sym)  # None if not in the 14-day window
        result[sym] = {
            "days_to_earnings": days,
            "earnings_soon": (days is not None and 0 <= days <= 5),
        }
    return result
