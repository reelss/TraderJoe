# Trading Project — Memory

Project-scoped memory for the autonomous paper-trading agent. Root context: [[../../CLAUDE|Main Brain]].

## The Agent — "Joe"

- **Name:** Joe. An autonomous swing-trading agent on a virtual (paper) account.
- **Goal:** actively monitor stocks, buy/sell on its own, log everything, and prove whether it can turn a profit over time.

## Locked architecture decisions (2026-06-01)

- **Money:** Alpaca **paper** trading account — simulated $, real market data, real fills.
- **Starting balance:** **$10,000** virtual.
- **Brain:** Claude as LLM-trader — reasons each cycle over technicals + Reddit sentiment, decisions logged in plain English. Runs as a standalone Python script, so it needs its own Anthropic API key.
- **Signal sources (multi-source, reliability-weighted):** Joe discovers tickers across several sources, merged by an aggregator that weights reliable sources higher (news 1.5 · Finnhub 1.4 · StockTwits 1.0 · Reddit 0.6). Code in `agent/sources/`.
  - **Alpaca News (Benzinga)** — primary, reliable newswire; uses existing Alpaca keys, no extra cred. Weight 1.5.
  - **Finnhub** — optional free key (`FINNHUB_API_KEY`); second independent newswire. Auto-activates only if key present. Weight 1.4.
  - **Reddit (PRAW)** — speculative/early hype input, lowest weight 0.6.
  - **StockTwits** — DISABLED by default: its public API is Cloudflare-gated (returns 403 to scripts as of 2026-06). Code kept as best-effort opt-in for if paid access is added.
- **Horizon:** Swing (days–weeks).
- **Universe:** Reddit-discovered trending tickers, filtered for liquidity/price.
- **Learning:** Reflective **playbook.md** — nightly review of trades vs. outcomes updates the lessons file Joe reads before each decision.
- **Schedule:** Windows Task Scheduler, **hourly** cycles during market hours (8:30am–3pm CST) + nightly reflection. Hourly chosen 2026-06-01: right cadence for swing trading (no edge lost vs. 20-min) and ~2.5× cheaper on API. $5 of Anthropic credit ≈ ~2 months at this cadence.
- **Stack:** Python (not the default Next.js — this is data/scheduling work).

## Risk guardrails (scaled for $10,000)

- Max **10%** (~$1,000) per position; **fractional shares** enabled.
- Max **8** open positions.
- Stop-loss **−8%**, take-profit **+15%** (Joe may override with logged reasoning).
- Daily loss circuit-breaker: halt trading if account drops **>5%** in a day.
- Fully autonomous (paper money) — no per-trade approval; everything logged.

## Credentials needed (all free; stored in gitignored `.env`)

1. Alpaca paper trading — key + secret.
2. Reddit API — client ID + secret (script app).
3. Anthropic API key — recurring token cost; mitigated by using Haiku/Sonnet.

## Known fix — log timezone

- Logs timestamp in **UTC**; "today" filters in `digest.py` and `reflect.py` must also use UTC (`datetime.now(timezone.utc).date()`), NOT local `date.today()`. Using local date drops evening-CST activity once UTC rolls to the next day. Fixed 2026-06-01.
- `main.py` forces stdout/stderr to UTF-8 so emoji in any log line can't crash a scheduled run under the cp1252 console.

## Environment notes

- Python: use the **`py`** launcher (3.14.4). The bare `python` command is the Microsoft Store alias and fails — don't use it.
- Virtual env at `.venv/`; run Joe via `.venv\Scripts\python.exe`.
- All deps install cleanly on Python 3.14 (alpaca-py 0.43, anthropic 0.105, praw 7.8, pandas 3.0).
- On Windows, prefer the PowerShell tool over Bash for paths (Bash mangles backslashes). Passing inline Python via `-c` strips double quotes — write a temp script file instead.

## Autonomy — Windows Task Scheduler (updated 2026-06-05)

