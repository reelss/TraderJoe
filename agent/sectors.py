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


def sector_exposure(positions: list[dict], equity: float | None = None) -> dict:
    """Calculate sector concentration as a fraction of TOTAL ACCOUNT EQUITY.

    Using equity (not just invested capital) as the denominator is critical:
    measuring concentration against invested-only made 3 positions in 3 sectors
    each read as 33%+ "concentrated" purely because most of the account was cash,
    self-locking deployment. Against equity, 3 positions at ~10% each read as
    ~10% per sector — correctly leaving room to add.

    Args:
        positions: list of position dicts from broker.positions()
                   Each must have 'symbol' and 'market_value'.
        equity: total account equity. If None, falls back to total invested
                (legacy behavior) — callers concerned with concentration should
                always pass equity.

    Returns:
        {
          "by_sector": {"Technology": 0.10, "Financials": 0.08, ...},  # of equity
          "by_symbol": {"ORCL": "Technology", "JPM": "Financials", ...},
          "concentrated": ["Technology"],   # sectors >= 30% of equity
          "total_invested": 1234.56,
          "denominator": "equity" | "invested",
        }
    """
    if not positions:
        return {
            "by_sector": {}, "by_symbol": {},
            "concentrated": [], "total_invested": 0.0,
            "denominator": "equity" if equity else "invested",
        }

    total_invested = sum(abs(p.get("market_value", 0)) for p in positions)
    denom = equity if (equity and equity > 0) else total_invested
    if denom == 0:
        return {
            "by_sector": {}, "by_symbol": {},
            "concentrated": [], "total_invested": 0.0,
            "denominator": "equity" if equity else "invested",
        }

    by_symbol: dict[str, str] = {}
    sector_totals: dict[str, float] = {}

    for p in positions:
        sym = p["symbol"]
        sector = _fetch_sector(sym)
        by_symbol[sym] = sector
        # "Unknown" = lookup failure / unmapped symbol, not a real sector.
        # Multiple unrelated "Unknown" names summed together can falsely trip
        # the 30% cap and block diversifying buys, so they don't count toward
        # any sector's concentration total.
        if sector == "Unknown":
            continue
        sector_totals[sector] = sector_totals.get(sector, 0.0) + abs(p.get("market_value", 0))

    by_sector = {
        s: round(v / denom, 4)
        for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])
    }
    concentrated = [s for s, pct in by_sector.items() if pct >= 0.30]

    return {
        "by_sector": by_sector,
        "by_symbol": by_symbol,
        "concentrated": concentrated,
        "total_invested": round(total_invested, 2),
        "denominator": "equity" if (equity and equity > 0) else "invested",
    }


def sector_of(symbol: str) -> str:
    """Public accessor for a single symbol's sector (cached)."""
    return _fetch_sector(symbol.upper())


def would_exceed_sector_cap(symbol: str, add_value: float,
                            positions: list[dict], equity: float,
                            cap: float = 0.30) -> bool:
    """True if adding `add_value` of `symbol` would push its sector over `cap`
    fraction of equity. Used as a hard buy gate in risk.vet_orders.

    Pending buys queued earlier in the same cycle should be reflected by passing
    them in `positions` (with 'symbol' and 'market_value') so the cap accounts
    for cumulative same-cycle exposure.
    """
    if not equity or equity <= 0:
        return False
    sector = _fetch_sector(symbol.upper())
    # Can't measure an unmapped/failed-lookup sector — don't block a buy against
    # a cap it can't be assessed against (a lookup timeout shouldn't be a veto).
    if sector == "Unknown":
        return False
    current = sum(abs(p.get("market_value", 0)) for p in positions
                  if _fetch_sector(p["symbol"].upper()) == sector)
    return (current + add_value) / equity > cap
