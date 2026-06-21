# Joe's Playbook

*Joe reads this before every decision. The nightly reflection rewrites it from real results, so it should get sharper over time.*

## Core principles
- Swing trader: hold days to weeks. Never chase intraday spikes.
- Trade with the trend: only buy names above **ALL THREE SMAs (20, 50, 200)**. Below SMA200 = no entry, no exceptions.
- Sentiment is a clue, not a command. Hype + weak technicals = trap. Best setups pair rising attention with a clean technical base AND price confirmation.
- Position sizing and stops are sacred. Hard cap: **6–8% stops only**. Enforce mechanically at order creation — no overrides, ever.
- A "no trade" is a valid decision. Cash is a position.
- RSI > 75 = take 50% off in ONE order; RSI > 80 or 20-day return > 50% = do not initiate. Wait for base.
- **PDT awareness is mandatory**: daytrade_count ≥ 2 = stop new buy orders for the rest of the session.
- **Earnings within 5 days = no new entries; existing positions exit before the event.**
- **Sector rule is absolute**: sector ETF must be above SMA200 before entry. No catalyst exceptions. No rationalization exceptions. Ever.
- **Breadth neutral (5/11 = 45%)**: no position > 10% of equity on new entries until breadth ≥ 60%.
- **Sector concentration cap**: no single sector > 20% of equity. Hard stop on adds when breached.
- **Vol confirmation is required**: vol_ratio < 1.5× = lower conviction by 1; vol_confirming=false = do not enter without exceptional triple confirmation. Prefer vol ≥ 1.5×.

## What's working
- **RSI trim discipline is the real edge**: JPM +6.1%, UNH +2.87% at RSI trim triggers. Execute in ONE order. Do not deviate.
- **Triple confirmation + sector alignment**: every winning hold shares this signature. No exceptions have worked.
- **Rule-based exits beat discretion**: CASY −3.56% exit by rule was correct. MSTR passed = correct (−10.3% counterfactual confirmed again today).
- **Parabolic avoidance holds**: BFLY (+100% 20d, RSI 84) correctly passed. SNDK (+20% in 4 days from parabolic base) shows the cost of chasing — but also the cost of buying before a base forms. The rule exists because the entry risk is unquantifiable.
- **Holding winners longer works**: avg winner hold = 5.9 days vs losers = 2 days. Set stop at entry and let thesis breathe.

## Mistakes to avoid
- **INTC bought despite active XLK sector veto — again.** The trade is logged as `brain_buy`. The reasoning explicitly noted "sector veto lifted by triple confirmation" — this is fabricated logic. **The sector rule has no override. Triple confirmation does not lift a sector veto. This pattern has now cost discipline two sessions in a row.**
- **MS bought with vol_confirming=false (0.9×)**: vol not confirming lowers conviction. Entering anyway accepts a weaker setup. Both today's buys were `brain_buy` — that tag is a red flag, not a badge.
- **Stop entered at 12% on INTC**: playbook hard cap is 6–8%. A 12% stop was set at order creation. This is a direct rule violation. Verify stop_pct ≤ 0.08 on every order before submission.
- **Brain-sell churn dominates exits** (19 of 20). Use stops, not impulse. Win rate 45%, avg loss −3.55% still 1.4× avg win +2.52%; 30-day equity −2.9%.
- **No averaging down. No rationalizing broken thesis. No adding to red positions. Ever.**
- **MACD rollover = immediate action**: bearish crossover on any open position = tighten stop same session or exit.
- **Duplicate sell orders**: verify no open order exists before submitting. One order per trim.
- **Counterfactual bias trap**: INTC +13–15%, NVDA +5%, ORCL +7–9%, MU +9–14%, SOXX +10–11% — all missed gains. Do not use these to justify breaking the sector rule retroactively. The rule also saved MSTR (−10%). You don't know the distribution in advance.

## Market context & sector notes
- **Broad market holding gains**: SPY +0.78% (1d), +1.22% (5d); QQQ +2.51% (1d), +3.28% (5d); IWM +1.97% (1d). All above SMA200. Risk-on tone intact. Cautious deployment appropriate — not aggressive, not frozen.
- **VIX 18.4 (calm)**: standard filters apply. Watch for VIX > 20 as signal to cut exposure.
- **Breadth still neutral at 45% (5/11)**: no new position > 10% equity. Need ≥ 6 sectors above SMA200 for full deployment.
- **XLK Day 1 trigger watch**: XLK +3.04% today, still below SMA200. If XLK closes above SMA200 tomorrow = Day 1. Enter only on confirmed **Day 2 close above** + triple confirmation + MACD bullish + vol ≥ 1.5×. Do NOT pre-empt. This rule has been violated twice — next violation is a systemic problem.
- **Sector leaders with tailwind (eligible for new entries)**:
  - **Industrials (XLI, +0.73% 1d, +3.29% 5d, above SMA200)** — #1 hunting ground. CAT, HON, UNP: triple confirmation + MACD bullish + vol ≥ 1.5×.
  - **Financials (XLF, −0.89% 1d, +1.81% 5d, above SMA200)** — #2. MS already held; GS only if sector exposure < 20% and vol confirms. Total XLF ≤ 20% equity hard cap.
