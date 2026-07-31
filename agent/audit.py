"""Daily self-audit — makes Joe's silent failures loud.

Joe reports P&L in detail and reports nothing about his own health. Every
serious problem found on 2026-07-30/31 had been running silently: principles.md
truncated by a token limit with four sections lost, the profit ladder never
firing once across 54 trades, deployment ignoring market direction entirely,
API credit reaching zero, protective-stop errors swallowed by a bare except.
None of them raised anything; each needed a human to go looking.

This module asserts the invariants that would have caught them and shouts in
Slack when one breaks. Findings are ("CRITICAL"|"WARN", message):
  CRITICAL — Joe is broken, unprotected, or about to stop trading.
  WARN     — degraded or drifting; worth a look, not an emergency.

Run standalone (`python -m agent.main audit`) or automatically at the end of
the daily digest.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import logbook as log
from .billing import estimate_runway
from .config import PRINCIPLES_PATH, STRATEGY

# principles.md must always carry these — a rewrite that drops one means the
# nightly reflection truncated or mangled the durable rules.
_REQUIRED_SECTIONS = (
    "## Risk limits", "## Entry criteria", "## Exit discipline", "## PDT rules",
)
_MIN_PRINCIPLES_LINES = 30

# Exit reasons produced by the mechanical ladder (as opposed to brain discretion).
_LADDER_REASONS = frozenset({
    "trailing_stop_breakeven", "trailing_stop_profit",
    "trailing_take_profit", "stop_loss",
})
_LADDER_LOOKBACK_TRADES = 25


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


def _check_principles() -> list[tuple[str, str]]:
    """Durable rules intact? This is the check that would have caught the
    2026-07-29 truncation that silently dropped exit discipline and PDT rules."""
    if not PRINCIPLES_PATH.exists():
        return [("CRITICAL", "principles.md is missing entirely")]
    text = PRINCIPLES_PATH.read_text(encoding="utf-8")
    out = []
    missing = [s for s in _REQUIRED_SECTIONS if s not in text]
    if missing:
        out.append(("CRITICAL",
                    f"principles.md is missing section(s): {', '.join(missing)} "
                    "— durable rules were dropped by a rewrite"))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < _MIN_PRINCIPLES_LINES:
        out.append(("CRITICAL",
                    f"principles.md is only {len(lines)} non-empty lines "
                    f"(expected >= {_MIN_PRINCIPLES_LINES}) — likely truncated"))
    # Truncation detection. A naive "ends with a period" test does NOT work:
    # the real 2026-07-29 truncation ended '...(sub-0.' — a decimal point — and
    # would sail through. Two signals that actually catch it:
    #   1) unbalanced brackets on the final line (the dangling '(' above)
    #   2) the file shrinking materially versus its own high-water mark
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    for opener, closer in (("(", ")"), ("[", "]")):
        if last.count(opener) > last.count(closer):
            out.append(("CRITICAL",
                        f"principles.md last line has an unclosed '{opener}' — "
                        f"truncated mid-sentence: ...{last[-60:]!r}"))
            break

    hwm_path = PRINCIPLES_PATH.parent / "logs" / "principles_lines.json"
    try:
        prev = json.loads(hwm_path.read_text(encoding="utf-8")).get("max_lines", 0)
    except Exception:
        prev = 0
    if prev and len(lines) < prev * 0.75:
        out.append(("CRITICAL",
                    f"principles.md shrank from {prev} to {len(lines)} lines "
                    "(>25% loss) — a rewrite dropped durable rules"))
    if len(lines) > prev:
        try:
            hwm_path.parent.mkdir(parents=True, exist_ok=True)
            hwm_path.write_text(json.dumps({"max_lines": len(lines)}), encoding="utf-8")
        except Exception as exc:
            log.info(f"principles line-count checkpoint write failed: {exc!r}")
    return out


def _check_stop_coverage(broker) -> list[tuple[str, str]]:
    """Every position opened before today must have a resting broker stop.
    Without one, an overnight gap runs past the intended exit (AVGO, -14%)."""
    try:
        positions = broker.positions()
        if not positions:
            return []
        opened_today = broker.symbols_bought_today()
        stops = broker.resting_stops()
        naked = [p["symbol"] for p in positions
                 if p["symbol"] not in opened_today and p["symbol"] not in stops]
        if naked:
            return [("CRITICAL",
                     f"{len(naked)} position(s) have NO protective stop: "
                     f"{', '.join(sorted(naked))} — unprotected against a gap")]
    except Exception as exc:
        return [("WARN", f"stop-coverage check failed: {exc!r}")]
    return []


def _check_ladder_alive() -> list[tuple[str, str]]:
    """Is the mechanical exit ladder actually firing? Across the first 54 trades
    it fired once — every other exit was brain discretion and the ladder was
    effectively dead code. Silence here means the thresholds are miscalibrated."""
    sells = [t for t in _read_jsonl(log.TRADES)
             if t.get("side") == "sell" and t.get("status") != "error"]
    recent = sells[-_LADDER_LOOKBACK_TRADES:]
    if len(recent) < 10:
        return []   # too few exits to judge
    fired = [t for t in recent if t.get("reason") in _LADDER_REASONS]
    if not fired:
        return [("WARN",
                 f"exit ladder has not fired in the last {len(recent)} exits — "
                 "all were brain discretion; thresholds may be unreachable again")]
    return []


def _check_deployment(broker) -> list[tuple[str, str]]:
    try:
        a = broker.account()
        positions = broker.positions()
        if not a.get("equity"):
            return []
        dep = sum(p["market_value"] for p in positions) / a["equity"]
        if dep < STRATEGY.min_deploy_pct * 0.6:
            return [("WARN",
                     f"deployment {dep:.0%} is far below the "
                     f"{STRATEGY.min_deploy_pct:.0%} target — capital is idle")]
    except Exception as exc:
        return [("WARN", f"deployment check failed: {exc!r}")]
    return []


def _check_runway() -> list[tuple[str, str]]:
    """API credit. Reaching zero stops Joe trading outright (2026-07-09)."""
    rw = estimate_runway()
    if not rw.get("available"):
        return [("WARN",
                 "API credit runway unknown — no balance checkpoint set. "
                 "Run: python -m agent.main billing --set <console balance>")]
    if rw.get("warn"):
        days = (f"~{rw['days_remaining']:.1f}d" if rw.get("days_remaining") is not None
                else "unknown")
        return [("CRITICAL",
                 f"API credit low: ~${rw['remaining_usd']:.2f} left ({days} at "
                 "current burn). Top up or Joe stops trading.")]
    return []


def _check_activity() -> list[tuple[str, str]]:
    """Did Joe actually run today, and did anything crash?"""
    out = []
    if not log.RUN_LOG.exists():
        return [("WARN", "no run log found")]
    today = datetime.now(timezone.utc).date().isoformat()
    lines = [ln for ln in log.RUN_LOG.read_text(encoding="utf-8",
                                                errors="replace").splitlines()
             if ln.startswith(f"[{today}")]
    if datetime.now(timezone.utc).weekday() < 5:
        cycles = sum(1 for ln in lines if "Cycle complete." in ln)
        if cycles == 0:
            out.append(("CRITICAL",
                        "no cycles completed today (weekday) — scheduler or "
                        "Joe may be down"))
    fatals = [ln for ln in lines if "FATAL" in ln]
    if fatals:
        out.append(("CRITICAL",
                    f"{len(fatals)} FATAL error(s) today. Latest: "
                    f"{fatals[-1][-160:]}"))
    return out


def _check_blocker_health() -> list[tuple[str, str]]:
    """Any entry rule now costing more than it saves, per resolved outcomes?"""
    try:
        from .counterfactual import blocker_scoreboard
        sb = blocker_scoreboard(days=30)
    except Exception as exc:
        return [("WARN", f"blocker scoreboard unavailable: {exc!r}")]
    out = []
    for rule, s in sb.items():
        if rule in ("unattributed", "other"):
            continue
        if s.get("net_verdict") == "rule_costing_money":
            out.append(("WARN",
                        f"rule '{rule}' is COSTING money: {s['missed_gain']} missed "
                        f"gains vs {s['correct_pass']} correct passes over "
                        f"{s['passes']} resolutions — consider loosening"))
    total = sum(s["passes"] for s in sb.values()) or 1
    unattr = sb.get("unattributed", {}).get("passes", 0)
    recent = total - unattr
    if recent and unattr / total > 0.9 and total > 50:
        out.append(("WARN",
                    "over 90% of resolved passes are unattributed — blocker "
                    "attribution may have stopped working"))
    return out


def _check_conviction_calibration() -> list[tuple[str, str]]:
    """Is Joe's self-reported conviction inversely related to outcomes?
    Inverted conviction means he sizes up on his worst ideas."""
    try:
        from .attribution import compute_attribution
        cal = compute_attribution(window_days=90).get("conviction_calibration", {})
    except Exception as exc:
        return [("WARN", f"conviction calibration unavailable: {exc!r}")]
    rho = cal.get("spearman_rho")
    if rho is None:
        return []
    if rho <= -0.20:
        return [("WARN",
                 f"conviction is INVERTED (rho {rho:+.2f} over {cal.get('n')} "
                 "trades) — high-conviction trades are underperforming; "
                 "Joe is systematically overconfident")]
    return []


def run_audit(post_to_slack: bool = True) -> list[tuple[str, str]]:
    """Run every invariant check. Returns findings; posts to Slack if any."""
    findings: list[tuple[str, str]] = []
    findings += _check_principles()
    findings += _check_runway()
    findings += _check_activity()
    findings += _check_ladder_alive()
    findings += _check_blocker_health()
    findings += _check_conviction_calibration()

    try:
        from .broker import Broker
        broker = Broker()
        findings += _check_stop_coverage(broker)
        findings += _check_deployment(broker)
    except Exception as exc:
        findings.append(("WARN", f"broker unavailable for audit: {exc!r}"))

    crit = [f for f in findings if f[0] == "CRITICAL"]
    if findings:
        for sev, msg in findings:
            log.info(f"AUDIT {sev}: {msg}")
    else:
        log.info("AUDIT: all invariants OK.")

    if post_to_slack and findings:
        from .digest import send_to_slack
        icon = "🚨" if crit else "⚠️"
        head = (f"{icon} *Joe self-audit — {len(crit)} critical, "
                f"{len(findings) - len(crit)} warning*")
        body = "\n".join(f"{'🚨' if s == 'CRITICAL' else '⚠️'} {m}"
                         for s, m in findings)
        send_to_slack(f"{head}\n{body}")
    return findings
