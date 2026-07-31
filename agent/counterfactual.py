"""Counterfactual tracking — what happened to names Joe passed on?

When Joe holds or skips a new (non-held) candidate, this module logs the
price. On later cycles when the same symbol reappears with updated prices,
it resolves the counterfactual and appends a verdict.

The reflection coach reads recent resolutions to learn from both missed
opportunities (Joe passed, stock went up) and correct passes (Joe passed,
stock fell). Both are valuable lessons.

Log format — logs/counterfactuals.jsonl (append-only JSONL):
  pass record:     {event:"pass",     symbol, price_at_pass, action, conviction,
                    blockers, reasoning, ts}
  resolved record: {event:"resolved", symbol, pass_ts, price_at_pass, price_now,
                    return_pct, days_elapsed, verdict, blockers, ts}

Verdicts: "missed_gain" (ret > +5%), "correct_pass" (ret < -3%), "neutral".

`blockers` names WHICH rule caused the pass (inferred from the brain's reasoning
text). The blocker scoreboard aggregates resolved outcomes per rule so the
nightly reflection can see which rules are saving money and which are costing
it — without this, Joe only learns from mistakes made, never opportunities
missed, and his rules ratchet stricter forever.
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


def _infer_blockers(reasoning: str) -> list[str]:
    """Tag which rule(s) blocked the entry, from the brain's reasoning text.

    Heuristic string matching — imperfect by design, but consistent enough to
    aggregate. "other" means the pass had no recognizable rule blocker."""
    note = reasoning.lower()
    tags = []
    if "vol" in note and ("gate" in note or "1.5" in note or "confirm" in note
                          or "weak" in note or "drift" in note):
        tags.append("vol_gate")
    if "sector veto" in note or "veto" in note and "sector" in note \
            or ("sector" in note and "sma200" in note):
        tags.append("sector_veto")
    if "extended" in note or "parabolic" in note or "chase" in note:
        tags.append("extended_dont_chase")
    if "macd bearish" in note or "macd" in note and "crossover" in note:
        tags.append("macd_bearish")
    if "below sma200" in note or "below all sma" in note or "below sma" in note:
        tags.append("below_sma")
    if "earnings" in note and ("day" in note or "soon" in note or "window" in note):
        tags.append("earnings_window")
    return tags or ["other"]


def log_passes(candidates: list[dict], decisions: list[dict]) -> None:
    """Log new (non-held) candidates that Joe passed on this cycle.

    Only candidates where held=False and the brain chose HOLD (or made no
    decision) are logged — active holds are not passes.
    """
    decided = {d.get("symbol", "").upper(): d for d in decisions}
    for c in candidates:
        if c.get("held"):
            continue
        sym   = c["symbol"]
        price = c.get("technicals", {}).get("price")
        if not price:
            continue
        d = decided.get(sym, {})
        action = d.get("action", "no_decision").lower()
        if action in ("hold", "no_decision"):
            reasoning = (d.get("reasoning") or "")[:300]
            _append({
                "event":         "pass",
                "symbol":        sym,
                "price_at_pass": price,
                "action":        action,
                "conviction":    d.get("conviction"),
                "reasoning":     reasoning,
                "blockers":      _infer_blockers(reasoning),
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
            "blockers":       r.get("blockers", ["unattributed"]),
        })


def blocker_scoreboard(days: int = 30) -> dict:
    """Aggregate resolved counterfactuals per blocking rule.

    Returns {blocker: {passes, missed_gain, correct_pass, neutral,
                       avg_return_pct, net_verdict}} so the reflection can see
    which rules are paying for themselves and which are costing money.
    net_verdict: "rule_costing_money" when missed gains dominate,
    "rule_saving_money" when correct passes dominate, else "inconclusive".
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    board: dict[str, dict] = {}
    for r in _read_all():
        if r.get("event") != "resolved" or r.get("ts", "") < cutoff:
            continue
        for b in r.get("blockers", ["unattributed"]):
            s = board.setdefault(b, {"passes": 0, "missed_gain": 0,
                                     "correct_pass": 0, "neutral": 0,
                                     "_returns": []})
            s["passes"] += 1
            s[r.get("verdict", "neutral")] = s.get(r.get("verdict", "neutral"), 0) + 1
            if isinstance(r.get("return_pct"), (int, float)):
                s["_returns"].append(r["return_pct"])
    for b, s in board.items():
        rets = s.pop("_returns")
        s["avg_return_pct"] = round(sum(rets) / len(rets), 4) if rets else None
        if s["passes"] >= 5 and s["missed_gain"] >= 2 * max(s["correct_pass"], 1):
            s["net_verdict"] = "rule_costing_money"
        elif s["passes"] >= 5 and s["correct_pass"] >= 2 * max(s["missed_gain"], 1):
            s["net_verdict"] = "rule_saving_money"
        else:
            s["net_verdict"] = "inconclusive"
    return board


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
