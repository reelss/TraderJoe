"""Normalized signal type + cross-source aggregation."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..config import SOURCES


@dataclass
class TickerSignal:
    """One source's read on one ticker."""
    symbol: str
    source: str
    weight: float                     # source reliability weight
    mentions: int = 0                 # attention volume from this source
    sentiment: float = 0.0            # -1 (bearish) .. +1 (bullish)
    samples: list[str] = field(default_factory=list)  # headlines / titles


def aggregate(signals: list[TickerSignal]) -> list[dict]:
    """Merge per-ticker across sources, weighting by source reliability.

    Returns ranked list of dicts:
      {symbol, weighted_mentions, sentiment, total_mentions,
       sources: {name: {mentions, sentiment}}, samples: [...] }
    """
    by_sym: dict[str, list[TickerSignal]] = defaultdict(list)
    for s in signals:
        if s.symbol:
            by_sym[s.symbol].append(s)

    out: list[dict] = []
    for sym, sigs in by_sym.items():
        weighted_mentions = sum(s.mentions * s.weight for s in sigs)
        # Sentiment weighted by each source's (mentions * reliability).
        denom = sum(s.mentions * s.weight for s in sigs) or 1.0
        sentiment = sum(s.sentiment * s.mentions * s.weight for s in sigs) / denom
        samples: list[str] = []
        for s in sigs:
            samples.extend(s.samples)
        out.append({
            "symbol": sym,
            "weighted_mentions": round(weighted_mentions, 2),
            "total_mentions": sum(s.mentions for s in sigs),
            "sentiment": round(sentiment, 3),
            "source_count": len({s.source for s in sigs}),
            "sources": {s.source: {"mentions": s.mentions,
                                   "sentiment": round(s.sentiment, 3)} for s in sigs},
            "samples": samples[:4],
        })

    out = [o for o in out if o["weighted_mentions"] >= SOURCES.min_weighted_mentions]
    # Rank by weighted attention, then by how many independent sources agree.
    out.sort(key=lambda o: (o["weighted_mentions"], o["source_count"]), reverse=True)
    return out
