# Trading Project (Joe) — Agent Rules

Autonomous paper-trading agent. Python. Runs on Windows Task Scheduler — treat as live/production.

## Stack
- Python 3.14 + venv at `.venv/`
- Alpaca Markets API (paper trading)
- Claude API (Haiku for trade decisions, Sonnet for nightly reflection)
- Slack (daily digest)
- GitHub Pages (live dashboard at reelss.github.io/TraderJoe)

## Rules
- **Never modify Task Scheduler scripts** (`run_hourly.bat`, `run_close.bat`) without checking the scheduler config first.
- **Never touch `.env`** — secrets managed separately.
- Always activate venv before running: `.venv/Scripts/activate`
- This is live/autonomous — test changes thoroughly before leaving them unattended.
- Don't change Alpaca order types (bracket orders are intentional for stop/target enforcement).

## Commands
```bash
# Activate venv
.venv\Scripts\activate

# Install deps
pip install -r requirements.txt

# Run manually
python main.py          # single trading cycle
python reflect.py       # nightly reflection
python dashboard.py     # regenerate dashboard
```

## Scheduler jobs (Windows Task Scheduler)
- Hourly cycle: `run_hourly.bat` (market hours)
- Market close: `run_close.bat` (4:30pm + 4:35pm CT)
