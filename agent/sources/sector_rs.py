"""Sector relative-strength screener — a momentum-leader discovery source.

Most of Joe's discovery is news-reactive (Benzinga, Finnhub). This source is
different: it surfaces the leaders of whichever sectors are showing the strongest
relative strength vs. SPY right now, regardless of whether they're in the news.
Momentum leadership is itself a signal — "trade the leaders, not the laggards."

Each cycle it:
  1. Computes each sector's 5-day return (via a representative sector ETF) minus
     SPY's 5-day return — that's the sector's relative strength.
  2. Picks the top 2 sectors by RS.
  3. Emits the curated liquid leaders of those sectors as ticker signals,
     weight 1.2 (between Finnhub's 1.4 and a hypothetical Reddit 0.6 — these are
     momentum leaders, not news catalysts, so they corroborate rather than lead).

Self-contained like every other source: it builds its own Broker and tolerates
any data failure by returning [] so a bad cycle never crashes discovery.
"""
from __future__ import annotations

from .base import TickerSignal
from .. import logbook as log
from ..config import SOURCES

# Representative ETF per sector + that sector's curated liquid leaders.
# Two names per sector keeps the candidate count manageable while covering the
# most liquid momentum leaders in each. The ETF is used only to measure the
# sector's relative strength; the leaders are what we actually emit.
_SECTORS: dict[str, dict] = {
    "Tech/Semis":   {"etf": "XLK", "names": ["NVDA", "AMD"]},
    "Financials":   {"etf": "XLF", "names": ["JPM", "GS"]},
    "Healthcare":   {"etf": "XLV", "names": ["UNH", "LLY"]},
    "Energy":       {"etf": "XLE", "names": ["XOM", "CVX"]},
    "Industrials":  {"etf": "XLI", "names": ["CAT", "DE"]},
    "Consumer Disc":{"etf": "XLY", "names": ["AMZN", "TSLA"]},
}

_RS_WEIGHT = SOURCES.weight_sector_rs
_TOP_N_SECTORS = 2
_RS_LOOKBACK = 5  # sessions; 5-day RS is less noisy than 1-day


def _ret_n(df, n: int) -> float | None:
    """n-session return of a daily-bar DataFrame, or None if too short."""
    try:
        if df is None or len(df) < n + 1:
            return None
        close = df["close"]
        return float(close.iloc[-1] / close.iloc[-(n + 1)] - 1)
    except Exception:
        return None


class SectorRSSource:
    name = "sector_rs"
    weight = _RS_WEIGHT

    def discover(self) -> list[TickerSignal]:
        try:
            from ..broker import Broker
            broker = Broker()
        except Exception as exc:
            log.info(f"source[sector_rs]: broker init failed ({exc!r})")
            return []

        etfs = [v["etf"] for v in _SECTORS.values()]
        try:
            bars = broker.daily_bars(sorted(set(etfs) | {"SPY"}), lookback_days=30)
        except Exception as exc:
            log.info(f"source[sector_rs]: bars fetch failed ({exc!r})")
            return []

        spy_ret = _ret_n(bars.get("SPY"), _RS_LOOKBACK)
        if spy_ret is None:
            log.info("source[sector_rs]: no SPY history — skipping RS screen")
            return []

        # Rank sectors by relative strength (sector 5d return - SPY 5d return).
        rs_by_sector: list[tuple[str, float]] = []
        for sector, cfg in _SECTORS.items():
            etf_ret = _ret_n(bars.get(cfg["etf"]), _RS_LOOKBACK)
            if etf_ret is None:
                continue
            rs_by_sector.append((sector, etf_ret - spy_ret))

        if not rs_by_sector:
            return []
        rs_by_sector.sort(key=lambda x: x[1], reverse=True)
        top = [s for s, rs in rs_by_sector[:_TOP_N_SECTORS] if rs > 0]
        if not top:
            log.info("source[sector_rs]: no sector outperforming SPY this cycle")
            return []

        signals: list[TickerSignal] = []
        for sector in top:
            for sym in _SECTORS[sector]["names"]:
                # mentions=2 so weighted (2 x 1.2 = 2.4) clears the aggregator's
                # min_weighted_mentions floor (2.0) on its own — an RS leader is a
                # standalone candidate even with no news corroboration this cycle.
                signals.append(TickerSignal(
                    symbol=sym, source=self.name, weight=self.weight,
                    mentions=2, sentiment=0.0,
                    samples=[f"[sector_rs] {sector} leading SPY (5d RS)"],
                ))
        log.info(f"source[sector_rs]: leading sectors {top} -> "
                 f"{len(signals)} leader signals")
        return signals
