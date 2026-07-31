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

- 2026-07-06: **Learning-ratchet fix shipped.** Diagnosis: Joe froze at 93% cash because nightly reflection hardened the soft volume-confirmation preference into a binary "vol <1.5× = no entry" gate (blocked 76 of last 120 decisions, including every A-grade setup: LLY/UNH/CAT). Root cause: Joe only learned from mistakes made, never opportunities missed, so rules only ratcheted stricter. Fixes: (1) volume is now a **graduated conviction sizer** (≥1.5× full size, 0.8–1.5× half size on clean setups, <0.8× none) in brain.py + principles.md; (2) **blocker scoreboard** in counterfactual.py — every pass logs which rule blocked it, resolved outcomes aggregate per-rule cost/savings, fed to reflection; (3) **anti-ratchet guardrail** in reflect.py — rules may only harden with scoreboard evidence, must loosen when a rule is provably costing money; (4) deployment % vs 50% target surfaced to brain (cycle.py regime) and reflection as an accountable decision. about.html updated (rules 21–24, LEDGER learning loop) and published. Sector SMA200 vetoes remain absolute.
- 2026-07-06: **Decision model upgraded Haiku → Sonnet 4.6** (`config.MODELS.decision_model`) — hourly judgment quality > the ~3× API cost delta. **Weekly process scorecard** added: `perf_stats.process_scorecard()` grades deployment ≥50%, win rate ≥45%, win/loss ≥1.5×, return vs SPY; graded as section 0 of the Sunday strategy review and rendered in the weekly Slack summary. Process goals over P&L goals — no dollar targets.
- 2026-07-06: **Watchlist discovery source shipped** (`agent/sources/watchlist.py`, weight 1.1): nightly reflection now ends the playbook with a machine-readable `WATCHLIST: TICK, TICK` line (fallback: heuristic parse of bolded Watchlist-notes bullets, veto lines excluded); those names are injected into every cycle's candidates AND guaranteed a seat past the 12-candidate cap (cycle.py keeps watchlist-source names trimmed by the cap). Closes the loop where Joe named LLY/UNH as Priority #1 all week but never saw them unless news mentioned them. Verified live: 18 candidates, brain individually evaluated LLY/UNH/CAT/V with rule-specific reasons. Same day: first buy under new rules — NVS (XLV leader, 6sh, 5.4% stop) + RIVN veto-violation exit at +5%.
- 2026-07-09: **Outage: Anthropic API credit exhaustion, ~4 hourly cycles missed (13:35–17:35 CST).** Root cause: Claude.ai Team "usage credits" ($7.72, for chat-app seat overage) is a SEPARATE billing pool from the developer Console API balance that `ANTHROPIC_API_KEY` draws against — the Console balance was actually $0. Confusing because both are labeled "usage credits" but live on different pages (claude.ai Team settings vs console.anthropic.com Billing). Raheel added credits to the correct Console balance; verified live (test API call + forced cycle both succeeded, Joe fully operational). **Watch item:** yesterday's decision-model upgrade Haiku→Sonnet (~3x cost/call, 7 calls/day) likely accelerated this burn — worth monitoring Console balance more proactively if it recurs.

