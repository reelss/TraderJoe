# Joe — Durable Principles

These are Joe's slowly-earned, long-term trading rules. They change rarely — only
when evidence across MULTIPLE trades validates or breaks a rule, never on a single
day's result. The nightly reflection copies this through unchanged in most runs.

## Risk limits (hard — enforced in code)
- Risk ~2% of equity per trade from entry to stop (volatility/ATR sized).
- Max 10% of equity in any one position.
- Max 8 open positions at once.
- ATR-based stops, clamped to a 5%–9% band. No stop wider than 9%.
- Daily loss breaker: halt new buys if the account is down 5% on the day.
- A buy that would push its sector above 30% of total equity is rejected.

## Entry criteria
- Only open new longs when the market regime is risk-on (SPY above its 200-day SMA).
- Only buy names above their own 200-day SMA — trade with the long-term trend.
- Prefer strong 12-1 relative momentum (Jegadeesh-Titman); rank cleanest trends first.
- Don't chase: RSI > 80 or a 20-day return > 50% is parabolic — wait for a base. A name up >10% intraday requires conviction ≥ 4 before any entry.
- Prefer names near 52-week highs (least overhead) and outperforming SPY (rs_vs_spy > 0).
- Volume is a CONVICTION SIZER, not a binary gate: vol ratio ≥ 1.5× = full size;
  0.8×–1.5× = HALF size, allowed only when everything else confirms (above all SMAs,
  MACD bullish, RSI 45–70, sector above its SMA200 and among the RS leaders);
  < 0.8× = no entry (hard floor, not a graduated zone).
  The strict 1.5× bar applies to BREAKOUT entries (new 52-week highs from a base),
  not trend-continuation entries in leading sectors.
  NEVER harden this back into a binary 1.5× gate — the binary version froze the
  account at 93% cash for a week and blocked every A-grade setup (LLY, UNH, CAT,
  July 2026). Loosening or tightening this rule requires blocker-scoreboard evidence.
  **The <0.8× no-entry floor is absolute — it is NOT a graduated zone. Do not rationalize sub-0.8× entries as "graduated rule" applications. The graduated rule only operates between 0.8× and 1.5×. A reasoning note that acknowledges sub-0.8× vol and still submits a buy is a rules violation — the order must not be placed.**
  **News catalysts (earnings beats, etc.) do NOT override the <0.8× hard floor. A catalyst that causes vol to surge intraday may be entered once vol is confirmed ≥0.8× at time of order submission — not in anticipation of vol arriving. KO entry at 0.76× vol (earnings catalyst cited) and MEDP at 0.78× vol are both documented violations. The WAB entry on 2026-07-30 (vol ~0.37× at decision time) is a third candidate violation under review. The fact that vol later rises is irrelevant to order-submission discipline.**
  **Vol-gate scoreboard (updated 2026-07-30):** `vol_gate` shows 1 missed_gain vs 45 correct_pass over 107 passes, avg_return −2.72%, net_verdict = "rule_saving_money." The <0.8× hard floor is strongly and repeatedly validated. No loosening warranted.
- Never open a new position with earnings inside 5 days — that's a coin flip, not a swing.
- **Sector SMA200 veto is absolute and cannot be overridden by any individual signal — not vol confirmation, not RSI, not MACD, not momentum, not news catalyst. If the sector ETF is below its 200-day SMA, no new longs in that sector, period.**
  **Two-close re-entry protocol:** A vetoed sector becomes eligible again only after its ETF closes above the SMA200 for two consecutive sessions. No entries on Day 1 of a potential recovery — only from Day 3 onward.
  *Scoreboard note (updated 2026-07-30): `sector_veto` shows 30 missed_gain vs 162 correct_pass over 460 passes, avg_return −2.17%, net_verdict = "rule_saving_money." The qualitative weight of catastrophic correct_passes (IBM −29%, MU −12% to −17%, SNDK −16% to −31%, AMD −6% to −16%, NVDA −3% to −6%, TSLA −3% to −20%, GS −3% to −4%, META −3% to −11%, GOOG/GOOGL −6% to −11%, NOW −9.9%, WDC −16%, CRWV −19%, DRAM −12%, INTC −14%) substantially outweighs missed_gains in risk-adjusted terms. XLE missed_gains (XOM +10%, CVX +5.6%) and isolated XLK pops (AAPL +6.3%, MSFT +16.6%) are real costs but insufficient to loosen — veto requires two-close protocol, not a momentum rally.*

## Position management
- Trim 50% of a position in ONE order when RSI closes above 75. Do not submit duplicate sell orders on the same RSI signal — verify prior trim execution before placing a second sell.
- After trimming, let the remaining half ride with the ATR trailing stop. Do not re-enter a name that just triggered a trim unless RSI has pulled back to 55–68 AND vol ≥0.8×.
- A position entered via a documented rules violation (sub-0.8× vol, sector veto,
  below SMA200) is exited at the next available opportunity regardless of current
  P&L. Do not hold rule-violating positions.

## Exit discipline
- Ladder the stop up as a position works: breakeven once it peaks at +3.5%,
  lock 2% profit once it peaks at +5%. Above +7% it trails, exiting only on a
  3% giveback from the peak. (Recalibrated 2026-07-30: the prior 7.5%/10%/15%
  gates never fired once across 54 trades — the ladder was dead code.)
- **Let winners run — the single biggest measured leak.** Every winner in the
  first 54 trades was cut by discretion at +0.4% to +5.0% while losers ran to
  −2.2% avg, holding the win/loss ratio at 1.28x against a 71% win rate. A
  winner up 0–5% is NOT sold on discretion below conviction 4; the ladder
  already protects it. Only a real thesis break (sector veto, SMA200 trend
  break, invalidating catalyst) justifies cutting a modest winner early.
- Overnight gap risk is real: a resting GTC broker stop backs every prior-day
  position, because the hourly cycle cannot react to a gap-down at the open.
  (AVGO closed −14% against a 9% stop ceiling on 2026-06-04 for exactly this.)
- Cut losers at the ATR stop. Recycle stale dead-money positions (21d flag, 35d hard).
- After a stop-out, respect the 5-day re-entry cooldown — don't buy the same weakness twice.
- Before any trim or sell, verify current open qty and that no pending order already
  exists for that symbol. One order per trigger, then wait for fill confirmation.

## Conviction & sizing
- Conviction floor: a buy needs a clear multi-signal thesis (regime + trend +
  momentum, not extended). Default to HOLD when the edge is unclear — doing
  nothing is a valid trade.
- Cut new-position size in elevated VIX (20–25); no new longs in fear (VIX > 25).
- Tighten stops and trim targets within 2 days of a major macro event (Fed/CPI/NFP).

## PDT rules (sub-$25k account)
- Never sell a position the same day it was opened (same-day round trip = a day trade).
- No new buys once the day-trade limit (3 per 5 business days) is hit.
- Think in multi-day-to-multi-week swings, never intraday.

## Diversification & deployment
- Spread risk across sectors — correlated positions move together and amplify losses.
- Idle cash in a risk-on regime is a DECISION with an opportunity cost, not a neutral
  default. Under-deployment must be justified by naming the specific blocking rule —
  and that rule must be earning its keep on the blocker scoreboard. Half-size entries
  in leading sectors beat 90% cash waiting for a perfect print. Target ~50% deployed.
