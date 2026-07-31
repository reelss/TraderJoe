"""Playbook watchlist — Joe's own priorities as a discovery source.

Joe's nightly playbook names priority tickers he wants to buy (e.g. "LLY is
Priority #1, waiting on volume"), but discovery is news-reactive — a watchlist
name that isn't in today's headlines never reaches the brain, so Joe can spend
a week wanting a stock he is never shown. This source closes that loop: the
names Joe said he wants are guaranteed a seat at the table every cycle. They
still clear every gate (universe filters, sector veto, graduated volume rule)
like any other candidate.

Parsing, in order of preference:
  1. A machine-readable line the nightly reflection emits in playbook.md:
       WATCHLIST: LLY, UNH, CAT
  2. Fallback heuristic: bolded lead tickers of bullets in the "Watchlist
     notes" section (`- **TICK`), skipping lines that read as vetoes.

Best-effort like every source: any parse failure returns [] and never blocks
a cycle.
"""
from __future__ import annotations

import re

from .base import TickerSignal
from .. import logbook as log
from ..config import PLAYBOOK_PATH, SOURCES

_MAX_NAMES = 8
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
# Fallback: "- **LLY ..." bullet leads in the Watchlist notes section.
_BULLET_RE = re.compile(r"^\s*-\s+\*\*([A-Z]{1,5})\b")
_VETO_WORDS = ("veto", "vetoed", "avoid", "remove", "do not", "skip", "banned")


def _parse_watchlist_line(text: str) -> list[str]:
    m = re.search(r"^WATCHLIST:\s*(.+)$", text, re.MULTILINE)
    if not m:
        return []
    names = [t.strip().upper().lstrip("$") for t in m.group(1).split(",")]
    return [t for t in names if _TICKER_RE.match(t)]


def _parse_watchlist_section(text: str) -> list[str]:
    """Heuristic fallback: bold lead tickers under '## Watchlist notes'."""
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for ln in lines:
        if ln.lstrip().startswith("#"):
            in_section = "watchlist" in ln.lower()
            continue
        if not in_section:
            continue
        low = ln.lower()
        if any(w in low for w in _VETO_WORDS):
            continue
        m = _BULLET_RE.match(ln)
        if m:
            out.append(m.group(1))
    return out


class WatchlistSource:
    name = "watchlist"
    weight = SOURCES.weight_watchlist

    def discover(self) -> list[TickerSignal]:
        try:
            if not PLAYBOOK_PATH.exists():
                return []
            text = PLAYBOOK_PATH.read_text(encoding="utf-8")
            names = _parse_watchlist_line(text) or _parse_watchlist_section(text)
        except Exception as exc:
            log.info(f"source[watchlist]: parse failed ({exc!r})")
            return []
        seen: set[str] = set()
        signals: list[TickerSignal] = []
        for sym in names:
            if sym in seen:
                continue
            seen.add(sym)
            if len(signals) >= _MAX_NAMES:
                break
            # mentions=2 so weighted (2 x 1.1 = 2.2) clears the aggregator's
            # min_weighted_mentions floor (2.0) standalone — a playbook priority
            # is a candidate even with zero news today.
            signals.append(TickerSignal(
                symbol=sym, source=self.name, weight=self.weight,
                mentions=2, sentiment=0.0,
                samples=["[watchlist] named a priority in Joe's own playbook"],
            ))
        return signals
