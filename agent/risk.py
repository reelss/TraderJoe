"""Risk guardrails — PDT-aware, regime-gated, volatility-sized.

Encodes researched edges:
  - **Regime gate:** no new longs when the market is risk-off (handled by caller
    passing risk_on=False) — trend research shows this cuts drawdowns.
  - **Volatility sizing (ATR):** each position is sized so the entry-to-stop loss
    is ~`risk_per_trade_pct` of equity. Jumpy names get smaller positions.
  - **Volatility stops (ATR):** the stop distance scales with the name's own ATR
    (clamped), so a volatile stock isn't knocked out by normal noise.
And the PDT rules: never sell a same-day position; no new entries when locked.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from .config import HWM_PATH, LOGS_DIR, RISK, STRATEGY

_TRADES = LOGS_DIR / "trades.jsonl"
_STOP_REASONS = frozenset({"stop_loss", "trailing_stop_profit", "trailing_stop_breakeven"})

# Trailing-stop floor levels (fraction of equity).
_BREAKEVEN_FLOOR = 0.005   # ~0.5% above entry — effectively breakeven
_PROFIT_FLOOR    = 0.05    # protect 5% profit

PDT_DAYTRADE_LIMIT = 3  # day trades allowed per 5 business days under $25k


def daily_loss_tripped(account: dict) -> bool:
    last = account.get("last_equity") or 0.0
    if last <= 0:
        return False
    return (last - account["equity"]) / last >= RISK.daily_loss_breaker_pct


def pdt_locked(account: dict) -> bool:
    return int(account.get("daytrade_count", 0)) >= PDT_DAYTRADE_LIMIT


def _load_hwm() -> dict[str, float]:
    try:
        if HWM_PATH.exists():
            return json.loads(HWM_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_hwm(hwm: dict[str, float], open_symbols: set[str]) -> None:
    pruned = {k: v for k, v in hwm.items() if k in open_symbols}
    try:
        HWM_PATH.write_text(json.dumps(pruned), encoding="utf-8")
    except Exception:
        pass


def effective_stop_floor(peak_plpc: float, base_stop_pct: float) -> float:
    """Returns the exit threshold (as a plpc fraction) based on the best gain seen.

    Stages:
      peak >= 10%  → protect 5% profit    (stop at +5%)
      peak >= 7.5% → protect breakeven    (stop at +0.5%)
      otherwise    → normal ATR stop      (stop at -base_stop_pct)
    """
    if peak_plpc >= 0.10:
        return _PROFIT_FLOOR
    if peak_plpc >= 0.075:
        return _BREAKEVEN_FLOOR
    return -base_stop_pct


def stop_pct_for(tech: dict) -> float:
    """Volatility-adaptive stop distance as a fraction of price.
    = atr_stop_mult x ATR%, clamped to [min_stop_pct, max_stop_pct].
    Falls back to the flat stop if ATR is unavailable."""
    atr_pct = (tech or {}).get("atr_pct")
    if not atr_pct or atr_pct <= 0:
        return RISK.stop_loss_pct
    raw = STRATEGY.atr_stop_mult * atr_pct
    return min(max(raw, STRATEGY.min_stop_pct), STRATEGY.max_stop_pct)


def cooling_off_symbols(days: int | None = None) -> set[str]:
    """Symbols stopped out in the last N days — re-entry blocked.

    A failed breakout reveals something about supply/demand. Re-entering
    immediately is often buying the same weakness twice. Wait for a new base.
    """
    window = days if days is not None else RISK.cooldown_days
    if not _TRADES.exists():
        return set()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()
    cooling: set[str] = set()
    try:
        for line in _TRADES.read_text(encoding="utf-8").splitlines():
            try:
                t = json.loads(line)
                if (t.get("side") == "sell"
                        and t.get("reason") in _STOP_REASONS
                        and t.get("ts", "") >= cutoff
                        and t.get("status") != "error"):
                    sym = t.get("symbol", "")
                    if sym:
                        cooling.add(sym)
            except Exception:
                pass
    except Exception:
        pass
    return cooling


def vet_orders(decisions: list[dict], account: dict, positions: list[dict],
               tech_by_sym: dict[str, dict], opened_today: set[str],
               risk_on: bool = True) -> list[dict]:
    """Return safe order instructions (PDT/regime/volatility aware)."""
    held = {p["symbol"]: p for p in positions}
    decided = {d.get("symbol", "").upper(): d for d in decisions}
    orders: list[dict] = []

    # 1) Exits — trailing-stop / take-profit / brain sell, on prior-day
    #    positions only (same-day exit = a PDT day trade).
    #    Trailing logic: once a position peaks at 7.5%, the floor rises to
    #    breakeven; at 10%, it locks in 5% profit. Peak is persisted across
    #    cycles in logs/hwm.json so a pullback is never forgotten.
    hwm = _load_hwm()
    open_syms = {p["symbol"] for p in positions}
    for p in positions:
        sym = p["symbol"]
        if sym in opened_today:
            continue
        plpc = p["unrealized_plpc"]
        base_stop_pct = stop_pct_for(tech_by_sym.get(sym, {}))
        hwm[sym] = max(hwm.get(sym, plpc), plpc)
        floor = effective_stop_floor(hwm[sym], base_stop_pct)
        d = decided.get(sym, {})
        hold_days = p.get("hold_days")  # injected by cycle.py from trade log
        if plpc <= floor:
            if floor >= _PROFIT_FLOOR:
                reason = "trailing_stop_profit"
            elif floor >= _BREAKEVEN_FLOOR:
                reason = "trailing_stop_breakeven"
            else:
                reason = "stop_loss"
        elif plpc >= RISK.take_profit_pct:
            reason = "take_profit"
        elif (hold_days is not None
              and hold_days >= RISK.stale_exit_days
              and plpc < RISK.stale_exit_max_gain_pct):
            reason = "stale_position"
        elif d.get("action", "").lower() == "sell":
            reason = "brain_sell"
        else:
            continue
        # Partial exit: brain may request exit_fraction < 1.0 (e.g. "sell half").
        # Mechanical stops/take-profits are always full exits.
        exit_fraction = 1.0
        exit_qty: int | None = None
        if reason == "brain_sell":
            raw_frac = d.get("exit_fraction")
            if raw_frac is not None:
                exit_fraction = max(0.1, min(1.0, float(raw_frac)))
            if exit_fraction < 1.0:
                exit_qty = max(1, round(float(p["qty"]) * exit_fraction))
        orders.append({"symbol": sym, "side": "sell", "reason": reason,
                       "conviction": d.get("conviction"),
                       "reasoning": d.get("reasoning", ""),
                       "plpc": round(plpc, 4), "stop_pct": round(base_stop_pct, 4),
                       "entry_price": round(p["avg_entry"], 2),
                       "exit_fraction": exit_fraction,
                       "exit_qty": exit_qty})
    _save_hwm(hwm, open_syms)

    # 2) Buys — blocked when PDT-locked, after the daily breaker, or risk-off.
    if pdt_locked(account) or daily_loss_tripped(account) or not risk_on:
        return orders

    equity, cash = account["equity"], account["cash"]
    open_count = len(positions)
    blocked = cooling_off_symbols()
    for d in decisions:
        sym = d.get("symbol", "").upper()
        if d.get("action", "").lower() != "buy" or sym in held:
            continue
        if open_count >= RISK.max_open_positions:
            continue
        if sym in blocked:
            continue  # recently stopped out — cooling-off period
        tech = tech_by_sym.get(sym, {})
        price = tech.get("price", 0) or 0
        if price <= 0:
            continue
        stop_pct = stop_pct_for(tech)
        stop_dist = price * stop_pct
        # Volatility sizing: risk ~1% of equity to the stop ...
        risk_qty = math.floor((equity * STRATEGY.risk_per_trade_pct) / stop_dist) if stop_dist else 0
        # ... but never exceed the position-size cap or available cash.
        cap_budget = min(equity * RISK.max_position_pct, cash)
        cap_qty = math.floor(cap_budget / price)
        qty = min(risk_qty, cap_qty)
        if qty < 1:
            continue
        open_count += 1
        cash -= qty * price
        orders.append({"symbol": sym, "side": "buy", "qty": qty,
                       "reason": "brain_buy", "conviction": d.get("conviction"),
                       "reasoning": d.get("reasoning", ""),
                       "stop_pct": round(stop_pct, 4)})
    return orders
