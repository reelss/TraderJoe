"""Offline self-test of the pure-logic core (no API keys needed).

Validates indicators.snapshot and the risk guardrails with synthetic data.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.indicators import snapshot
from agent.risk import vet_orders, daily_loss_tripped

# --- indicators on a synthetic uptrend ---
n = 120
rng = np.random.default_rng(7)
price = 100 + np.cumsum(rng.normal(0.3, 1.0, n))
df = pd.DataFrame({
    "open": price, "high": price + 1, "low": price - 1,
    "close": price, "volume": rng.integers(1_000_000, 5_000_000, n),
})
snap = snapshot(df)
print("INDICATORS:", {k: snap[k] for k in
                      ["price", "sma20", "above_sma20", "rsi14",
                       "macd_bullish", "ret_5d", "avg_dollar_vol_20d"]})

# --- daily loss breaker ---
acct = {"equity": 10000.0, "last_equity": 10600.0, "cash": 4000.0, "buying_power": 4000.0}
assert daily_loss_tripped(acct) is True, "breaker should trip at -5.7%"
print("daily_loss_tripped (down 5.7%):", daily_loss_tripped(acct))

# Positions: WIN held since a prior day & up 16% (take-profit), OLD down 9%
# (ATR stop ~7.5%), FRESH bought today down 9% (must NOT sell — same-day = day trade).
# Fields mirror live broker.positions(): symbol, qty, avg_entry, current_price,
# market_value, unrealized_pl, unrealized_plpc. Synthetic values are kept
# internally consistent (current_price = avg_entry * (1 + plpc)).
positions = [
    {"symbol": "WIN", "qty": 4, "avg_entry": 100.0, "current_price": 116.0,
     "market_value": 464.0, "unrealized_pl": 64.0, "unrealized_plpc": 0.16},
    {"symbol": "OLD", "qty": 2, "avg_entry": 80.0, "current_price": 72.8,
     "market_value": 145.6, "unrealized_pl": -14.4, "unrealized_plpc": -0.09},
    {"symbol": "FRESH", "qty": 1, "avg_entry": 50.0, "current_price": 45.5,
     "market_value": 45.5, "unrealized_pl": -4.5, "unrealized_plpc": -0.09},
]
opened_today = {"FRESH"}
acct2 = {"equity": 10000.0, "last_equity": 10000.0, "cash": 4000.0,
         "buying_power": 4000.0, "daytrade_count": 0}
# tech: price + atr_pct drives volatility sizing/stops. NVDA steady (2% ATR),
# VOLA jumpy (5% ATR) -> VOLA should size smaller and get a wider stop.
tech = {
    "WIN": {"price": 100.0, "atr_pct": 0.03}, "OLD": {"price": 80.0, "atr_pct": 0.03},
    "FRESH": {"price": 50.0, "atr_pct": 0.03},
    "NVDA": {"price": 200.0, "atr_pct": 0.02},
    "VOLA": {"price": 200.0, "atr_pct": 0.05},
    "PRICEY": {"price": 1500.0, "atr_pct": 0.02},
}
decisions = [
    {"symbol": "NVDA", "action": "buy", "target_pct": 0.10, "conviction": 4, "reasoning": "x"},
    {"symbol": "VOLA", "action": "buy", "target_pct": 0.10, "conviction": 4, "reasoning": "v"},
    {"symbol": "PRICEY", "action": "buy", "target_pct": 0.10, "conviction": 5, "reasoning": "dear"},
]
# Start each run from a clean peaks store so the trailing-exit assertions below
# are deterministic regardless of prior live state.
from agent.config import PEAKS_PATH
PEAKS_PATH.write_text("{}", encoding="utf-8")

orders = vet_orders(decisions, acct2, positions, tech, opened_today, risk_on=True)
print("VETTED:", [(o["symbol"], o["side"], o.get("qty"), o.get("reason")) for o in orders])
# T1-D: a fresh +16% winner with no prior peak has NOT given back 6% — it HOLDS
# (the old hard +15% take-profit was replaced by a trailing stop above +15%).
assert not any(o["symbol"] == "WIN" for o in orders), "winner up 16% with no giveback should run, not exit"
assert any(o["symbol"] == "OLD" and o["reason"] == "stop_loss" for o in orders)
assert not any(o["symbol"] == "FRESH" for o in orders), "same-day position must not be sold (PDT)"
nvda = next(o for o in orders if o["symbol"] == "NVDA")
vola = next(o for o in orders if o["symbol"] == "VOLA")
# T1-A deployment floor: this account is mostly cash (~6.5% deployed), so sizing is
# scaled toward the 10% position cap. Both NVDA and VOLA should clear $500 value.
assert nvda["qty"] * tech["NVDA"]["price"] >= 500, "under-deployed account should size up toward cap"
assert vola["qty"] * tech["VOLA"]["price"] >= 500, "under-deployed account should size up toward cap"
assert vola["stop_pct"] > nvda["stop_pct"], "jumpier VOLA should still get a wider stop"
assert not any(o["symbol"] == "PRICEY" for o in orders), "above position cap should be skipped"
print(f"  deploy-floor sizing: NVDA {nvda['qty']}sh stop {nvda['stop_pct']:.0%} | "
      f"VOLA {vola['qty']}sh stop {vola['stop_pct']:.0%}")

# T1-D: trailing take-profit fires when a 15%+ winner gives back >= 6% from peak.
PEAKS_PATH.write_text('{"WIN": 0.24}', encoding="utf-8")  # WIN peaked at +24%, now +16% (gave back 8%)
orders_tp = vet_orders(decisions, acct2, positions, tech, opened_today, risk_on=True)
assert any(o["symbol"] == "WIN" and o["reason"] == "trailing_take_profit" for o in orders_tp), \
    "15%+ winner that gave back 6% from peak should trailing-exit"
PEAKS_PATH.write_text("{}", encoding="utf-8")  # reset
print("  trailing take-profit fires on 6% giveback from peak. OK")

# Volatility STOP relationship is the durable volatility signal: jumpier VOLA gets
# a wider stop than steady NVDA. (Position-quantity sizing is frequently bounded by
# the 10% position cap under 2%-risk, so stop width — not qty — is the reliable test.)
assert vola["stop_pct"] > nvda["stop_pct"], "jumpier VOLA should get a wider stop"
assert nvda["stop_pct"] <= 0.09 and vola["stop_pct"] <= 0.09, "stop ceiling must hold at 9%"
print(f"  stop ceiling enforced (<=9%): NVDA {nvda['stop_pct']:.0%} | VOLA {vola['stop_pct']:.0%}")

# Regime risk-off: no new buys, but exits still run.
roff = vet_orders(decisions, acct2, positions, tech, opened_today, risk_on=False)
assert not any(o["side"] == "buy" for o in roff), "risk-off must block new buys"
assert any(o["side"] == "sell" for o in roff), "exits still run when risk-off"

# PDT-locked: no new buys, prior-day exits still allowed.
locked = vet_orders(decisions, {**acct2, "daytrade_count": 3}, positions, tech, opened_today, True)
assert not any(o["side"] == "buy" for o in locked), "PDT-locked must block new buys"
assert any(o["side"] == "sell" for o in locked), "prior-day exits still allowed when locked"
print("Regime gate + PDT lock both block buys, exits still run. CORE LOGIC OK")
