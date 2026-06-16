"""Counterfactual tracking — what happened to names Joe passed on?

When Joe holds or skips a new (non-held) candidate, this module logs the
price. On later cycles when the same symbol reappears with updated prices,
it resolves the counterfactual and appends a verdict.

The reflection coach reads recent resolutions to learn from both missed
opportunities (Joe passed, stock went up) and correct passes (Joe passed,
stock fell). Both are valuable lessons.

Log format — logs/counterfactuals.jsonl (append-only JSONL):
  pass record:     {event:"pass",     symbol, price_at_pass, action, conviction, ts}
  resolved record: {event:"resolved", symbol, pass_ts, price_at_pass, price_now,
                    return_pct, days_elapsed, verdict, ts}

Verdicts: "missed_gain" (ret > +5%), "correct_pass" (ret < -3%), "neutral".
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .config import LOGS_DIR

COUNTERFACTUALS = LOGS_DIR / "counterfactuals.jsonl"
_RESOLVE_AFTER_DAYS = 4   # minimum calendar days before resolving a pass
_MISSED_GAIN_THRESHOLD  =  0.05   # +5% = missed gain
_CORRECT_PASS_THRESHOLD = -0.03   # -3% = correct pass


def _append(record: dict) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with COUNTERFACTUALS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _read_all() -> list[dict]:
    if not COUNTERFACTUALS.exists():
        return []
    out = []
    for line in COUNTERFACTUALS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def log_passes(candidates: list[dict], decisions: list[dict]) -> None:
    """Log new (non-held) candidates that Joe passed on this cycle.

    Only candidates where held=False and the brain chose HOLD (or made no
    decision) are logged — active holds are not passes.
    """
    decided = {d.get("symbol", "").upper(): d.get("action", "").lower()
               for d in decisions}
    for c in candidates:
        if c.get("held"):
            continue
        sym   = c["symbol"]
        price = c.get("technicals", {}).get("price")
        if not price:
            continue
        action = decided.get(sym, "no_decision")
        if action in ("hold", "no_decision"):
            _append({
                "event":        "pass",
                "symbol":       sym,
                "price_at_pass": price,
                "action":       action,
                "conviction":   next(
                    (d.get("conviction") for d in decisions
                     if d.get("symbol", "").upper() == sym),
                    None,
                ),
            })


def resolve_pending(tech_by_sym: dict) -> None:
    """Resolve passes whose symbol appears in the current cycle's bars.

    Only resolves passes that are at least _RESOLVE_AFTER_DAYS old so we
    measure a meaningful holding period, not a same-day tick.
    Resolution happens lazily: if a passed symbol doesn't reappear in news
    for several cycles it will be resolved later when it does.
    """
    records = _read_all()
    resolved_keys: set[tuple] = {
        (r["symbol"], r.get("pass_ts"))
        for r in records if r.get("event") == "resolved"
    }
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RESOLVE_AFTER_DAYS)

    for r in records:
        if r.get("event") != "pass":
            continue
        sym = r["symbol"]
        key = (sym, r["ts"])
        if key in resolved_keys:
            continue
        try:
            pass_dt = datetime.fromisoformat(r["ts"])
        except Exception:
            continue
        if pass_dt > cutoff:
            continue  # too recent — wait longer
        current = tech_by_sym.get(sym, {}).get("price")
        if not current:
            continue   # symbol not in this cycle's bars — resolve later
        ret = round(current / r["price_at_pass"] - 1, 4)
        verdict = (
            "missed_gain"   if ret >  _MISSED_GAIN_THRESHOLD  else
            "correct_pass"  if ret <  _CORRECT_PASS_THRESHOLD else
            "neutral"
        )
        _append({
            "event":          "resolved",
            "symbol":         sym,
            "pass_ts":        r["ts"],
            "price_at_pass":  r["price_at_pass"],
            "price_now":      round(current, 2),
            "return_pct":     ret,
            "days_elapsed":   (datetime.now(timezone.utc) - pass_dt).days,
            "verdict":        verdict,
        })


def recent_resolved(days: int = 14) -> list[dict]:
    """Return recently resolved counterfactuals for the reflection prompt.

    Only returns missed_gain and correct_pass verdicts (not neutral) since
    those are the actionable lessons.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [
        r for r in _read_all()
        if r.get("event") == "resolved"
        and r.get("ts", "") >= cutoff
        and r.get("verdict") in ("missed_gain", "correct_pass")
    ]
