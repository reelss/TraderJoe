"""Daily digest — Joe reports to you on Slack after the close.

Pulls live account state + the day's trades/decisions from the logs, has Claude
write a short personality-rich summary plus a forward-ready "friends version,"
and posts it to a Slack incoming webhook. All the numbers are templated (always
correct); the narrative is a cheap Haiku call that degrades gracefully.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

from . import logbook as log
from .broker import Broker
from .config import CREDS, MODELS, RISK

DASHBOARD_URL = "https://reelss.github.io/TraderJoe/"


def _today_utc() -> str:
    # Logs are written with UTC timestamps; filter on the same basis. The whole
    # US trading session + the after-close digest fall within one UTC date.
    return datetime.now(timezone.utc).date().isoformat()


def _read_today(path) -> list[dict]:
    today = _today_utc()
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("ts", "").startswith(today):
                    out.append(r)
            except json.JSONDecodeError:
                pass
    return out


def _narrative(facts: dict) -> dict:
    """Cheap Haiku call: friendly summary + a WhatsApp-ready friends blurb.
    Returns {'summary': str, 'friends': str}; empty strings on any failure."""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=CREDS.anthropic_key)
        sys = (
            "You are Joe, an AI swing-trading agent giving your human a short, "
            "upbeat end-of-day update on your $10k paper account. Be confident but "
            "honest about losses. Return ONLY JSON: "
            '{"summary": "<2-3 sentences, first person, on today>", '
            '"friends": "<1-2 sentence fun blurb he can forward to friends on WhatsApp, '
            'with an emoji or two>"}'
        )
        resp = client.messages.create(
            model=MODELS.decision_model,
            max_tokens=500,
            system=sys,
            messages=[{"role": "user", "content": json.dumps(facts, default=str)}],
        )
        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip()
        s, e = text.find("{"), text.rfind("}")
        data = json.loads(text[s:e + 1])
        return {"summary": data.get("summary", ""), "friends": data.get("friends", "")}
    except Exception:
        return {"summary": "", "friends": ""}


def build_digest() -> dict:
    broker = Broker()
    account = broker.account()
    positions = broker.positions()
    trades = _read_today(log.TRADES)
    decisions = _read_today(log.DECISIONS)

    equity = account["equity"]
    last = account["last_equity"] or equity
    day_pl = equity - last
    day_pct = (day_pl / last) if last else 0.0
    total_pl = equity - RISK.starting_equity
    total_pct = total_pl / RISK.starting_equity

    facts = {
        "date": _today_utc(),
        "equity": round(equity, 2),
        "cash": round(account["cash"], 2),
        "day_pl": round(day_pl, 2),
        "day_pct": round(day_pct * 100, 2),
        "total_pl": round(total_pl, 2),
        "total_pct": round(total_pct * 100, 2),
        "open_positions": [
            {"symbol": p["symbol"], "qty": round(p["qty"], 4),
             "unrealized_plpc": round(p["unrealized_plpc"] * 100, 1)}
            for p in positions
        ],
        "trades_today": [
            {"symbol": t["symbol"], "side": t["side"],
             "notional": t.get("notional"), "reason": t.get("reason")}
            for t in trades
        ],
        "n_decisions": len(decisions),
    }
    facts["narrative"] = _narrative(facts)
    facts["_account"] = account
    facts["_positions"] = positions
    facts["_trades"] = trades
    return facts


def _slack_text(f: dict) -> str:
    up = "🟢" if f["day_pl"] >= 0 else "🔴"
    tot = "📈" if f["total_pl"] >= 0 else "📉"
    lines = [
        f"*🦙 Joe's Daily Digest — {f['date']}*",
        f"{up} *Today:* ${f['day_pl']:+,.2f} ({f['day_pct']:+.2f}%)   "
        f"{tot} *Total:* ${f['total_pl']:+,.2f} ({f['total_pct']:+.2f}%)",
        f"*Equity:* ${f['equity']:,.2f}  |  *Cash:* ${f['cash']:,.2f}",
        f"<{DASHBOARD_URL}|📊 View live dashboard>",
    ]
    if f["narrative"].get("summary"):
        lines += ["", f"_{f['narrative']['summary']}_"]

    if f["open_positions"]:
        lines += ["", "*Open positions:*"]
        for p in f["open_positions"]:
            arrow = "▲" if p["unrealized_plpc"] >= 0 else "▼"
            lines.append(f"• {p['symbol']}: {arrow} {p['unrealized_plpc']:+.1f}%")
    else:
        lines += ["", "_No open positions._"]

    if f["trades_today"]:
        lines += ["", "*Today's trades:*"]
        for t in f["trades_today"]:
            size = f"${t['notional']:,.0f}" if t.get("notional") else ""
            lines.append(f"• {t['side'].upper()} {t['symbol']} {size} ({t.get('reason', '')})")
    else:
        lines += ["", "_No trades today._"]

    if f["narrative"].get("friends"):
        lines += ["", "─" * 12, "*📲 Forward to friends:*", f"> {f['narrative']['friends']}"]
    return "\n".join(lines)


def send_to_slack(text: str) -> bool:
    url = CREDS.slack_webhook
    if not url:
        log.info("No SLACK_WEBHOOK_URL set — digest built but not sent.")
        return False
    try:
        r = requests.post(url, json={"text": text}, timeout=10)
        return r.status_code == 200
    except requests.RequestException as exc:
        log.info(f"Slack post failed: {exc!r}")
        return False


def run_digest() -> None:
    # Skip on weekends — market is closed, nothing happened, no Slack noise.
    if datetime.now(timezone.utc).weekday() >= 5:  # 5=Sat, 6=Sun
        log.info("Weekend — skipping digest.")
        return

    f = build_digest()
    text = _slack_text(f)
    ok = send_to_slack(text)
    log.info(f"Digest: day {f['day_pct']:+.2f}%, total {f['total_pct']:+.2f}%, "
             f"{len(f['trades_today'])} trades — sent to Slack: {ok}")
    # Refresh the local HTML dashboard, then publish it to GitHub Pages so the
    # live page updates at market close.
    try:
        from .dashboard_page import build_dashboard
        build_dashboard()
        from .publish import publish_dashboard
        publish_dashboard()
    except Exception as exc:
        log.info(f"Dashboard refresh/publish failed: {exc!r}")
