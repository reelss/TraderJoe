"""Signal attribution — does Joe's behavior correlate with outcomes?

Reads the trade log to answer:
- Does higher conviction at entry lead to better exits?
- Which exit reasons (stop_loss, take_profit, brain_sell, trailing_stop) produce
  the best outcomes?
- Are there conviction levels Joe should use more or less?

Fed into the weekly strategy review so the advisor can spot systematic biases
(e.g. "high-conviction trades are underperforming — Joe is overconfident" or
"most stops are at conviction=2 entries — lower the bar for those").
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import LOGS_DIR

_TRADES = LOGS_DIR / "trades.jsonl"


def _read_trades(window_days: int) -> list[dict]:
    if not _TRADES.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
    out = []
    for line in _TRADES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("ts", "") >= cutoff and r.get("status") != "error":
                out.append(r)
        except json.JSONDecodeError:
            pass
    return out


def compute_attribution(window_days: int = 90) -> dict:
    """Correlate entry conviction with exit outcomes.

    Matches buy→sell pairs by symbol (last buy before each sell), then
    groups outcomes by buy-conviction and exit-reason.

    Returns {} when < 5 completed trades (not enough data to draw conclusions).
    """
    trades = _read_trades(window_days)
    if not trades:
        return {}

    # Walk chronologically, tracking last-buy conviction per symbol.
    last_buy: dict[str, dict] = {}
    completed: list[dict] = []
    for t in sorted(trades, key=lambda x: x.get("ts", "")):
        sym = t.get("symbol", "")
        if t.get("side") == "buy":
            last_buy[sym] = {
                "conviction": t.get("conviction"),
                "ts": t.get("ts", ""),
            }
        elif t.get("side") == "sell" and t.get("plpc") is not None:
            buy_info = last_buy.get(sym, {})
            completed.append({
                "symbol": sym,
                "buy_conviction": buy_info.get("conviction"),
                "plpc": t.get("plpc", 0.0),
                "exit_reason": t.get("reason", "unknown"),
                "hold_days": t.get("hold_days"),
            })

    if len(completed) < 5:
        return {"note": "insufficient data", "completed_trades": len(completed)}

    # --- By conviction level ---
    by_conviction: dict[int | str, dict] = defaultdict(
        lambda: {"count": 0, "wins": 0, "total_plpc": 0.0, "hold_days": []}
    )
    for c in completed:
        conv = c["buy_conviction"] or "unknown"
        rec = by_conviction[conv]
        rec["count"] += 1
        rec["total_plpc"] += c["plpc"]
        if c["plpc"] > 0:
            rec["wins"] += 1
        if c["hold_days"] is not None:
            rec["hold_days"].append(c["hold_days"])

    conviction_summary = {}
    for conv, rec in sorted(by_conviction.items(), key=lambda x: str(x[0])):
        n = rec["count"]
        conviction_summary[str(conv)] = {
            "count": n,
            "win_rate": round(rec["wins"] / n, 3),
            "avg_plpc": round(rec["total_plpc"] / n, 4),
            "avg_hold_days": (round(sum(rec["hold_days"]) / len(rec["hold_days"]), 1)
                              if rec["hold_days"] else None),
        }

    # --- By exit reason ---
    by_reason: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "wins": 0, "total_plpc": 0.0}
    )
    for c in completed:
        rec = by_reason[c["exit_reason"]]
        rec["count"] += 1
        rec["total_plpc"] += c["plpc"]
        if c["plpc"] > 0:
            rec["wins"] += 1

    reason_summary = {
        reason: {
            "count": rec["count"],
            "win_rate": round(rec["wins"] / rec["count"], 3),
            "avg_plpc": round(rec["total_plpc"] / rec["count"], 4),
        }
        for reason, rec in sorted(by_reason.items(),
                                   key=lambda x: -x[1]["total_plpc"] / max(x[1]["count"], 1))
    }

    # --- Top/bottom conviction insight ---
    scored = [
        (str(conv), rec["total_plpc"] / rec["count"])
        for conv, rec in by_conviction.items()
        if rec["count"] >= 2 and str(conv).isdigit()
    ]
    best_conv = max(scored, key=lambda x: x[1])[0] if scored else None
    worst_conv = min(scored, key=lambda x: x[1])[0] if scored else None

    return {
        "window_days": window_days,
        "completed_trades": len(completed),
        "by_conviction": conviction_summary,
        "by_exit_reason": reason_summary,
        "best_conviction_level": best_conv,
        "worst_conviction_level": worst_conv,
    }
