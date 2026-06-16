"""Sector concentration — prevents Joe from stacking correlated bets.

Uses Finnhub's stock profile endpoint (free tier, no extra auth beyond the
existing FINNHUB_API_KEY) to look up the sector/industry for each symbol.
Results are cached per process so repeated calls within a cycle are free.

Joe uses this to:
  1. Know what sector each holding belongs to.
  2. See total equity % allocated per sector across all open positions.
  3. Avoid adding a new position if its sector is already at >= 30% of equity.
"""
from __future__ import annotations

from functools import lru_cache

import requests

from .config import CREDS

_TIMEOUT = 4

# Lightweight fallback map for ETFs and well-known names that Finnhub
# may not classify with a useful industry tag.
_KNOWN = {
    "SPY": "Broad Market ETF",
    "QQQ": "Tech ETF",
    "VIX": "Volatility Index",
    "SOXX": "Semiconductor ETF",
    "IGV": "Software ETF",
    "XLF": "Financial ETF",
    "XLK": "Tech ETF",
    "XLE": "Energy ETF",
    "XLV": "Healthcare ETF",
    "GLD": "Commodity ETF",
    "TLT": "Bond ETF",
}


@lru_cache(maxsize=256)
def _fetch_sector(symbol: str) -> str:
    """Return the Finnhub industry string for a symbol, or 'Unknown'."""
    if symbol in _KNOWN:
        return _KNOWN[symbol]
    if not CREDS.finnhub_key:
        return "Unknown"
    try:
        url = (
            f"https://finnhub.io/api/v1/stock/profile2"
            f"?symbol={symbol}&token={CREDS.finnhub_key}"
        )
        r = requests.get(url, timeout=_TIMEOUT)
        if r.status_code != 200:
            return "Unknown"
        data = r.json()
        return data.get("finnhubIndustry") or "Unknown"
    except Exception:
        return "Unknown"


def sector_exposure(positions: list[dict]) -> dict:
    """Calculate sector concentration across all open positions.

    Args:
        positions: list of position dicts from broker.positions()
                   Each must have 'symbol' and 'market_value'.

    Returns:
        {
          "by_sector": {"Technology": 0.35, "Financials": 0.12, ...},
          "by_symbol": {"ORCL": "Technology", "JPM": "Financials", ...},
          "concentrated": ["Technology"],   # sectors >= 30% of invested equity
          "total_invested": 1234.56,
        }
    """
    if not positions:
        return {
            "by_sector": {}, "by_symbol": {},
            "concentrated": [], "total_invested": 0.0,
        }

    total_invested = sum(abs(p.get("market_value", 0)) for p in positions)
    if total_invested == 0:
        return {
            "by_sector": {}, "by_symbol": {},
            "concentrated": [], "total_invested": 0.0,
        }

    by_symbol: dict[str, str] = {}
    sector_totals: dict[str, float] = {}

    for p in positions:
        sym = p["symbol"]
        sector = _fetch_sector(sym)
        by_symbol[sym] = sector
        sector_totals[sector] = sector_totals.get(sector, 0.0) + abs(p.get("market_value", 0))

    by_sector = {
        s: round(v / total_invested, 4)
        for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])
    }
    concentrated = [s for s, pct in by_sector.items() if pct >= 0.30]

    return {
        "by_sector": by_sector,
        "by_symbol": by_symbol,
        "concentrated": concentrated,
        "total_invested": round(total_invested, 2),
    }
