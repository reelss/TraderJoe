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
- Don't chase: RSI > 80 or a 20-day return > 50% is parabolic — wait for a base.
- Prefer names near 52-week highs (least overhead) and outperforming SPY (rs_vs_spy > 0).
- Volume should confirm the move; a breakout on weak volume is drift, not conviction.
- Never open a new position with earnings inside 5 days — that's a coin flip, not a swing.

## Exit discipline
- Below +15%: ladder the stop up — breakeven once a position peaks at +7.5%,
  lock 5% profit once it peaks at +10%.
- At/above +15%: let it run on a trailing stop; only exit if it gives back 6% from
  its peak gain. Do NOT cap winners at +15%.
- Cut losers at the ATR stop. Recycle stale dead-money positions (21d+ flag, 35d hard).
- After a stop-out, respect the 5-day re-entry cooldown — don't buy the same weakness twice.

## Conviction & sizing
- Conviction floor: a buy needs a clear multi-signal thesis (regime + trend + momentum,
  not extended). Default to HOLD when the edge is unclear — doing nothing is a valid trade.
- Cut new-position size in elevated VIX (20–25); no new longs in fear (VIX > 25).
- Tighten stops and trim targets within 2 days of a major macro event (Fed/CPI/NFP).

## PDT rules (sub-$25k account)
- Never sell a position the same day it was opened (same-day round trip = a day trade).
- No new buys once the day-trade limit (3 per 5 business days) is hit.
- Think in multi-day-to-multi-week swings, never intraday.

## Diversification
- Spread risk across sectors — correlated positions move together and amplify losses.
- When capital is idle in a risk-on regime with room to add, deploy toward the target
  (about 50% of equity) rather than letting the risk formula leave size tiny.
