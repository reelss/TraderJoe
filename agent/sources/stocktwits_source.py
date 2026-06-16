"""StockTwits source — trending tickers with explicit user Bullish/Bearish tags.

Uses StockTwits' public endpoints (no key). These are rate-limited and can be
gated without notice, so every call is best-effort: any failure degrades to an
empty result and the rest of the pipeline carries on.
"""
from __future__ import annotations

import requests

from .base import TickerSignal
from ..config import SOURCES

_TRENDING = "https://api.stocktwits.com/api/2/trending/symbols.json"
_STREAM = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; joe-trader/0.1)"}
_TIMEOUT = 8


class StockTwitsSource:
    name = "stocktwits"
    weight = SOURCES.weight_stocktwits

    def _get(self, url: str) -> dict | None:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        return None

    def _trending_symbols(self) -> list[str]:
        data = self._get(_TRENDING)
        if not data:
            return []
        return [s["symbol"].upper() for s in data.get("symbols", [])
                if s.get("symbol", "").isalpha()][: SOURCES.stocktwits_top_n]

    def _symbol_sentiment(self, sym: str) -> tuple[int, float, list[str]]:
        """Return (message_count, bull_bear_sentiment, sample_titles)."""
        data = self._get(_STREAM.format(sym=sym))
        if not data:
            return 0, 0.0, []
        msgs = data.get("messages", [])
        bull = bear = 0
        samples: list[str] = []
        for m in msgs:
            basic = (((m.get("entities") or {}).get("sentiment")) or {}).get("basic")
            if basic == "Bullish":
                bull += 1
            elif basic == "Bearish":
                bear += 1
            if len(samples) < 2 and m.get("body"):
                samples.append(f"[stocktwits] {m['body'][:120]}")
        total_tagged = bull + bear
        sentiment = (bull - bear) / total_tagged if total_tagged else 0.0
        return len(msgs), sentiment, samples

    def discover(self) -> list[TickerSignal]:
        out: list[TickerSignal] = []
        for sym in self._trending_symbols():
            count, sentiment, samples = self._symbol_sentiment(sym)
            if count == 0:
                # Still trending even if the stream call failed — record attention.
                count = 1
            out.append(TickerSignal(
                symbol=sym, source=self.name, weight=self.weight,
                mentions=count, sentiment=sentiment, samples=samples,
            ))
        return out
