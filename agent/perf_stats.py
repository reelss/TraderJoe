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


def process_scorecard(window_days: int = 7, spy_ret: float | None = None) -> dict:
    """Weekly PROCESS scorecard — grades how Joe traded, not just what he made.

    Process goals beat P&L goals on a swing account: hit the process and the
    P&L follows; miss the P&L while hitting the process and the market was
    simply hostile that week. Targets:
      deployment  — average % of equity deployed >= 50%
      win_rate    — >= 45% of completed trades profitable
      win_loss    — average winner >= 1.5x average loser
      vs_spy      — equity change beats SPY over the window
    Each KPI reports {value, target, pass}; "pass" is None when unmeasurable
    (too few trades / no benchmark) so the coach never grades on noise.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

    # Deployment from the per-cycle equity log: deployed = (equity - cash) / equity.
    eq = [e for e in _read_jsonl(LOGS_DIR / "equity.jsonl")
          if e.get("ts", "") >= cutoff and e.get("equity")]
    dep = [(e["equity"] - e.get("cash", 0)) / e["equity"] for e in eq if e["equity"] > 0]
    avg_deployed = round(mean(dep), 3) if dep else None

    stats = compute_stats(window_days)
    win_rate = stats.get("win_rate")
    avg_w, avg_l = stats.get("avg_plpc_winners"), stats.get("avg_plpc_losers")
    wl_ratio = round(abs(avg_w / avg_l), 2) if avg_w and avg_l else None

    # Equity change straight from the equity log — compute_stats withholds it
    # below 3 completed trades, but the account curve is measurable regardless.
    eq_chg = (round(eq[-1]["equity"] / eq[0]["equity"] - 1, 4)
              if len(eq) >= 2 and eq[0]["equity"] > 0 else None)

    def kpi(value, target, ok):
        # ok=None means unmeasurable this window — never grade on noise.
        return {"value": value, "target": target, "pass": ok}

    return {
        "window_days": window_days,
        "deployment":  kpi(avg_deployed, ">= 0.50 when risk-on",
                           avg_deployed >= 0.50 if avg_deployed is not None else None),
        "win_rate":    kpi(win_rate, ">= 0.45",
                           win_rate >= 0.45 if win_rate is not None else None),
        "win_loss_ratio": kpi(wl_ratio, ">= 1.5x",
                              wl_ratio >= 1.5 if wl_ratio is not None else None),
        "vs_spy":      kpi({"joe": eq_chg, "spy": spy_ret}, "beat SPY",
                           eq_chg > spy_ret
                           if eq_chg is not None and spy_ret is not None else None),
    }


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
