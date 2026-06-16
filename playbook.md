# Joe's Playbook

*Joe reads this before every decision. The nightly reflection rewrites it from real results, so it should get sharper over time.*

## Core principles
- Swing trader: hold days to weeks. Never chase intraday spikes.
- Trade with the trend: only buy names above **ALL THREE SMAs (20, 50, 200)**. Below SMA200 = no entry, no exceptions — not for turnarounds, not for "almost there."
- Sentiment is a clue, not a command. Hype + weak technicals = trap. Best setups pair rising attention with a clean technical base AND price confirmation.
- Position sizing and stops are sacred. Hard cap: **6–8% stops only**. Enforce mechanically at order creation — no overrides, ever.
- A "no trade" is a valid decision. Cash (~83%) is a position.
- RSI > 75 = take 50% off in ONE order; RSI > 80 or 20-day return > 50% = do not initiate. Wait for base.
- **PDT awareness is mandatory**: daytrade_count ≥ 2 = stop new buy orders for the rest of the session.
- **Earnings within 5 days = no new entries; existing positions exit before the event.**
- **Sector rule is absolute**: individual stock above all three SMAs is necessary but not sufficient — sector ETF must also be above SMA200 before entry. No exceptions.
- **Breadth neutral (5/11 = 45%)**: no position > 10% of equity on new entries until breadth ≥ 60%.

## What's working
- **RSI trim discipline is the real edge**: JPM trimmed +6.1–6.2% at RSI 78.5; UNH trimmed +2.87% at RSI 77. Both executed correctly in one order. This is the highest-return repeatable action in the playbook — do not deviate.
- **Triple confirmation + sector alignment**: every winning hold (JPM, UNH, NUVL, CASY) shares this signature. No exceptions have worked.
- **Rule-based exits beat discretion**: ROKU exited at −0.86% by rule. Sector filter saved a potential −7%+ stop.
- **Parabolic avoidance**: WDC, MU, SNDK all passed correctly despite massive missed gains. The rule exists because catching the top of a parabolic costs more than missing the move.
- **Sitting in cash (~83%)**: broad market pulled back today (SPY −0.6%, QQQ −1.9%); holding cash was correct. Do not force trades into weakness.

## Mistakes to avoid
- **Duplicate sell orders**: JPM generated two sell orders (2 shares + 1 share) for the same 50% trim. At order creation, verify no open order exists for that symbol before submitting. One order, one trim.
- **Brain-sell churn is still the dominant exit reason** (18 of 19 exits). Good exits (RSI trim, sector violation) are labeled brain-sells in the log — that's fine. But discretionary small-loss exits are not. Use stops, not impulse.
- **Win rate 47.4%, avg loss (−3.55%) still 1.4× avg win (+2.52%)**: improving but not yet positive expectancy. Fix: hold winners to RSI trim triggers; stop exiting green positions early.
- **Avg hold days for losers = 0**: stops are cutting too fast OR positions aren't being held long enough to work. Set the stop right at entry and let the trade breathe to its thesis.
- **No averaging down, no rationalizing broken thesis.** No adding to red positions. Ever.
- **MACD rollover = immediate action**: bearish crossover on any open position = tighten stop same session or exit.
- **XLK pulled back −2.8% today**: the two-close trigger did NOT fire. Do not pre-empt it. NVDA, GOOGL, MSFT remain vetoed until XLK confirms.

## Market context & sector notes
- **Broad market softened**: SPY −0.6% (1d), QQQ −1.9% (1d), IWM −0.87% (1d). All still above SMA200 and positive on 5d. This is a one-day pullback in an uptrend, not a reversal — but caution warranted.
- **VIX 16.2 (calm, unchanged)**: no regime change. Standard filters apply.
- **Breadth still neutral at 45% (5/11)**: do not aggressively deploy cash. No new position > 10% equity until ≥6 sectors clear SMA200.
- **Sector leaders with tailwind (eligible for new entries)**:
  - **Financials (XLF, +1.47% 1d, +3.6% 5d, above SMA200)** — #1 hunting ground. JPM partially trimmed; remaining half hold. GS/MS: require MACD bullish crossover + vol ≥1.5×. Total XLF exposure ≤20% equity.
  - **Industrials (XLI, +0.65% 1d, +2.4% 5d, above SMA200)** — #2. Primary new-entry candidates: CAT, HON, UNP. Need triple confirmation + MACD bullish + vol ≥1.5×.
  - **Consumer Staples (XLP, +0.13% 1d, +1.8% 5d, above SMA200)** — #3. Stabilizing. COST, PG, KO, WMT eligible if triple confirmation intact. CASY held here; monitor.
  - **Real Estate (XLRE, +0.24% 1d, +0.3% 5d, above SMA200)** — valid but sluggish 5d. Require full confirmation before entry; low priority.
  - **Health Care (XLV, flat 1d, −1.05% 5d, above SMA200)** — lagging and 5d negative. Joe holds UNH + NUVL (~15%). No new XLV adds until below 10% exposure.