- **JoeTrader-Cycle** — runs `.venv\Scripts\python.exe -m agent.main cycle`. Trigger: daily 8:35 AM CST, repeats hourly (PT1H) for 7 hours → covers the market session. Self-gates via `is_market_open()` so off-hours/weekend fires exit immediately (near-zero cost, no LLM call).
- **JoeTrader-Cycle-EOD** — runs same cycle command. Trigger: weekdays 2:55 PM CST (5 min before market close). Allows Joe to make last-minute trading decisions based on end-of-day price action. Added 2026-06-05 to increase aggressiveness on timing.
- **JoeTrader-Reflect** — runs `... -m agent.main reflect`. Trigger: weekdays 4:30 PM CST. Skips if no trades that day (guard added to reflect.py).
- **JoeTrader-Digest** — runs `... -m agent.main digest`. Trigger: weekdays 4:35 PM CST. Builds a daily summary (P&L, positions, trades) + a Claude-written narrative + a forward-ready "friends" blurb, posts to **Slack** via incoming webhook (`SLACK_WEBHOOK_URL` in .env). Verified posting (sent: True).
- All verified executing under the scheduler (LastTaskResult 0). Settings: StartWhenAvailable (catches missed runs after sleep), AllowStartIfOnBatteries, 15-min limit.
- **Caveat:** Task Scheduler only fires while the PC is awake. If asleep/off during market hours, that hour is skipped. For true 24/5 independence, migrate to GitHub Actions cron (future).
- Manage: `Get-ScheduledTask JoeTrader-*` | to pause: `Disable-ScheduledTask`; to remove: `Unregister-ScheduledTask`.

## Capital protection & PDT-awareness (rev. 2026-06-02)

**Pattern Day Trading (PDT) is THE key constraint at $10k.** Sub-$25k accounts are capped at **3 day trades / 5 business days**; Alpaca blocks orders that would breach it. On 2026-06-02 day one, Joe hit the wall: the broker bracket stop fired same-day on CRDO (involuntary day trade) + UK manual buy/sell same-day → `daytrade_count=3` → Alpaca then **denied** AVGO/PLTR/AMD/ASTS buys ("trade denied due to pattern day trading protection"). Decided (with Raheel) to **stay $10k and make Joe PDT-aware** (most realistic for a small account).

- **Dropped broker bracket orders.** They auto-sold same-day and created day trades. Buys are now plain **whole-share market orders** (`broker.buy_market`).
- **Stops/targets are checked in-cycle** (−8% / +15% via `unrealized_plpc`), NOT by the broker.
- **Never sell a position opened the same day** (`broker.symbols_bought_today()` via Alpaca fills). Same-day round trips = day trades. Stops/targets/brain-sells only act on **prior-day** positions → swing trades held overnight are never day trades → count stays ~0.
- **No new entries while PDT-locked** (`risk.pdt_locked`, daytrade_count ≥ 3) or after the daily breaker.
- **Tradeoff accepted:** a position that craters the *same day* it's bought is NOT stopped until the next session (day-one downside uncapped). Real small-account reality.
- **Today's hangover:** the 3 day trades keep Joe blocked from *new buys* for ~5 business days until they age off the rolling window; he can still hold/exit existing positions. Going forward the new logic won't accumulate day trades.
- `allow_fractional=False` (whole shares). `broker.exit_position` cancels open orders then liquidates.

## Two dashboard/logging fixes (2026-06-02)

