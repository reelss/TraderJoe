# Joe — Autonomous Swing-Trading Paper Agent

Joe is a virtual trader. He scans Reddit for trending tickers, reads the
technicals, lets Claude make swing-trade decisions, executes them on an Alpaca
**paper** account, logs everything, and rewrites his own playbook each night to
get better over time. Goal: prove whether he can turn a profit on $10,000 of
virtual money — with a full audit trail.

## How it works (one cycle)

```
Reddit scan ─► candidate tickers ─┐
                                  ├─► Claude (the brain) ─► decisions
current holdings + technicals ────┘            │
                                               ▼
                          risk guardrails (stops, caps, breaker)
                                               │
                                               ▼
                                  Alpaca paper orders ─► logs/
```

A nightly **reflection** reviews the day's results and updates `playbook.md`.

## Project layout

| Path | Purpose |
|---|---|
| `agent/config.py` | credentials, risk rules, universe filters (all tunables) |
| `agent/social.py` | Reddit scan + VADER sentiment |
| `agent/broker.py` | Alpaca account, data, orders |
| `agent/indicators.py` | RSI / MACD / SMA / ATR / momentum |
| `agent/brain.py` | Claude decision engine |
| `agent/risk.py` | stop-loss, take-profit, sizing & position caps |
| `agent/cycle.py` | one full trading cycle |
| `agent/reflect.py` | nightly playbook rewrite |
| `agent/main.py` | entrypoint (`cycle` / `reflect`) |
| `scripts/check_connections.py` | Phase-1 connection test |
| `playbook.md` | Joe's evolving lessons |
| `logs/` | decisions / trades / equity (JSONL audit trail) |

## Setup

```powershell
# 1. Create a virtual environment and install deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Add your keys
copy .env.example .env   # then edit .env with real keys

# 3. Verify all three integrations
python scripts/check_connections.py

# 4. Run one cycle by hand (use --force outside market hours)
python -m agent.main cycle --force
```

## Risk rules (enforced in code, not just suggested to the brain)

- Start: **$10,000** paper · max **10%** per position · max **8** positions
- Stop-loss **-8%** · take-profit **+15%** · daily loss breaker **-5%**
- Fractional shares enabled

## Status

Phase 1 (scaffold) built. Pending: API keys → connection test → first live cycle →
scheduling via Windows Task Scheduler.
