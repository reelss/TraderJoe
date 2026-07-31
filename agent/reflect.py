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
from .billing import log_usage
from .broker import Broker
from .config import CREDS, MODELS, PLAYBOOK_PATH, PRINCIPLES_PATH, STRATEGY
from .counterfactual import blocker_scoreboard, recent_resolved
from .digest import send_to_slack
from .llm_retry import create_with_retry
from .perf_stats import compute_stats
from .regime import macro_context

_SYSTEM = """You are the reflective coach for Joe, a swing-trading agent.
You are given Joe's DURABLE PRINCIPLES, today's ephemeral PLAYBOOK, today's account
state and trades, AND a macro market context block showing how the market moved.

Joe's memory is split into two layers — respect the difference:
  • PRINCIPLES = durable, slowly-earned method (risk limits, entry criteria, what
    works long-term). Change these RARELY — only when a principle has been
    validated or invalidated across MULTIPLE trades, not a single day's result.
  • PLAYBOOK = today's market-specific notes: sector tilts, what to watch
    tomorrow, near-term tactical reminders. This is rewritten every night.

Produce TWO clearly delimited Markdown sections in your response:

<<<PLAYBOOK>>>
(The new ephemeral playbook — concise, actionable, tomorrow-focused.)
- Promote patterns that worked today; warn against ones that lost money.
- Use the macro context: sector rotation, VIX spikes, broad-market weakness.
- Update watchlist notes (which sectors/names have the wind at their back).
- Sections: "What's working", "Mistakes to avoid", "Market context & sector
  notes", "Watchlist notes". Keep under ~50 lines.
- END the playbook with one machine-readable line (it feeds tomorrow's
  candidate discovery, so these names are guaranteed to reach the brain):
    WATCHLIST: TICK1, TICK2, TICK3
  List 3-8 tickers Joe actively wants to BUY when their entry conditions are
  met. NEVER include names in vetoed sectors or on the avoid list.

<<<PRINCIPLES>>>
(The durable principles. In MOST nightly runs, return the EXISTING principles
UNCHANGED — copy them through verbatim. Only revise when today's evidence,
combined with the rolling stats, validates or breaks a durable rule across
multiple trades. Never drop below 20 lines; never delete a core risk rule.)

STRUCTURAL REQUIREMENT — you MUST return the complete file, every section,
every time: "## Risk limits", "## Entry criteria", "## Position management",
"## Exit discipline", "## Conviction & sizing", "## PDT rules",
"## Diversification & deployment". Copying unchanged sections through verbatim
IS the expected behavior — a rewrite that omits a section will be rejected.
Keep it TIGHT: scoreboard notes are ONE line each, not paragraphs. Verbose
commentary crowds out the actual rules and risks truncating the file.

ANTI-RATCHET GUARDRAIL (critical). Rules must be able to loosen as well as
tighten, or Joe converges on never trading:
  • You may only make a rule STRICTER (convert a graduated preference into a
    hard veto, raise a threshold) when the BLOCKER SCOREBOARD shows that rule's
    passes were net correct (correct_pass clearly outweighing missed_gain over
    multiple resolutions). An avoided-loss anecdote alone NEVER hardens a rule.
  • When the scoreboard shows a rule is costing money (missed_gain dominating),
    you MUST note it in the playbook and consider loosening it.
  • The volume-ratio rule is GRADUATED SIZING (>=1.5x full size, 0.8-1.5x half
    size on an otherwise-clean setup, <0.8x no entry). NEVER rewrite it as a
    binary 1.5x gate — the binary version froze the account at 93% cash and
    blocked every A-grade setup for a week (July 2026).

DEPLOYMENT ACCOUNTABILITY. The record includes deployment (deployed % vs
target). Under-deployment in a risk-on regime is itself a decision with a
cost. If Joe is far below target, the playbook MUST name which rule blocked
capital and whether the scoreboard evidence justifies it.

Return ONLY these two delimited sections, no preamble."""


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
    current_principles = PRINCIPLES_PATH.read_text(encoding="utf-8") if PRINCIPLES_PATH.exists() else "(no durable principles yet)"

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
    try:
        scoreboard = blocker_scoreboard(days=30)
    except Exception as exc:
        log.info(f"Reflection: blocker scoreboard unavailable ({exc!r}).")
        scoreboard = {}

    invested = sum(p.get("market_value", 0) for p in positions)
    deployed_pct = round(invested / account["equity"], 3) if account.get("equity") else 0.0
    payload = {
        "date": today,
        "account": account,
        "deployment": {
            "deployed_pct": deployed_pct,
            "target_pct": STRATEGY.min_deploy_pct,
            "under_target": deployed_pct < STRATEGY.min_deploy_pct,
        },
        "open_positions": positions,
        "todays_decisions": decisions,
        "todays_trades": trades,
    }
    user = (
        f"DURABLE PRINCIPLES (change rarely — copy through unchanged unless multi-trade evidence):\n{current_principles}\n\n"
        f"CURRENT PLAYBOOK (ephemeral — rewrite freely):\n{current_playbook}\n\n"
        f"MACRO MARKET CONTEXT (today's close):\n{json.dumps(mctx, indent=2, default=str)}\n\n"
        f"ROLLING PERFORMANCE (last 30 days):\n{json.dumps(stats, indent=2, default=str)}\n\n"
        f"COUNTERFACTUAL LESSONS (names passed on — what happened):\n"
        f"{json.dumps(cf_lessons, indent=2, default=str)}\n\n"
        f"BLOCKER SCOREBOARD (per-rule cost of passes, last 30 days — the evidence\n"
        f"required before hardening OR loosening any rule):\n"
        f"{json.dumps(scoreboard, indent=2, default=str)}\n\n"
        f"TODAY'S RECORD:\n{json.dumps(payload, indent=2, default=str)}\n\n"
        "Produce the <<<PLAYBOOK>>> and <<<PRINCIPLES>>> sections now."
    )

    client = Anthropic(api_key=CREDS.anthropic_key)
    try:
        resp = create_with_retry(
            client,
            model=MODELS.reflection_model,
            # Reflection emits TWO documents (playbook + full principles), so it
            # needs far more headroom than a single decision call.
            max_tokens=MODELS.reflection_max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
    except RateLimitError as exc:
        log.info(f"Reflection: Anthropic rate limit after retries ({exc!r}) — skipping update.")
        send_to_slack(":warning: Joe nightly reflection failed: Anthropic rate limit (429) after retries. Playbook unchanged.")
        return
    log_usage(MODELS.reflection_model, resp.usage)

    # Truncation guard. On 2026-07-30 a reflection hit the max_tokens ceiling
    # mid-sentence and wrote a principles file that had silently lost the entire
    # exit-discipline, PDT, sizing, and deployment sections — the line-count
    # guard below passed because the truncated file was still >20 lines. A
    # response that ran out of tokens is never safe to persist.
    if getattr(resp, "stop_reason", None) == "max_tokens":
        log.info("Reflection hit max_tokens — output truncated, NOT writing "
                 "playbook or principles.")
        send_to_slack(":warning: Joe nightly reflection truncated (hit token "
                      "limit) — playbook and principles left unchanged.")
        return

    raw = resp.content[0].text.strip()
    new_playbook, new_principles = _split_sections(raw)

    if new_playbook:
        PLAYBOOK_PATH.write_text(new_playbook + "\n", encoding="utf-8")
        log.info(f"Playbook updated ({len(trades)} trades, {len(decisions)} decisions today).")
    else:
        log.info("Reflection produced no playbook section — playbook unchanged.")

    # Principles guard: only overwrite if the model returned a substantial block
    # (>= 20 non-empty lines). This protects the durable rules from being silently
    # truncated or wiped by a malformed/lazy nightly response.
    if new_principles:
        line_count = len([ln for ln in new_principles.splitlines() if ln.strip()])
        # Structural check: the durable sections must all survive a rewrite.
        # Line count alone is not enough — a truncated file can still be long
        # while having silently dropped exit discipline and PDT rules entirely.
        required = ("## Risk limits", "## Entry criteria", "## Exit discipline",
                    "## PDT rules")
        missing = [h for h in required if h not in new_principles]
        if missing:
            log.info(f"Principles rewrite dropped required section(s) {missing} "
                     "— keeping existing principles.")
            send_to_slack(f":warning: Joe reflection dropped principles section(s) "
                          f"{', '.join(missing)} — principles left unchanged.")
        elif line_count >= 20:
            PRINCIPLES_PATH.write_text(new_principles + "\n", encoding="utf-8")
            log.info(f"Principles updated ({line_count} lines).")
        else:
            log.info(f"Principles section too short ({line_count} lines < 20) "
                     "— keeping existing principles.")
    else:
        log.info("No principles section returned — principles unchanged.")


def _split_sections(text: str) -> tuple[str, str]:
    """Split the reflection response into (playbook, principles).

    Tolerant of marker order: finds each section by its delimiter regardless
    of which appears first. Falls back to treating the whole response as the
    playbook if neither marker is present (legacy single-block behavior).
    """
    pb_marker = "<<<PLAYBOOK>>>"
    pr_marker = "<<<PRINCIPLES>>>"

    pb_pos = text.find(pb_marker)
    pr_pos = text.find(pr_marker)

    if pb_pos == -1 and pr_pos == -1:
        # Legacy: no markers — treat whole response as playbook.
        return text.strip(), ""

    def _extract(text: str, marker: str) -> str:
        pos = text.find(marker)
        if pos == -1:
            return ""
        after = text[pos + len(marker):]
        # Stop at the next marker if one follows.
        for other in ("<<<PLAYBOOK>>>", "<<<PRINCIPLES>>>"):
            if other != marker:
                stop = after.find(other)
                if stop != -1:
                    after = after[:stop]
        return after.strip()

    return _extract(text, pb_marker), _extract(text, pr_marker)
