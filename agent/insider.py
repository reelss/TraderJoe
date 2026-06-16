"""Insider transaction signal — SEC Form 4 open-market purchases via Finnhub.

CEO/CFO/director buying in the open market is one of the clearest signals in
the market: they're putting personal capital in at current prices with full
knowledge of the business. Selling is ambiguous (diversification, tax); buying
is directional.

Only "P" (open market purchase) transactions count — not grants, exercises,
or gifts. The signal is meaningful at $25k+ in aggregate purchases within 30 days.

Requires FINNHUB_API_KEY. Returns {} silently on any failure — never blocks a cycle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from .config import CREDS

_TIMEOUT = 5
_WINDOW_DAYS = 30
_MIN_BUY_VALUE = 25_000  # ignore trivial purchases


def insider_signal(symbols: list[str]) -> dict[str, dict]:
    """Recent insider open-market buying activity per symbol.

    Returns {symbol: {net_buying, buy_value, n_buyers, days_since_last_buy}}.
    Symbols with no meaningful recent buying return {net_buying: False}.
    """
    if not CREDS.finnhub_key or not symbols:
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)).date().isoformat()
    result: dict[str, dict] = {}
    for sym in symbols:
        try:
            r = requests.get(
                "https://finnhub.io/api/v1/stock/insider-transactions",
                params={"symbol": sym, "token": CREDS.finnhub_key},
                timeout=_TIMEOUT,
            )
            if r.status_code != 200:
                continue
            txns = r.json().get("data", [])
            buy_value = 0.0
            buyers: set[str] = set()
            last_buy_date: str | None = None
            for t in txns:
                date_str = t.get("transactionDate", "")
                if not date_str or date_str < cutoff:
                    continue
                # Only open-market purchases ("P") — the directional signal.
                if (t.get("transactionCode") or "").upper() != "P":
                    continue
                shares = abs(float(t.get("share") or 0))
                price = abs(float(t.get("transactionPrice") or 0))
                value = shares * price
                if value < _MIN_BUY_VALUE:
                    continue
                buy_value += value
                name = t.get("name", "")
                if name:
                    buyers.add(name)
                if last_buy_date is None or date_str > last_buy_date:
                    last_buy_date = date_str
            days_since: int | None = None
            if last_buy_date:
                try:
                    d = datetime.strptime(last_buy_date, "%Y-%m-%d").date()
                    days_since = (datetime.now(timezone.utc).date() - d).days
                except ValueError:
                    pass
            result[sym] = {
                "net_buying": buy_value >= _MIN_BUY_VALUE,
                "buy_value": round(buy_value, 0),
                "n_buyers": len(buyers),
                "days_since_last_buy": days_since,
            }
        except Exception:
            pass
    return result
