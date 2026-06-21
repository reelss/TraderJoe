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

from . import logbook as log
from .config import HWM_PATH, LOGS_DIR, PEAKS_PATH, RISK, STRATEGY
from .sectors import would_exceed_sector_cap

_TRADES = LOGS_DIR / "trades.jsonl"

# Trailing take-profit: above this gain, replace the hard +15% exit with a
# trailing stop — let winners run, but exit if they give back `_TP_GIVEBACK`.
_TP_TRAIL_TRIGGER = 0.15   # only trail once a position is up 15%+
_TP_GIVEBACK = 0.06        # exit if it falls 6% from its peak gain
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
    except Exception as exc:
        log.info(f"hwm save failed: {exc!r}")


def _load_peaks() -> dict[str, float]:
    try:
        if PEAKS_PATH.exists():
            return json.loads(PEAKS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_peaks(peaks: dict[str, float], open_symbols: set[str]) -> None:
    pruned = {k: v for k, v in peaks.items() if k in open_symbols}
    try:
        PEAKS_PATH.write_text(json.dumps(pruned), encoding="utf-8")
    except Exception as exc:
        log.info(f"peaks save failed: {exc!r}")


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
               risk_on: bool = True,
               meta_by_sym: dict[str, dict] | None = None) -> list[dict]:
    """Return safe order instructions (PDT/regime/volatility aware).

    meta_by_sym: per-candidate hard-gate data, keyed by upper-case symbol:
        {"above_sma200": bool|None, "earnings_soon": bool, "sector": str}
    Built by cycle.py from the candidate list. When None (e.g. the offline
    self-test), the SMA200/earnings/sector hard gates are skipped — the legacy
    risk/sizing path still runs unchanged.
    """
    meta_by_sym = meta_by_sym or {}
    held = {p["symbol"]: p for p in positions}
    decided = {d.get("symbol", "").upper(): d for d in decisions}
    orders: list[dict] = []

    def _reject(sym: str, why: str) -> None:
        log.info(f"vet_orders: rejected BUY {sym} — {why}")

    # 1) Exits — trailing-stop / take-profit / brain sell, on prior-day
    #    positions only (same-day exit = a PDT day trade).
    #    Ladder logic (below +15%): once a position peaks at 7.5%, the floor
    #    rises to breakeven; at 10%, it locks in 5% profit.
    #    Above +15%: the old hard take-profit is replaced by a TRAILING stop —
    #    we track peak gain in logs/peaks.json and only exit if the position
    #    gives back `_TP_GIVEBACK` (6%) from its peak. Winners are left to run.
    hwm = _load_hwm()
    peaks = _load_peaks()
    open_syms = {p["symbol"] for p in positions}
    for p in positions:
        sym = p["symbol"]
        if sym in opened_today:
            continue
        plpc = p["unrealized_plpc"]
        base_stop_pct = stop_pct_for(tech_by_sym.get(sym, {}))
        hwm[sym] = max(hwm.get(sym, plpc), plpc)
        peaks[sym] = max(peaks.get(sym, plpc), plpc)
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
        elif plpc >= _TP_TRAIL_TRIGGER and (peaks[sym] - plpc) >= _TP_GIVEBACK:
            # Up 15%+ and gave back 6% from the peak — bank the trailing winner.
            reason = "trailing_take_profit"
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
    _save_peaks(peaks, open_syms)

    # 2) Buys — blocked when PDT-locked, after the daily breaker, or risk-off.
    if pdt_locked(account) or daily_loss_tripped(account) or not risk_on:
        return orders

    equity, cash = account["equity"], account["cash"]
    open_count = len(positions)
    blocked = cooling_off_symbols()
    # Track cumulative committed value (existing positions + this cycle's buys)
    # so the deployment floor and sector cap reflect same-cycle accumulation.
    committed = sum(abs(p.get("market_value", 0)) for p in positions)
    pending_for_sector: list[dict] = list(positions)
    for d in decisions:
        sym = d.get("symbol", "").upper()
        if d.get("action", "").lower() != "buy" or sym in held:
            continue
        if open_count >= RISK.max_open_positions:
            continue
        if sym in blocked:
            continue  # recently stopped out — cooling-off period

        meta = meta_by_sym.get(sym, {})
        # --- Hard gates (T1-C): enforced in code, not left to the brain. ---
        # 1) SMA200 trend gate.
        if meta.get("above_sma200") is False:
            _reject(sym, "below 200-day SMA (trend gate)")
            continue
        # 2) Earnings gate — no new position with earnings within 5 days.
        if meta.get("earnings_soon"):
            _reject(sym, "earnings within 5 days")
            continue

        tech = tech_by_sym.get(sym, {})
        price = tech.get("price", 0) or 0
        if price <= 0:
            continue
        # 3) Stop ceiling — stop_pct_for already clamps to max_stop_pct (0.09);
        #    we read it through that path so the ceiling is always enforced.
        stop_pct = stop_pct_for(tech)
        stop_dist = price * stop_pct

        # Volatility sizing: risk ~risk_per_trade_pct of equity to the stop ...
        risk_qty = math.floor((equity * STRATEGY.risk_per_trade_pct) / stop_dist) if stop_dist else 0
        # ... but never exceed the position-size cap or available cash.
        cap_budget = min(equity * RISK.max_position_pct, cash)
        cap_qty = math.floor(cap_budget / price)
        qty = min(risk_qty, cap_qty)

        # --- Deployment floor (T1-A): don't let the risk formula alone leave
        #     capital idle when the regime is risk-on and there's room. If we're
        #     under the deploy target, scale the size up toward the position cap
        #     (still bounded by cash). Never forces beyond the 10% cap. ---
        under_deployed = committed < equity * STRATEGY.min_deploy_pct
        if under_deployed and open_count < RISK.max_open_positions and cap_qty >= 1:
            qty = max(qty, cap_qty)

        if qty < 1:
            continue

        # 4) Sector veto (T1-C): would this buy push its sector over 30% equity?
        #    Only runs in the live path (meta present) — it makes a sector lookup,
        #    which the offline self-test (meta_by_sym=None) must not trigger.
        add_value = qty * price
        if meta_by_sym and would_exceed_sector_cap(sym, add_value, pending_for_sector, equity):
            _reject(sym, "would exceed 30% sector cap")
            continue

        open_count += 1
        cash -= add_value
        committed += add_value
        pending_for_sector.append({"symbol": sym, "market_value": add_value})
        orders.append({"symbol": sym, "side": "buy", "qty": qty,
                       "reason": "brain_buy", "conviction": d.get("conviction"),
                       "reasoning": d.get("reasoning", ""),
                       "stop_pct": round(stop_pct, 4)})
    return orders
