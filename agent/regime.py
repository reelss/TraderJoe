"""Market regime filter — Joe only opens new longs in a healthy market.

Two independent signals:
1. SPY vs. 200-day SMA — the trend filter. Risk-off if the broad market is
   below its long-term average (avoids bear markets).
2. VIX level — the fear filter. Elevated fear compresses sizing; extreme fear
   blocks new entries regardless of the trend.

   VIX tiers:
     < 20  calm      — normal sizing, no restriction
     20-25 elevated  — reduce new position size by ~50%
     > 25  fear      — no new longs (too much uncertainty, wide swings)

Combined: risk_on requires BOTH SPY above 200-day SMA AND VIX < 25.
"""
from __future__ import annotations

import requests

from .config import CREDS, STRATEGY

_VIX_TIMEOUT = 4


def _fetch_vix(broker) -> float | None:
    """Pull latest VIX close. Returns None on any error.

    Sources tried in order:
    1. Stooq.com free CSV endpoint (^VIX, no auth, most reliable).
    2. CBOE CDN CSV (authoritative but slightly slower).
    Both are best-effort — a failed VIX fetch never blocks a cycle.
    """
    # Source 1: stooq.com — returns CSV with Date,Open,High,Low,Close,Volume
    try:
        r = requests.get(
            "https://stooq.com/q/d/l/?s=^vix&i=d",
            timeout=_VIX_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200 and r.text.strip():
            lines = [l for l in r.text.strip().splitlines() if l and not l.startswith("Date")]
            if lines:
                last = lines[-1].split(",")  # Date,Open,High,Low,Close,Volume
                if len(last) >= 5:
                    return float(last[4])  # Close
    except Exception:
        pass

    # Source 2: CBOE CDN
    try:
        r = requests.get(
            "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
            timeout=_VIX_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200 and r.text.strip():
            lines = [l for l in r.text.strip().splitlines() if l and not l.startswith("DATE")]
            if lines:
                last = lines[-1].split(",")  # DATE,OPEN,HIGH,LOW,CLOSE
                if len(last) >= 5:
                    return float(last[4])
    except Exception:
        pass

    return None


def _vix_tier(vix: float | None) -> str:
    """Returns 'calm', 'elevated', or 'fear'."""
    if vix is None:
        return "unknown"
    if vix < 20:
        return "calm"
    if vix < 25:
        return "elevated"
    return "fear"


def market_regime(broker) -> dict:
    """Returns regime dict consumed by cycle.py and the brain.

    Keys: symbol, regime, risk_on, price, sma, sma_window,
          vix, vix_tier, size_multiplier
    """
    sym = STRATEGY.regime_symbol
    bars = broker.daily_bars([sym], lookback_days=STRATEGY.bars_lookback_days)
    df = bars.get(sym)

    # SPY regime
    golden_cross: bool | None = None
    if df is None or len(df) < STRATEGY.regime_sma:
        spy_risk_on = True  # not enough history — don't block
        price, sma = None, None
    else:
        close = df["close"]
        price = float(close.iloc[-1])
        sma = float(close.rolling(STRATEGY.regime_sma).mean().iloc[-1])
        spy_risk_on = price > sma
        # Golden cross: 50d SMA above 200d SMA — a leading bullish confirmation.
        if len(df) >= 50:
            sma50 = float(close.rolling(50).mean().iloc[-1])
            golden_cross = sma50 > sma

    # VIX regime
    vix = _fetch_vix(broker)
    tier = _vix_tier(vix)
    vix_risk_on = tier != "fear"  # fear blocks new longs

    # Combined: both must be green to open new positions
    risk_on = spy_risk_on and vix_risk_on

    # Size multiplier passed to the brain as guidance (not hard-enforced here)
    size_mult = {"calm": 1.0, "elevated": 0.5, "fear": 0.0, "unknown": 1.0}[tier]

    regime_str = "risk_on" if risk_on else "risk_off"
    if not spy_risk_on:
        regime_str = "risk_off_spy"
    elif not vix_risk_on:
        regime_str = "risk_off_vix"

    return {
        "symbol": sym,
        "regime": regime_str,
        "risk_on": risk_on,
        "price": round(price, 2) if price else None,
        "sma": round(sma, 2) if sma else None,
        "sma_window": STRATEGY.regime_sma,
        "golden_cross": golden_cross,  # SPY 50d > 200d = intermediate trend bullish
        "vix": round(vix, 1) if vix else None,
        "vix_tier": tier,
        "size_multiplier": size_mult,
    }


# ---------------------------------------------------------------------------
# Macro context — used by nightly reflection and weekly strategy review
# ---------------------------------------------------------------------------

_INDICES = ["SPY", "QQQ", "IWM"]

_SECTORS = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLV", "Health Care"),
    ("XLY", "Consumer Disc."),
    ("XLP", "Consumer Staples"),
    ("XLE", "Energy"),
    ("XLI", "Industrials"),
    ("XLC", "Communication"),
    ("XLRE", "Real Estate"),
    ("XLU", "Utilities"),
    ("XLB", "Materials"),
]


def macro_context(broker) -> dict:
    """Fetch a broad market snapshot for use in reflection and weekly review.

    Returns indices (SPY/QQQ/IWM) with 1d/5d returns and SMA status, VIX
    level and 5-day change, and sector ETF returns ranked best-to-worst.
    Best-effort — partial data is returned on any individual failure.
    """
    all_syms = _INDICES + [s for s, _ in _SECTORS]
    bars = broker.daily_bars(all_syms, lookback_days=300)  # ~215 trading days, enough for 200d SMA

    def _returns(df) -> dict:
        if df is None or len(df) < 6:
            return {}
        close = df["close"]
        last = float(close.iloc[-1])
        ret_1d = float(close.iloc[-1] / close.iloc[-2] - 1) if len(df) >= 2 else None
        ret_5d = float(close.iloc[-1] / close.iloc[-6] - 1) if len(df) >= 6 else None
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else None
        return {
            "price": round(last, 2),
            "ret_1d": round(ret_1d, 4) if ret_1d is not None else None,
            "ret_5d": round(ret_5d, 4) if ret_5d is not None else None,
            "above_200sma": (last > sma200) if sma200 else None,
        }

    indices = {sym: _returns(bars.get(sym)) for sym in _INDICES}

    sector_rows = []
    for etf, name in _SECTORS:
        r = _returns(bars.get(etf))
        if r:
            sector_rows.append({"etf": etf, "name": name, **r})
    sector_rows.sort(key=lambda x: x.get("ret_5d") or 0, reverse=True)

    leaders = [s["name"] for s in sector_rows[:3]] if sector_rows else []
    laggards = [s["name"] for s in reversed(sector_rows[-3:])] if sector_rows else []

    # Market breadth: % of sector ETFs above their 200d SMA.
    # A simple but meaningful proxy — when < 40% of sectors are above 200d,
    # the broad market is deteriorating even if SPY itself hasn't crossed down yet.
    sectors_with_sma = [s for s in sector_rows if s.get("above_200sma") is not None]
    sectors_above_200 = sum(1 for s in sectors_with_sma if s["above_200sma"])
    sector_breadth_pct = (round(sectors_above_200 / len(sectors_with_sma), 2)
                          if sectors_with_sma else None)
    if sector_breadth_pct is not None:
        if sector_breadth_pct >= 0.70:
            breadth_tier = "expanding"
        elif sector_breadth_pct >= 0.45:
            breadth_tier = "neutral"
        else:
            breadth_tier = "contracting"
    else:
        breadth_tier = "unknown"

    # VIX 5-day change
    vix_now = _fetch_vix(broker)
    vix_5d_change = None
    vix_df = bars.get("VIX")  # likely None from Alpaca, but try
    if vix_df is not None and len(vix_df) >= 6:
        vix_5d_change = round(float(vix_df["close"].iloc[-1]) - float(vix_df["close"].iloc[-6]), 2)

    return {
        "date": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat(),
        "indices": indices,
        "vix": {"current": round(vix_now, 1) if vix_now else None,
                "tier": _vix_tier(vix_now),
                "change_5d": vix_5d_change},
        "sectors": sector_rows,
        "sector_leaders": leaders,
        "sector_laggards": laggards,
        "market_breadth": {
            "sectors_above_200sma": sectors_above_200,
            "sectors_total": len(sectors_with_sma),
            "breadth_pct": sector_breadth_pct,
            "breadth_tier": breadth_tier,
        },
    }
