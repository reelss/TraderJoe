"""Offline test of the multi-source aggregation (no keys / network needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.sources.base import TickerSignal, aggregate

# NVDA: real news catalyst (high weight) + StockTwits bullish + a little reddit.
# GME : pure reddit hype, single source, bearish-ish.
signals = [
    TickerSignal("NVDA", "alpaca_news", 1.5, mentions=3, sentiment=0.6, samples=["[news] NVDA beats"]),
    TickerSignal("NVDA", "stocktwits", 1.0, mentions=8, sentiment=0.4, samples=["[stocktwits] bull"]),
    TickerSignal("NVDA", "reddit", 0.6, mentions=5, sentiment=0.2, samples=["[r/wsb] calls"]),
    TickerSignal("GME", "reddit", 0.6, mentions=12, sentiment=-0.1, samples=["[r/wsb] hold"]),
    TickerSignal("ABC", "reddit", 0.6, mentions=1, sentiment=0.9),  # below floor -> dropped
]

ranked = aggregate(signals)
for r in ranked:
    print(f"{r['symbol']:5} wmentions={r['weighted_mentions']:6} "
          f"sent={r['sentiment']:+.2f} sources={r['source_count']} "
          f"({','.join(r['sources'])})")

syms = [r["symbol"] for r in ranked]
assert syms[0] == "NVDA", "multi-source corroborated name should rank first"
assert "ABC" not in syms, "below-floor single mention should be dropped"
nvda = ranked[0]
# weighted mentions = 3*1.5 + 8*1.0 + 5*0.6 = 4.5+8+3 = 15.5
assert nvda["weighted_mentions"] == 15.5, nvda["weighted_mentions"]
assert nvda["source_count"] == 3
print("AGGREGATION OK")
