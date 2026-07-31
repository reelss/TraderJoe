"""Pluggable signal sources for Joe's ticker discovery.

Each source yields normalized TickerSignal objects. `scan_all()` runs every
enabled source, tolerates individual failures, and returns one aggregated,
reliability-weighted view per ticker for the brain.
"""
from __future__ import annotations

from .base import TickerSignal, aggregate
from .. import logbook as log
from ..config import CREDS, SOURCES


def _enabled_sources() -> list:
    sources = []
    if SOURCES.enable_alpaca_news:
        from .alpaca_news_source import AlpacaNewsSource
        sources.append(AlpacaNewsSource())
    if SOURCES.enable_finnhub and CREDS.finnhub_key:
        from .finnhub_source import FinnhubSource
        sources.append(FinnhubSource())
    if SOURCES.enable_sector_rs:
        from .sector_rs import SectorRSSource
        sources.append(SectorRSSource())
    if SOURCES.enable_watchlist:
        from .watchlist import WatchlistSource
        sources.append(WatchlistSource())
    if SOURCES.enable_stocktwits:
        from .stocktwits_source import StockTwitsSource
        sources.append(StockTwitsSource())
    if SOURCES.enable_reddit and CREDS.has_reddit():
        from .reddit_source import RedditSource
        sources.append(RedditSource())
    return sources


def scan_all(broker=None) -> list[dict]:
    """Aggregated, ranked ticker signals across all enabled sources.

    broker: optional shared Broker from the cycle. Sources that need market
    bars (currently sector_rs) reuse it instead of opening their own client and
    re-fetching the same data. Sources that don't take a broker ignore it.
    """
    all_signals: list[TickerSignal] = []
    for src in _enabled_sources():
        try:
            # Only sector_rs consumes a broker today; pass it where accepted.
            if broker is not None and src.name == "sector_rs":
                sigs = src.discover(broker=broker)
            else:
                sigs = src.discover()
            all_signals.extend(sigs)
            log.info(f"source[{src.name}]: {len(sigs)} ticker signals")
        except Exception as exc:
            log.info(f"source[{src.name}] FAILED: {exc!r}")
    return aggregate(all_signals)


__all__ = ["TickerSignal", "aggregate", "scan_all"]
