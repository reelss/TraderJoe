"""Nightly reflection — how Joe becomes an expert.

After the close, Joe reviews the day's decisions, trades, and equity path, then
asks the stronger model to distill durable lessons and rewrite the playbook.
The playbook is read before every decision, so lessons compound over time.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from anthropic import Anthropic, RateLimitError

from . import logbook as log
from .broker import Broker
from .config import CREDS, MODELS, PLAYBOOK_PATH
from .counterfactual import recent_resolved
from .digest import send_to_slack
from .llm_retry import create_with_retry
from .perf_stats import compute_stats
from .regime import macro_context

_SYSTEM = """You are the reflective coach for Joe, a swing-trading agent.
You are given Joe's current playbook, today's account state and trades, AND a
macro market context block showing how the broad market and sectors moved today.

Produce an UPDATED playbook in Markdown that makes Joe a better trader tomorrow.

Rules for the playbook:
- Keep it concise and actionable — concrete rules, not platitudes.
- Promote patterns that worked; demote or warn against ones that lost money.
- Use the macro context: if sectors are rotating, if VIX is spiking, if the
  broad market is weakening — factor that into what Joe should do differently.
  Update watchlist notes to reflect which sectors and names have the wind at
  their back right now vs. which are facing headwinds.
- Preserve still-valid lessons; revise stale ones; never let it bloat past ~50 lines.
- Sections: "Core principles", "What's working", "Mistakes to avoid",
  "Market context & sector notes", "Watchlist notes".
Return ONLY the Markdown playbook, no preamble."""


def _read_jsonl(path) -> list[dict]:
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


def run_reflection() -> None:
    broker = Broker()
    account = broker.account()
    positions = broker.positions()

    today = datetime.now(timezone.utc).date().isoformat()
    decisions = [d for d in _read_jsonl(log.DECISIONS) if d.get("ts", "").startswith(today)]
    trades = [t for t in _read_jsonl(log.TRADES) if t.get("ts", "").startswith(today)]

    # No activity today (weekend / holiday / quiet day) — don't let the model
    # rewrite a good playbook from an empty log.
    if not decisions and not trades:
        log.info("No activity today — skipping reflection, playbook unchanged.")
        return

    current_playbook = PLAYBOOK_PATH.read_text(encoding="utf-8") if PLAYBOOK_PATH.exists() else "(empty)"

    # Fetch macro context — best effort, never blocks reflection if it fails.
    try:
        mctx = macro_context(broker)
    except Exception as exc:
        log.info(f"Reflection: macro context unavailable ({exc!r}), proceeding without.")
        mctx = {}

    # Rolling stats and counterfactual lessons — best effort, never block reflection.
    try:
        stats = compute_stats(window_days=30)
    except Exception as exc:
        log.info(f"Reflection: perf stats unavailable ({exc!r}).")
        stats = {}
    try:
        cf_lessons = recent_resolved(days=14)
    except Exception as exc:
        log.info(f"Reflection: counterfactual data unavailable ({exc!r}).")
        cf_lessons = []

    payload = {
        "date": today,
        "account": account,
        "open_positions": positions,
        "todays_decisions": decisions,
        "todays_trades": trades,
    }
    user = (
        f"CURRENT PLAYBOOK:\n{current_playbook}\n\n"
        f"MACRO MARKET CONTEXT (today's close):\n{json.dumps(mctx, indent=2, default=str)}\n\n"
        f"ROLLING PERFORMANCE (last 30 days):\n{json.dumps(stats, indent=2, default=str)}\n\n"
        f"COUNTERFACTUAL LESSONS (names passed on — what happened):\n"
        f"{json.dumps(cf_lessons, indent=2, default=str)}\n\n"
        f"TODAY'S RECORD:\n{json.dumps(payload, indent=2, default=str)}\n\n"
        "Rewrite the playbook."
    )

    client = Anthropic(api_key=CREDS.anthropic_key)
    try:
        resp = create_with_retry(
            client,
            model=MODELS.reflection_model,
            max_tokens=MODELS.max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
    except RateLimitError as exc:
        log.info(f"Reflection: Anthropic rate limit after retries ({exc!r}) — skipping update.")
        send_to_slack(":warning: Joe nightly reflection failed: Anthropic rate limit (429) after retries. Playbook unchanged.")
        return
    new_playbook = resp.content[0].text.strip()
    if new_playbook:
        PLAYBOOK_PATH.write_text(new_playbook + "\n", encoding="utf-8")
        log.info(f"Playbook updated ({len(trades)} trades, {len(decisions)} decisions today).")
    else:
        log.info("Reflection produced no update — playbook unchanged.")
