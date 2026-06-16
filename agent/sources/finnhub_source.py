"""Finnhub source (optional) — a second independent newswire.

Activates only when FINNHUB_API_KEY is set. Uses the free general market-news
endpoint and tallies symbol mentions with VADER sentiment, giving Joe a second,
independent news signal to corroborate (or contradict) Benzinga.
"""
from __future__ import annotations

from collections import defaultdict

import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .base import TickerSignal
from ..config import CREDS, SOURCES

_NEWS = "https://finnhub.io/api/v1/news"
_TIMEOUT = 8


class FinnhubSource:
    name = "finnhub"
    weight = SOURCES.weight_finnhub

    def __init__(self) -> None:
        self.vader = SentimentIntensityAnalyzer()

    def discover(self) -> list[TickerSignal]:
        try:
            r = requests.get(_NEWS, params={"category": "general",
                                            "token": CREDS.finnhub_key},
                             timeout=_TIMEOUT)
            if r.status_code != 200:
                return []
            articles = r.json()
        except (requests.RequestException, ValueError):
            return []

        mentions: dict[str, int] = defaultdict(int)
        sent_sum: dict[str, float] = defaultdict(float)
        samples: dict[str, list[str]] = defaultdict(list)

        for art in articles[: SOURCES.news_limit]:
            headline = art.get("headline", "") or ""
            summary = art.get("summary", "") or ""
            related = art.get("related", "") or ""
            if not related:
                continue
            score = self.vader.polarity_scores(f"{headline}. {summary}")["compound"]
            for sym in related.split(","):
                sym = sym.strip().upper()
                if not sym.isalpha() or len(sym) > 5:
                    continue
                mentions[sym] += 1
                sent_sum[sym] += score
                if len(samples[sym]) < 2:
                    samples[sym].append(f"[finnhub] {headline[:120]}")

        return [
            TickerSignal(symbol=sym, source=self.name, weight=self.weight,
                         mentions=count, sentiment=sent_sum[sym] / count,
                         samples=samples[sym])
            for sym, count in mentions.items()
        ]