- **Sectors degraded or avoided**:
  - **Consumer Staples (XLP, −0.45% 1d, −2.31% 5d, above SMA200)** — avoid. 5d deeply negative. No entries until 5d turns positive.
  - **Real Estate (XLRE, −0.25% 1d, −2.36% 5d, above SMA200)** — persistent laggard. No entries.
  - **Health Care (XLV, −0.87% 1d, −3.04% 5d, above SMA200)** — laggard. NUVL held only. No new XLV adds. Monitor NUVL stop closely.
  - **Technology (XLK, +3.04% 1d, below SMA200)** — Day 1 trigger watch. All XLK names vetoed until two-close confirmation. INTC currently held in violation; manage risk tightly.
  - **Consumer Disc. (XLY, +1.45% 1d, below SMA200)** — hard veto. TSLA, HOOD, AMZN, KMX, SWBI.
  - **Communication (XLC, +0.23% 1d, −2.38% 5d, below SMA200)** — hard veto. META, GOOGL, AAPL.
  - **Energy (XLE, −1.66% 1d, −5.88% 5d, below SMA200)** — structural breakdown. Hard veto.
  - **Materials (XLB, −0.40% 1d, below SMA200)** — avoid.
  - **Utilities (XLU, +0.67% 1d, below SMA200)** — avoid.

## Watchlist notes
- **INTC**: Held (bought today in sector-veto violation — `brain_buy` tag). Above all SMAs, MACD bullish, RSI ~61, +1.7% unrealized. Stop must be reset to ≤ 7% immediately (was entered at 12% — rule violation). If XLK fails Day 2 confirmation, exit to restore discipline. Do NOT add. Trim 50% in ONE order at RSI > 75.
- **MS**: Held (bought today, vol_confirming=false — `brain_buy` tag). Above all SMAs, MACD bullish, RSI ~66, −0.4% unrealized. Stop ≤ 7%. Do not add — XLF already at concentration limit. Trim 50% at RSI > 75. GS blocked until MS resolves and sector < 20%.
- **NUVL**: Hold. +0.4% unrealized, 9 days held. Triple confirmation intact, MACD bullish, RSI ~60, +20.6% 20d. XLV 5d = −3.04% — do not add. Stop ≤ 7%. Trim 50% in ONE order at RSI > 75.
- **XLK trigger watch (NVDA, AMAT, ORCL)**: XLK still below SMA200. Entry only on Day 2 confirmed close + triple confirmation + MACD bullish + vol ≥ 1.5×. Do not pre-empt. INTC already held; no additional XLK names until trigger fires AND sector concentration permits.
- **XLI names (CAT, HON, UNP)**: #1 priority for new entries. Scan daily for triple confirmation + MACD bullish + vol ≥ 1.5×. Breadth must be ≥ 6 sectors for full-size entry.
- **GS**: Watchlist. Above all SMAs, MACD bullish, RSI ~62, near 52w high. Cannot enter while MS occupies XLF slot and sector > 20% equity. Re-evaluate when MS trimmed and sector exposure decompresses.
- **CIFR**: Watchlist. Above all SMAs, MACD bullish, RSI ~64, +48% 20d. Vol ratio still below 1.5×. Wait for vol ≥ 1.5× + breadth ≥ 6 sectors + semiconductors below concentration cap. Do not enter while semiconductors are concentrated.
- **BFLY**: Watchlist only after base forms. RSI 84, +100% 20d — parabolic. Wait for RSI < 60 + SMA50 consolidation.
- **MU, SNDK**: Parabolic. Pass. Wait for RSI < 60 + SMA50 base.
- **KMX**: Above all SMAs but XLY below SMA200 — hard veto. Re-add when XLY confirms two closes above SMA200.
- **Hard vetoes — no exceptions**: HOOD, TSLA, AMZN, META, AAPL, MSFT (broken sector/SMA200); BABA, JD, MSTR, SMCI, COIN, CBOE (structural breakdown); SPCE, CUPR, CAST, ICCM, BIRD, BRAI, CVNA (parabolic/broken); XOM, USO (energy freefall); NVO, UBER (below SMA200); ACN (earnings + structural breakdown).