- **Blocked/failed orders no longer shown as buys:** dashboard trades table excludes `status=="error"` rows (e.g. PDT-denied). Added a legend: the decision feed = Joe's *intent*, the Trades table = *executed*.
- **Exits now logged:** with in-cycle (not broker) exits, every sell is placed by Joe's code and logged — fixing the gap where broker-executed stop fills (e.g. CRDO's stop-out) never appeared on the dashboard. (Historical pre-fix exits like CRDO/UK won't retro-appear, but live equity already reflects them.)

## Dashboard (local HTML)

- `agent/dashboard_page.py` + `scripts/build_dashboard.py` generate **dashboard.html** — a self-contained, offline (no CDN) dark "trading terminal" page: KPI cards, inline-SVG equity curve, positions/trades tables, decision feed. Design via ui-ux-pro-max skill (Dark OLED, success-green, mono/sans system fonts). Auto-refreshes at the end of each daily digest run; run the script anytime to refresh manually.

## Hosting — GitHub Pages (2026-06-01)

- Repo: **github.com/reelss/TraderJoe** (public, empty before this). Published **only** `dashboard.html` as `index.html` from a temp folder — nothing else from the vault, no `.env`, no secrets.
- Live URL: **https://reelss.github.io/TraderJoe/** (verified serving). **PUBLIC** — anyone with the link can see Joe's positions/P&L/decisions (no credentials are ever in the HTML).
- **Auto-refreshes every hourly cycle** (changed 2026-06-02): `run_cycle` regenerates + publishes the dashboard in a `finally` block, so the live page tracks positions/P&L through the day (incl. no-trade hours), not just once at close. The 4:35 PM digest also refreshes it. `agent/publish.py` keeps a persistent clone at `~/.traderjoe-pages`, copies `dashboard.html`→`index.html`, **commits only when changed**, pushes via Git Credential Manager. Verified live end-to-end.
- Auth: `gh` is NOT installed; git 2.53 present, user `reelss`, GitHub creds in Git Credential Manager (push + token retrieval via `git credential fill` work non-interactively).

## Strategy upgrade — researched edges encoded (2026-06-02)

Direction (Raheel): make Joe a genuinely smart, edge-driven, money-making trader. Chose to **encode researched strategies now** (vs. backtest-first) — live results are the test; nightly reflection adapts. Honest framing kept: goal is a disciplined, risk-managed *measurable edge*, not a guaranteed money printer.

Three evidence-based edges added (core strategy lives in `brain.py` system prompt = permanent; observations evolve in playbook):
1. **Regime filter** (`agent/regime.py`): only open new longs when SPY > its 200-day SMA. Risk-off → manage/exit only, no new buys. (Trend-following research: big drawdown reduction.) Verified live: SPY 759 vs 682 SMA = risk-on.
2. **12-1 momentum** (Jegadeesh-Titman): `indicators.mom_12_1` = prior-year return ex last month; brain prefers high relative-strength, above-200-SMA names. Added `sma200`/`above_sma200` too. Bars lookback extended 120→420 days.
3. **Volatility sizing & stops (ATR)** in `risk.py`: position sized so entry→stop risk ≈ 1% of equity (`risk_per_trade_pct`), capped at 10%; stop distance = 2.5×ATR clamped to 5–12%. Jumpy names get smaller size + wider stops (directly fixes the CRDO same-minute stop-out). Verified: steady name 5sh/5% stop vs jumpy 4sh/12% stop.

Params in `config.StrategyConfig`. Self-test (`scripts/selftest_core.py`) covers regime gate, PDT lock, vol-sizing, vol-stops. All green.

## Backlog (deferred — pull forward when ready)

- **GitHub Actions migration** — run Joe in the cloud (true 24/5, independent of the PC being awake); also moves dashboard publishing off the local machine. Retire the local Task Scheduler jobs when done.
- **Slack two-way control** — let Raheel command Joe from his phone via Slack ("buy NVDA", "sell UK", "status", "pause"). Joe already posts one-way; this adds reading commands (Slack bot token + a polling checker). Works while PC awake now; fully remote after the cloud migration. (Discussed 2026-06-02, deferred.)

## Status

- 2026-06-01: **Phase 5 complete — Joe is AUTONOMOUS.** Scheduled tasks live; first real cycle fires next market open (Tue 2026-06-02, 8:35 AM CST). 3 orders from the first forced cycle (AVGO/CRDO/MSFT, $800 each) are queued and fill at that open.
- 2026-06-01: **Phase 2 complete — Joe is LIVE and made his first trades.** All connections green. First forced cycle: scanned 131 news tickers → 12 candidates → bought AVGO, CRDO, MSFT ($800 each, 8% conviction-4) and correctly held/avoided overbought parabolics (HPE RSI 86, SMCI RSI 81) and weak-technical names despite positive news (GOOGL, MCHP). Orders ACCEPTED, queued for next open. Reasoning quality is strong and playbook-consistent.
- **Remaining:** Phase 3 (P&L dashboard generator), Phase 4 (reflection loop test), Phase 5 (Windows Task Scheduler for autonomous hourly cycles + nightly reflection).
- Discovery currently runs on Alpaca/Benzinga news only (Finnhub news feed returns 0 tickers — its value is enrichment, not discovery; not yet wired). Reddit + StockTwits disabled.

- 2026-06-01: **Phase 1 complete.** Full scaffold built under `agent/`, deps installed, all modules import, core-logic self-test passes (indicators, stop/take-profit exits, daily breaker, position-size clamping). `scripts/selftest_core.py` validates the offline core; `scripts/check_connections.py` validates the 3 live integrations.
- **Blocked on:** user supplying the 3 API keys in `.env` (copy from `.env.example`) to run the live connection test and first cycle.
- Next phases: 2) first live cycle, 3) P&L dashboard generator, 4) reflection loop test, 5) Task Scheduler setup.