- **Sectors to avoid**:
  - **Technology (XLK, −2.79% 1d, +3.1% 5d, below SMA200)** — pulled back hard today. Two-close trigger NOT active; reset the clock. NVDA, GOOGL, MSFT, ORCL remain on watchlist but vetoed. Do NOT pre-empt.
  - **Consumer Disc. (XLY, −0.09% 1d, below SMA200)** — avoid. TSLA, HOOD, AMZN hard vetoed.
  - **Communication (XLC, +0.12% 1d, below SMA200)** — avoid. Zero exposure; no re-entry until 2 consecutive closes above SMA200.
  - **Energy (XLE, −0.34% 1d, −3.54% 5d, below SMA200)** — structural breakdown. Hard veto.
  - **Materials (XLB, +0.42% 1d, below SMA200)** — bouncing but unconfirmed. No entries.
  - **Utilities (XLU, +0.72% 1d, below SMA200)** — avoid.

## Watchlist notes
- **JPM**: Hold remaining ~50% position. +6.1% locked on trimmed half. RSI was 78.5 at trim; monitor current RSI — if it re-extends above 75, trim again (50% of remainder in one order). Triple confirmation intact, MACD bullish, XLF tailwind. Stop ≤6% on remainder. No new XLF adds until total XLF < 15% equity.
- **UNH**: Hold 1 share post-trim. +2.87% locked. RSI ~77 — if RSI stays >75 tomorrow, execute another 50% trim in ONE order. Triple confirmation intact. XLV is lagging (−1.05% 5d); do not add. Stop at breakeven.
- **NUVL**: Hold. +0.28% unrealized. Triple confirmation, MACD bullish, RSI ~62. HC at ceiling; no new adds. Stop ≤7%. Trim 50% at RSI >75.
- **CASY**: Hold. −2.4% unrealized (deteriorating). Triple confirmation intact, MACD bullish, RSI ~65, vol ratio 0.26 (very weak). Yellow flag: if vol stays dry and price breaks SMA20, exit same session. Stop hard at ≤7%. Do not add.
- **ALAB**: Watchlist. Above all SMAs, strong momentum (+73% 20d), near 52w high. MACD bearish — wait for MACD bullish crossover + vol ≥1.5×. XLK sector must also confirm (2-close rule) before entry. High priority for the moment XLK clears.
- **CIFR**: Watchlist. Above all SMAs, MACD bullish, strong momentum (+42% 20d). Vol ratio 0.55 — too weak to enter now. Wait for vol ≥1.5× + breadth ≥6 sectors. Breadth-neutral size cap (≤10% equity) applies.
- **XLK trigger watch (NVDA, ALAB, GOOGL, ORCL)**: XLK pulled back −2.8% today — two-close trigger reset to zero. If XLK closes above SMA200 on Day 1, prep the scan. Enter only on Day 2 confirmed close. MU remains parabolic — wait for RSI <60 + SMA50 base regardless of sector.
- **XLI names (CAT, HON, UNP)**: Primary new-entry candidates. Scan for triple confirmation + MACD bullish + vol ≥1.5×. XLI is the cleanest eligible sector right now.
- **XLF names (GS, MS)**: Secondary. Require MACD bullish crossover. Total XLF ≤20% equity.
- **XLP names (COST, PG, KO, WMT)**: Third priority. RSI 50–70 + vol ≥1.5× required at entry.
- **Hard vetoes — no exceptions**: HOOD, TSLA, AMZN, META, MSFT (broken sector or SMA200); BABA, JD, MSTR, SMCI, COIN, CBOE (below all SMAs, structural breakdown); SPCE, CUPR, CAST (parabolic/broken); XOM, USO (energy freefall).
- **WDC**: Still parabolic (+36% 20d). Pass. Wait for pullback to RSI <60 + SMA50 base.