- 2026-07-30: **Real-money readiness audit — verdict: NOT YET.** 54 trades since 6/2. Post-fix (7/6+) is genuinely better: 71% win rate, +1.34%/trade vs pre-fix 53%/-0.35%. Joe -1.16% since inception vs SPY -2.35% (beat benchmark by 1.2pp) but still absolute-negative. Blockers to real money: sample far too small (24 post-fix trades); VIX never left 15-17 so regime/fear filters are untested; only 1 stop_loss ever fired in 54 trades (risk machinery unproven); AVGO closed -14% vs a 9% stop ceiling via overnight gap; the 7/9 API outage left positions unmanaged 4 hours. Gates before revisiting: 100+ trades, one positive quarter absolute, a VIX>25 event survived, multiple stops firing correctly, gap hole closed, one month clean uptime. Est. 3-6 more months paper.
- 2026-07-30: **Two fixes shipped from that audit.** (1) RETURNS — the profit ladder was DEAD CODE: zero of 54 trades ever reached the old +7.5% breakeven gate, so every winner was cut by brain discretion at +0.4% to +5.0% while losers ran to -2.2% (win/loss ratio 1.28x despite 71% win rate). Recalibrated to Joe's actual distribution (breakeven +3.5%, 2% lock at +5%, trail at +7% on 3% giveback) and added a let-winners-run guard in `risk.py`: a brain sell of a winner up 0-5% now requires conviction >=4, else it's held. (2) RISK — `_sync_protective_stops()` in cycle.py places resting GTC broker stops on all prior-day positions (PDT-safe), closing the overnight gap hole. Ratchet invariant: stops only ever tighten, never widen, so degraded technicals can't silently reduce protection. Verified live 5/5 positions protected.
- 2026-07-30: **CRITICAL BUG FOUND + FIXED — nightly reflection was silently corrupting principles.md.** The 7/29 reflection hit its 4,000-token ceiling mid-sentence and wrote a truncated file that had lost the ENTIRE exit-discipline, conviction-sizing, PDT, and deployment sections. The 20-line guard passed (41 lines > 20) so it overwrote the good file — Joe traded without exit/PDT rules in his system prompt. Fixes: `stop_reason == "max_tokens"` check refuses to persist truncated output (+ Slack alert); `MODELS.reflection_max_tokens = 12_000`; structural guard requires all of Risk limits/Entry criteria/Exit discipline/PDT rules headings present or the write is rejected; reflection prompt now demands the complete file every run and one-line scoreboard notes. principles.md restored by hand. **Lesson: line-count guards do not catch semantic loss — check for required structure.**
- 2026-07-31: **Deployment was NOT tactical intelligence — it was structural under-investment.** Tested directly: correlation between deployment % and SPY 5-day direction = **-0.13** (Joe deployed 22.5% avg when SPY rising vs 26.1% when falling — backwards). Root cause: every entry gate is trend-LAGGING (price SMA200, sector SMA200, MACD), so they stay shut through the first leg of any recovery; week of Jul 5 SPY +1.12% and Joe was 7.6% deployed. Separately confirmed the SELECTION is genuinely good (blocker scoreboard: every rule "rule_saving_money" across 1,500+ resolved passes; deployed capital +2.45% vs SPY -1.28%). Conclusion: good stock selection, poor capital allocation — the SPY outperformance is substantially flattered by being under-invested in a down market, and the same machinery would badly lag a rising one.
- 2026-07-31: **Sector-ETF fallback shipped** to fix that. `sector_rs.py` now also emits the top-2 leading sectors' own ETFs (weight 1.0, reuses bars already fetched — no extra API calls); ETFs are less noisy than constituents so more clear SMA200 as breadth improves, making deployment scale WITH the market by construction. Guarded: (a) `sectors.py` `etf_overlaps_holdings()` + `is_sector_etf()` use per-ETF industry-keyword sets to detect that e.g. XLV and a held MEDP/THC are one bet in two buckets — the granular Finnhub industry labels mean the 30% cap alone would NOT catch this; (b) hard veto in `vet_orders` rejects an ETF buy overlapping any held name; (c) ETFs still face SMA200/vol/earnings/sector-cap gates; (d) brain prompt ranks single names first, ETF only to close a deployment gap. Also needed a **guaranteed candidate seat** (cycle.py) — ETFs ranked 33rd/34th on attention and were always cut by the 12-candidate cap, same failure mode as the watchlist source. Verified live: XLF correctly held on marginal MACD, XLY correctly vetoed below SMA200.
- 2026-07-31: **SPY benchmark added permanently to the dashboard** — `_spy_benchmark()` in dashboard_page.py normalizes SPY buy-and-hold to the same $10k start, renders as a dashed line sharing one y-axis with Joe's curve, plus a running "Joe +X pts vs S&P 500" label. Verified 285 aligned points, both series in bounds.
- 2026-07-31: **Open issue (not yet fixed): pending buy orders are not accounted for across cycles.** `vet_orders` reads `account['cash']`, which Alpaca does not decrement until fill — so consecutive cycles can over-commit the same cash. Surfaced when repeated `--force` test cycles queued AAPL then RTX+DLR; the later cycle had reversed the AAPL call ("wait for XLK two-close confirmation") so the stale order was cancelled manually. Low production risk (Joe only cycles during market hours where market orders fill in seconds) but real on a halt/illiquid fill. Cheap fix: subtract open-buy notional from available cash in vet_orders.
- 2026-07-31: **Daily self-audit shipped** (`agent/audit.py`, `python -m agent.main audit`; auto-runs at the end of the daily digest and the Sunday weekly review). Motivation: every serious problem found this week had been running SILENTLY — truncated principles, dead exit ladder (54 trades), deployment ignoring the market (2 months), API credits hitting zero, swallowed stop-placement errors. Joe reported P&L in detail and nothing about his own health. Checks (CRITICAL vs WARN, posted to Slack only when something fires): principles.md section integrity + truncation + >25% shrink vs high-water mark; every prior-day position has a resting broker stop; exit ladder has fired within the last 25 exits; deployment vs target; API credit runway; FATAL errors and zero-cycle days; any blocker rule flipped to "costing money"; attribution pipeline alive. **Detectors were themselves tested against deliberately broken states** — the first truncation check FAILED on the real 7/29 case (that file ended `'(sub-0.'`, a decimal point, so an "ends with a period" heuristic passed it); replaced with unclosed-bracket detection + line-count shrink, which now catch it two independent ways. First live run immediately flagged the two known-real gaps: no billing checkpoint, and the ladder not firing.
- 2026-07-31: **Source attribution + conviction calibration shipped.** (1) Every buy now logs its discovery source(s) in trades.jsonl (`cycle.py`), and `attribution.compute_attribution()` gained `by_source` (win rate + avg return per source, with a `reliable` flag at >=8 trades so the weekly review can't read noise) — source weights in SourceConfig were judgement calls with zero evidence until now; historical trades show `held_or_unknown` since tagging starts from today. (2) `_calibration()` computes Spearman rank correlation between entry conviction and realized return. **Result on 54 trades: rho = -0.352 — conviction is INVERTED.** conv 3: 39 trades, 69% win, +1.13% avg. conv 4: 15 trades, 40% win, **-1.50%** avg (and held 8.4d vs 4.7d — he sits in bad trades longer). Root cause hypothesis: conviction is not used for position sizing at all, only as a PERMISSION TOKEN for three riskier actions (buy an already-extended name, hold through earnings, cut a modest winner all require conviction>=4) — so 4 is the number Joe reaches for to unlock a marginal setup, not a confidence signal. Calibration is now fed back to the brain in-cycle (`brain._calibration()`) and checked by the daily audit. Note: scipy is NOT installed and pandas' spearman silently requires it — implemented `_spearman()` by hand (verified against perfect +1/-1, a Sd2=4 case = 0.8, and a tie case).
- 2026-07-31: **Pending-order double-commit bug FIXED** (was flagged as open earlier same day, then bit twice). Alpaca leaves `cash` untouched until fill, so consecutive cycles spent the same dollars — and since the 10% position cap and the no-pyramiding rule both key off FILLED positions, RTX stacked to 8 shares (~17% of equity) across two cycles. Fix: `broker.pending_buys()` returns unfilled buy qty per symbol; `vet_orders` now reserves their notional from available cash AND rejects any buy for a symbol with an order already pending. Verified live: "Reserved $2,780 for 3 unfilled buy order(s)" + "rejected BUY DLR — already has an unfilled buy order pending".
- 2026-07-31: **Bug fixed: `scripts/selftest_core.py` was clobbering live stop state.** `vet_orders` prunes hwm/peaks to whatever symbols it is handed, so every selftest run replaced all real positions' high-water marks with the test fixtures (WIN/OLD) — silently discarding each ratcheted stop (THC was holding a +2% profit lock at peak +9.35%; it would have reverted to a base ATR stop, widening real risk). Caught because the files went dirty in `git status` right after committing. Fix: selftest redirects `agent.risk.HWM_PATH`/`PEAKS_PATH` to a tempdir at import time before any vet_orders call, and no longer re-imports the production PEAKS_PATH mid-file. Verified hwm.json byte-identical before/after a full run. **Lesson: tests that exercise risk logic must redirect persisted state — this bit twice in one session.**
