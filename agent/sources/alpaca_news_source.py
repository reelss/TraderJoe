"""Alpaca News source (Benzinga newswire) — factual catalysts, high weight.

Pulls the most recent market-wide news, tallies which tickers the headlines are
about, and scores headline sentiment with VADER. Uses the Alpaca keys we already
have — no extra credential.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

from .base import TickerSignal
from ..config import CREDS, SOURCES


class AlpacaNewsSource:
    name = "alpaca_news"
    weight = SOURCES.weight_alpaca_news

    def __init__(self) -> None:
        self.client = NewsClient(CREDS.alpaca_key, CREDS.alpaca_secret)
        self.vader = SentimentIntensityAnalyzer()

    @staticmethod
    def _items(news_set) -> list:
        # alpaca-py wraps results; support both shapes defensively.
        data = getattr(news_set, "data", None)
        if isinstance(data, dict) and "news" in data:
            return data["news"]
        return getattr(news_set, "news", []) or []

    def discover(self) -> list[TickerSignal]:
        start = datetime.now(timezone.utc) - timedelta(hours=SOURCES.news_lookback_hours)
        req = NewsRequest(
            start=start,
            limit=SOURCES.news_limit,
            sort="desc",
            exclude_contentless=True,
        )
        items = self._items(self.client.get_news(req))

        mentions: dict[str, int] = defaultdict(int)
        sent_sum: dict[str, float] = defaultdict(float)
        samples: dict[str, list[str]] = defaultdict(list)

        for art in items:
            headline = getattr(art, "headline", "") or ""
            summary = getattr(art, "summary", "") or ""
            score = self.vader.polarity_scores(f"{headline}. {summary}")["compound"]
            for sym in (getattr(art, "symbols", None) or []):
                sym = sym.upper()
                # Skip crypto pairs / non-equity tickers.
                if not sym.isalpha() or len(sym) > 5:
                    continue
                mentions[sym] += 1
                sent_sum[sym] += score
                if len(samples[sym]) < 2:
                    samples[sym].append(f"[news] {headline[:120]}")

        return [
            TickerSignal(symbol=sym, source=self.name, weight=self.weight,
                         mentions=count, sentiment=sent_sum[sym] / count,
                         samples=samples[sym])
            for sym, count in mentions.items()
        ]
