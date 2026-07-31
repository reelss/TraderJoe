"""API spend tracking and runway estimate.

Anthropic exposes no API to read the Console credit balance — the only signal
Joe gets today is a hard 400 error once it's already at zero (the 2026-07-09
outage). This module estimates runway instead of watching the real number:
every Claude call logs its actual token usage + cost, and Raheel tells Joe
the Console balance once whenever he tops up (`set_checkpoint`). From there,
spend since the checkpoint is tracked against the trailing burn rate so the
daily digest can warn days before a projected zero, not after.

This is an ESTIMATE, not the real balance — pricing drift or an out-of-band
console top-up will desync it. `set_checkpoint` after every top-up keeps it
honest.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .config import LOGS_DIR

USAGE_LOG = LOGS_DIR / "api_usage.jsonl"
CHECKPOINT_PATH = LOGS_DIR / "billing_checkpoint.json"

# $ per 1M tokens, input/output. Update if models or pricing change.
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6":            {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5-20251001":    {"input": 1.00,  "output": 5.00},
}

# Warn in the digest when projected runway drops below this many days,
# or below this dollar floor — whichever trips first.
WARN_DAYS = 5.0
WARN_DOLLARS = 2.0


def log_usage(model: str, usage) -> None:
    """Append one API call's actual cost. Best-effort: never raises."""
    try:
        price = PRICING.get(model)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        cost = (
            (in_tok / 1_000_000 * price["input"] + out_tok / 1_000_000 * price["output"])
            if price else None
        )
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": round(cost, 6) if cost is not None else None,
        }
        with USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # spend tracking must never break a trading cycle


def set_checkpoint(balance_usd: float) -> None:
    """Record a known Console balance as of now — call this after every top-up."""
    CHECKPOINT_PATH.write_text(json.dumps({
        "balance_usd": balance_usd,
        "ts": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")


def _read_usage_since(cutoff_iso: str) -> list[dict]:
    if not USAGE_LOG.exists():
        return []
    out = []
    for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("ts", "") >= cutoff_iso and r.get("cost_usd") is not None:
                out.append(r)
        except json.JSONDecodeError:
            pass
    return out


def estimate_runway() -> dict:
    """Estimated remaining balance and days-of-runway since the last checkpoint.

    Returns {"available": False} if no checkpoint has ever been set. Otherwise:
      checkpoint_balance, checkpoint_ts, spent_since_checkpoint,
      remaining_usd, avg_daily_burn_usd (trailing 7d), days_remaining, warn.
    days_remaining is None when burn rate is 0 (nothing spent yet this week).
    """
    if not CHECKPOINT_PATH.exists():
        return {"available": False}
    try:
        chk = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False}

    spent = sum(r["cost_usd"] for r in _read_usage_since(chk["ts"]))
    remaining = chk["balance_usd"] - spent

    burn_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent = _read_usage_since(max(burn_cutoff, chk["ts"]))
    span_days = max(
        (datetime.now(timezone.utc)
         - datetime.fromisoformat(max(chk["ts"], burn_cutoff))).total_seconds() / 86400,
        0.25,
    )
    avg_daily_burn = sum(r["cost_usd"] for r in recent) / span_days if recent else 0.0

    days_remaining = (remaining / avg_daily_burn) if avg_daily_burn > 0 else None
    warn = remaining <= WARN_DOLLARS or (days_remaining is not None and days_remaining <= WARN_DAYS)

    return {
        "available": True,
        "checkpoint_balance": chk["balance_usd"],
        "checkpoint_ts": chk["ts"],
        "spent_since_checkpoint": round(spent, 4),
        "remaining_usd": round(remaining, 4),
        "avg_daily_burn_usd": round(avg_daily_burn, 4),
        "days_remaining": round(days_remaining, 1) if days_remaining is not None else None,
        "warn": warn,
    }
