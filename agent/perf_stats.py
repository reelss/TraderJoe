"""Rolling performance statistics for the reflection and weekly coaching prompts.

Reads trades.jsonl and equity.jsonl and produces a compact dict the models
can reason over directly — win rate, P&L distributions, hold times, exit-reason
breakdowns. Returns a minimal stub when there are fewer than 3 completed trades
so the coach doesn't hallucinate patterns from noise.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from .config import LOGS_DIR


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def compute_stats(window_days: int = 30) -> dict:
    """Compute rolling performance stats for the last window_days calendar days.

    Returns a compact, coach-readable dict. Always safe to include in a prompt —
    returns a minimal stub when data is too thin to draw conclusions.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

    completed = [
        t for t in _read_jsonl(LOGS_DIR / "trades.jsonl")
        if t.get("side") == "sell"
        and t.get("ts", "") >= cutoff
        and t.get("plpc") is not None
        and t.get("status") != "error"
    ]

    if len(completed) < 3:
        return {
            "window_days": window_days,
            "total_completed_trades": len(completed),
            "note": "Too few trades for meaningful stats — keep trading.",
        }

    plpcs   = [t["plpc"] for t in completed]
    wins    = [t for t in completed if t["plpc"] > 0]
    losses  = [t for t in completed if t["plpc"] <= 0]

    hw = [t["hold_days"] for t in wins   if t.get("hold_days") is not None]
    hl = [t["hold_days"] for t in losses if t.get("hold_days") is not None]

    # Exit reason breakdown
    by_reason: dict[str, dict] = {}
    for t in completed:
        r = t.get("reason", "unknown")
        if r not in by_reason:
            by_reason[r] = {"count": 0, "wins": 0, "plpc_sum": 0.0}
        by_reason[r]["count"]    += 1
        by_reason[r]["plpc_sum"] += t["plpc"]
        if t["plpc"] > 0:
            by_reason[r]["wins"] += 1

    reason_summary = {
        r: {
            "count":    v["count"],
            "win_rate": round(v["wins"] / v["count"], 3),
            "avg_plpc": round(v["plpc_sum"] / v["count"], 4),
        }
        for r, v in by_reason.items()
    }

    # Equity trend from equity log
    eq_log     = _read_jsonl(LOGS_DIR / "equity.jsonl")
    recent_eq  = [e for e in eq_log if e.get("ts", "") >= cutoff]
    eq_start   = recent_eq[0].get("equity")  if recent_eq else None
    eq_end     = recent_eq[-1].get("equity") if recent_eq else None
    eq_chg_pct = (
        round((eq_end - eq_start) / eq_start, 4)
        if eq_start and eq_end and eq_start > 0 else None
    )

    return {
        "window_days":              window_days,
        "total_completed_trades":   len(completed),
        "win_rate":                 round(len(wins) / len(completed), 3),
        "avg_plpc_all":             round(mean(plpcs), 4),
        "avg_plpc_winners":         round(mean([t["plpc"] for t in wins]),   4) if wins   else None,
        "avg_plpc_losers":          round(mean([t["plpc"] for t in losses]), 4) if losses else None,
        "avg_hold_days_winners":    round(mean(hw), 1) if hw else None,
        "avg_hold_days_losers":     round(mean(hl), 1) if hl else None,
        "exits_by_reason":          reason_summary,
        "equity_change_pct":        eq_chg_pct,
    }
