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
    if SOURCES.enable_stocktwits:
        from .stocktwits_source import StockTwitsSource
        sources.append(StockTwitsSource())
    if SOURCES.enable_reddit and CREDS.has_reddit():
        from .reddit_source import RedditSource
        sources.append(RedditSource())
    return sources


def scan_all() -> list[dict]:
    """Aggregated, ranked ticker signals across all enabled sources."""
    all_signals: list[TickerSignal] = []
    for src in _enabled_sources():
        try:
            sigs = src.discover()
            all_signals.extend(sigs)
            log.info(f"source[{src.name}]: {len(sigs)} ticker signals")
        except Exception as exc:
            log.info(f"source[{src.name}] FAILED: {exc!r}")
    return aggregate(all_signals)


__all__ = ["TickerSignal", "aggregate", "scan_all"]
