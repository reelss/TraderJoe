"""Weekly strategy review — Joe's deeper, slower learning loop.

Where nightly reflection updates the *playbook* (what happened today, tactical
lessons), the weekly review updates the *strategy* (is the approach itself
right for current market conditions?).

Runs Sundays at 4 PM CST via Task Scheduler. Uses the stronger model and a
broader lens: 7 days of decisions + outcomes, sector rotation, macro regime,
factor performance. Output is strategy.md — a living document that biases Joe
toward or away from certain styles based on what the market is rewarding.

Joe reads strategy.md alongside the playbook before every decision cycle.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from anthropic import Anthropic, RateLimitError

from . import logbook as log
from .billing import log_usage
from .broker import Broker
from .config import CREDS, MODELS, PLAYBOOK_PATH, STRATEGY_PATH
from .digest import send_to_slack
from .llm_retry import create_with_retry
from .perf_stats import compute_stats, process_scorecard
from .attribution import compute_attribution
from .regime import macro_context

_SYSTEM = """You are the strategic advisor for Joe, an autonomous swing-trading agent.

Unlike the nightly coach (who updates tactical lessons from today's trades),
your job is to assess whether Joe's STRATEGY is right for the current market
environment and recommend directional adjustments for the week ahead.

You are given:
- The last 7 days of Joe's decisions and trade outcomes
- Current market macro context (indices, VIX, sector rotation)
- Joe's current tactical playbook
- Joe's current strategy document (your prior output)

Produce an UPDATED strategy.md in Markdown. Be direct and opinionated.

Sections to include:
0. **Process scorecard** — grade the week against the PROCESS KPIs provided
   (deployment vs 50% target, win rate vs 45%, win/loss ratio vs 1.5x, return
   vs SPY) plus rule adherence (scan the week's decisions for hard-rule
   violations — sector veto breaches, duplicate orders). One line per KPI:
   PASS/FAIL/N-A and what to do about a miss. A missed P&L KPI on a passing
   process is acceptable; a process failure is not. KPIs marked null are
   unmeasurable this week — say so, never grade on noise.
1. **Market regime summary** — what kind of market is this? (trending, choppy,
   risk-on/off, rotation, sector-specific). One short paragraph.
2. **Factor performance** — which edges are working right now? Is momentum
   outperforming? Is mean reversion getting rewarded? Are news catalysts
   translating into follow-through or fading? Be honest if the data is too thin.
3. **Sector tilts** — based on sector rotation, which sectors should Joe
   overweight or underweight in the week ahead? Be specific (e.g. "favor
   Financials and Energy, reduce Tech exposure").
4. **Strategy adjustments** — concrete changes to Joe's approach for next week.
   Examples: tighten stops in choppy tape, be more patient on entries, take
   profits faster in low-momentum environment, etc.
5. **Signal attribution** — read `conviction_calibration` and `by_source`:
   - State the conviction verdict plainly (calibrated / uninformative /
     INVERTED). If inverted, say so bluntly — Joe is overconfident and high
     conviction should be treated as a caution flag, not a reason to size up.
   - Name which discovery sources are earning their weight and which are not,
     using ONLY sources marked `reliable: true` (>= 8 trades). Explicitly say
     when a source has too few trades to judge rather than reading noise.
   - Note the best and worst exit reasons.
   Recommend a concrete weight change only when the evidence is reliable.
6. **Watchlist for next week** — 3-5 specific names or ETFs that set up well
   given the current regime and sector tilts. With brief rationale.

Rules:
- Be direct. "Technology is extended, avoid new longs this week" beats vague hedging.
- If the 7-day sample is too small to draw conclusions, say so and default to
  the current strategy rather than inventing patterns.
- Keep it under 60 lines — Joe reads this every hour, it must be scannable.
- Return ONLY the Markdown strategy document, no preamble."""


def _read_last_n_days(path, days: int = 7) -> list[dict]:
    """Read all records from the last N calendar days (UTC)."""
    if not path.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("ts", "") >= cutoff:
                out.append(r)
        except json.JSONDecodeError:
            pass
    return out


def run_weekly_review() -> None:
    broker = Broker()
    account = broker.account()
    positions = broker.positions()

    # Last 7 days of activity
    decisions = _read_last_n_days(log.DECISIONS, days=7)
    trades = _read_last_n_days(log.TRADES, days=7)

    if not decisions and not trades:
        log.info("Weekly review: no activity in last 7 days — skipping.")
        return

    # Macro context
    try:
        mctx = macro_context(broker)
    except Exception as exc:
        log.info(f"Weekly review: macro context unavailable ({exc!r}).")
        mctx = {}

    # Current documents
    current_playbook = PLAYBOOK_PATH.read_text(encoding="utf-8") if PLAYBOOK_PATH.exists() else "(empty)"
    current_strategy = STRATEGY_PATH.read_text(encoding="utf-8") if STRATEGY_PATH.exists() else "(no prior strategy document)"

    # Rolling stats — best effort.
    try:
        stats_30d = compute_stats(window_days=30)
        stats_7d  = compute_stats(window_days=7)
    except Exception as exc:
        log.info(f"Weekly review: perf stats unavailable ({exc!r}).")
        stats_30d, stats_7d = {}, {}

    # Signal attribution — conviction vs outcome, exit reason analysis.
    try:
        attribution = compute_attribution(window_days=90)
    except Exception as exc:
        log.info(f"Weekly review: attribution unavailable ({exc!r}).")
        attribution = {}

    # Process scorecard — deployment, win rate, win/loss ratio, return vs SPY.
    try:
        spy_ret = mctx.get("indices", {}).get("SPY", {}).get("ret_5d")
        scorecard = process_scorecard(window_days=7, spy_ret=spy_ret)
    except Exception as exc:
        log.info(f"Weekly review: process scorecard unavailable ({exc!r}).")
        scorecard = {}

    payload = {
        "account": account,
        "open_positions": positions,
        "last_7d_decisions": decisions,
        "last_7d_trades": [t for t in trades if t.get("status") != "error"],
    }

    user = (
        f"PROCESS SCORECARD (this week's KPIs — grade these in section 0):\n"
        f"{json.dumps(scorecard, indent=2, default=str)}\n\n"
        f"CURRENT TACTICAL PLAYBOOK:\n{current_playbook}\n\n"
        f"CURRENT STRATEGY DOCUMENT (your prior output):\n{current_strategy}\n\n"
        f"MACRO MARKET CONTEXT:\n{json.dumps(mctx, indent=2, default=str)}\n\n"
        f"PERFORMANCE STATS — last 7 days:\n{json.dumps(stats_7d, indent=2, default=str)}\n\n"
        f"PERFORMANCE STATS — last 30 days:\n{json.dumps(stats_30d, indent=2, default=str)}\n\n"
        f"SIGNAL ATTRIBUTION (conviction vs outcomes, last 90 days):\n"
        f"{json.dumps(attribution, indent=2, default=str)}\n\n"
        f"LAST 7 DAYS OF ACTIVITY:\n{json.dumps(payload, indent=2, default=str)}\n\n"
        "Produce the updated strategy document."
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
        log.info(f"Weekly review: Anthropic rate limit after retries ({exc!r}) — skipping update.")
        send_to_slack(":warning: Joe weekly strategy review failed: Anthropic rate limit (429) after retries. Strategy unchanged.")
        return
    log_usage(MODELS.reflection_model, resp.usage)
    new_strategy = resp.content[0].text.strip()
    if not new_strategy:
        log.info("Weekly review: model returned empty — strategy.md unchanged.")
        return

    STRATEGY_PATH.write_text(new_strategy + "\n", encoding="utf-8")
    log.info(f"Weekly strategy updated ({len(trades)} trades, {len(decisions)} decisions over 7 days).")

    # Post a summary to Slack
    _post_slack_summary(mctx, new_strategy, len(trades), account, scorecard)

    # Self-audit before the week starts — the daily digest skips weekends, so
    # this is the pre-week health check (credit runway especially).
    try:
        from .audit import run_audit
        run_audit()
    except Exception as exc:
        log.info(f"Self-audit failed to run: {exc!r}")


def _scorecard_lines(scorecard: dict) -> list[str]:
    """Render the process KPIs as compact Slack lines."""
    if not scorecard:
        return []
    icons = {True: "✅", False: "❌", None: "▫️"}
    labels = {"deployment": "Deployment", "win_rate": "Win rate",
              "win_loss_ratio": "Win/loss", "vs_spy": "vs SPY"}
    lines = ["*Process scorecard (7d):*"]
    for key, label in labels.items():
        k = scorecard.get(key)
        if not isinstance(k, dict):
            continue
        v = k.get("value")
        if isinstance(v, dict):  # vs_spy carries {joe, spy}
            joe, spy = v.get("joe"), v.get("spy")
            v_str = (f"Joe {joe*100:+.1f}% / SPY {spy*100:+.1f}%"
                     if joe is not None and spy is not None else "n/a")
        elif isinstance(v, float):
            v_str = f"{v*100:.0f}%" if v <= 1 else f"{v:.2f}x"
        else:
            v_str = "n/a"
        lines.append(f"{icons[k.get('pass')]} {label}: {v_str} (target {k.get('target')})")
    return lines


def _post_slack_summary(mctx: dict, strategy: str, n_trades: int, account: dict,
                        scorecard: dict | None = None) -> None:
    """Send a compact weekly strategy update to Slack."""
    indices = mctx.get("indices", {})
    spy = indices.get("SPY", {})
    qqq = indices.get("QQQ", {})
    vix = mctx.get("vix", {})
    leaders = ", ".join(mctx.get("sector_leaders", [])) or "—"
    laggards = ", ".join(mctx.get("sector_laggards", [])) or "—"

    spy_str = f"{spy.get('ret_5d', 0)*100:+.1f}%" if spy.get("ret_5d") is not None else "—"
    qqq_str = f"{qqq.get('ret_5d', 0)*100:+.1f}%" if qqq.get("ret_5d") is not None else "—"
    vix_str = f"{vix.get('current')} ({vix.get('tier', '—')})" if vix.get("current") else "—"

    equity = account.get("equity", 0)
    total_pl = equity - 10000
    total_pct = total_pl / 10000 * 100

    lines = [
        "*📋 Joe's Weekly Strategy Review*",
        f"Equity: ${equity:,.2f} | Total P&L: ${total_pl:+,.2f} ({total_pct:+.1f}%)",
        "",
        *_scorecard_lines(scorecard or {}),
        "",
        f"*Market (5d):* SPY {spy_str} | QQQ {qqq_str} | VIX {vix_str}",
        f"*Sector leaders:* {leaders}",
        f"*Sector laggards:* {laggards}",
        "",
        f"_{n_trades} trades reviewed. Strategy updated — see dashboard for full doc._",
        f"<https://reelss.github.io/TraderJoe/|📊 Dashboard>",
    ]
    send_to_slack("\n".join(lines))
