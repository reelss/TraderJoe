"""Structured, append-only logging — Joe's audit trail.

Three JSONL streams in logs/:
  - decisions.jsonl : every brain decision (buy/sell/hold) with reasoning
  - trades.jsonl    : every order actually submitted to the broker
  - equity.jsonl    : account equity snapshot per cycle (for P&L charting)

JSONL (one JSON object per line) keeps the log append-only, greppable, and
trivially loadable into pandas for the dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import LOGS_DIR

LOGS_DIR.mkdir(parents=True, exist_ok=True)

DECISIONS = LOGS_DIR / "decisions.jsonl"
TRADES = LOGS_DIR / "trades.jsonl"
EQUITY = LOGS_DIR / "equity.jsonl"
RUN_LOG = LOGS_DIR / "joe.log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path: Path, record: dict[str, Any]) -> None:
    record = {"ts": _now(), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log_decision(symbol: str, action: str, reasoning: str, **extra: Any) -> None:
    _append(DECISIONS, {"symbol": symbol, "action": action,
                        "reasoning": reasoning, **extra})


def log_trade(symbol: str, side: str, qty: float | None, notional: float | None,
              status: str, **extra: Any) -> None:
    _append(TRADES, {"symbol": symbol, "side": side, "qty": qty,
                     "notional": notional, "status": status, **extra})


def log_equity(equity: float, cash: float, positions: int, **extra: Any) -> None:
    _append(EQUITY, {"equity": equity, "cash": cash,
                     "positions": positions, **extra})


def buy_date_for(symbol: str) -> str | None:
    """Timestamp of the most recent successful buy for this symbol.
    Returns None if not found — used to compute hold_days on exit."""
    if not TRADES.exists():
        return None
    latest: str | None = None
    for line in TRADES.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            if (r.get("symbol") == symbol
                    and r.get("side") == "buy"
                    and r.get("status") != "error"):
                latest = r.get("ts")
        except Exception:
            pass
    return latest


def info(msg: str) -> None:
    """Human-readable run log + stdout echo."""
    line = f"[{_now()}] {msg}"
    print(line)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
