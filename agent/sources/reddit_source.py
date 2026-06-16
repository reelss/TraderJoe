"""Reddit source — crowd buzz across trading subreddits (noisy, low weight)."""
from __future__ import annotations

import re
from collections import defaultdict

import praw
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .base import TickerSignal
from ..config import CREDS, SOCIAL, SOURCES

_CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
_BARE = re.compile(r"\b([A-Z]{2,5})\b")

_STOP = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER", "WAS",
    "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HOW", "MAN", "NEW", "NOW",
    "OLD", "SEE", "TWO", "WHO", "BOY", "DID", "ITS", "LET", "PUT", "SAY", "SHE",
    "TOO", "USE", "CEO", "CFO", "IPO", "ATH", "DD", "YOLO", "FD", "WSB", "USD",
    "ETF", "USA", "GDP", "FED", "SEC", "EPS", "PE", "AI", "EV", "IMO", "TLDR",
    "EOD", "AH", "PM", "ER", "FOMO", "HODL", "LOL", "WTF", "TA",
}


class RedditSource:
    name = "reddit"
    weight = SOURCES.weight_reddit

    def __init__(self) -> None:
        self.reddit = praw.Reddit(
            client_id=CREDS.reddit_client_id,
            client_secret=CREDS.reddit_client_secret,
            user_agent=CREDS.reddit_user_agent,
        )
        self.reddit.read_only = True
        self.vader = SentimentIntensityAnalyzer()

    def _extract(self, text: str) -> set[str]:
        found = {m.group(1).upper() for m in _CASHTAG.finditer(text)}
        for m in _BARE.finditer(text):
            if m.group(1) not in _STOP:
                found.add(m.group(1))
        return found

    def discover(self) -> list[TickerSignal]:
        mentions: dict[str, int] = defaultdict(int)
        sent_sum: dict[str, float] = defaultdict(float)
        samples: dict[str, list[str]] = defaultdict(list)

        for sub in SOCIAL.subreddits:
            try:
                for post in self.reddit.subreddit(sub).hot(limit=SOCIAL.posts_per_sub):
                    text = f"{post.title} {getattr(post, 'selftext', '')}"
                    score = self.vader.polarity_scores(post.title)["compound"]
                    for sym in self._extract(text):
                        mentions[sym] += 1
                        sent_sum[sym] += score
                        if len(samples[sym]) < 2:
                            samples[sym].append(f"[r/{sub}] {post.title[:120]}")
            except Exception:
                continue

        out = []
        for sym, count in mentions.items():
            if count < SOCIAL.min_mentions:
                continue
            out.append(TickerSignal(
                symbol=sym, source=self.name, weight=self.weight,
                mentions=count, sentiment=sent_sum[sym] / count,
                samples=samples[sym],
            ))
        return out
