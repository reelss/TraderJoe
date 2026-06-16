"""Historical backtester for Joe's swing strategy.

Simulates Joe's entry/exit rules against daily OHLCV bars to validate edge
before running with real capital. No LLM calls — deterministic rule-based
signals that mirror brain.py's strategy rules. All indicators match snapshot()
exactly so backtest and live results are directly comparable.

Design:
  - Indicators precomputed vectorially per symbol (fast — one pandas pass each)
  - Fills at next trading day's open + 0.1% slippage (no lookahead)
  - Trailing stops mirror risk.py: breakeven at peak +7.5%, profit-lock at +10%
  - Position sizing mirrors vet_orders: ATR-based, 1% equity risk per trade
  - Regime: SPY 200-day SMA (no historical VIX — approximation)

Usage: see run_backtest.py in the project root.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import mean, stdev
from typing import Optional

import numpy as np
import pandas as pd

from .config import CREDS, RISK, STRATEGY
from .indicators import indicator_series
from .risk import effective_stop_floor, stop_pct_for

# ── Universe ──────────────────────────────────────────────────────────────────
DEFAULT_UNIVERSE: list[str] = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "INTC",
    "AVGO", "ORCL", "CRM", "ADBE", "NOW", "PANW", "FTNT", "CRWD", "ZS",
    "SNOW", "DDOG", "NET", "MU", "QCOM", "TXN", "AMAT", "LRCX",
    # Financials
    "JPM", "BAC", "GS", "MS", "WFC", "V", "MA", "AXP", "BLK", "SCHW",
    # Healthcare
    "LLY", "UNH", "JNJ", "PFE", "MRK", "ABBV", "TMO", "AMGN", "GILD",
    # Consumer / Retail
    "COST", "HD", "LOW", "NKE", "SBUX", "MCD", "CMG", "LULU",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG",
    # Industrial
    "CAT", "DE", "HON", "RTX", "BA", "LMT",
    # Sector ETFs (useful as liquid swing vehicles)
    "XLK", "XLF", "XLV", "XLE", "QQQ", "IWM",
]

SLIPPAGE       = 0.001   # 0.1% per fill — buy higher, sell lower
MIN_BARS       = 252     # bars of history required before simulating


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class _Position:
    symbol:      str
    qty:         int
    entry_price: float
    entry_date:  date
    stop_pct:    float
    peak_plpc:   float = 0.0


@dataclass
class TradeRecord:
    symbol:       str
    entry_date:   date
    exit_date:    date
    entry_price:  float
    exit_price:   float
    qty:          int
    plpc:         float
    hold_days:    int
    exit_reason:  str

    def as_dict(self) -> dict:
        return {
            "symbol":      self.symbol,
            "entry_date":  self.entry_date.isoformat(),
            "exit_date":   self.exit_date.isoformat(),
            "entry_price": self.entry_price,
            "exit_price":  self.exit_price,
            "qty":         self.qty,
            "plpc_pct":    round(self.plpc * 100, 2),
            "hold_days":   self.hold_days,
            "exit_reason": self.exit_reason,
        }


# ── Signal helpers ─────────────────────────────────────────────────────────────

def _entry_signal(row: pd.Series) -> bool:
    """Deterministic entry filter matching Joe's brain.py rules 1-12."""
    try:
        return bool(
            row["above_sma20"]   is True  or row["above_sma20"]  == True
            and row["above_sma50"] is True or row["above_sma50"] == True
            and row["macd_bullish"] is True or row["macd_bullish"] == True
            and 50 <= float(row["rsi14"]) <= 75
            and bool(row.get("near_52w_high", True))
            and (pd.isna(row.get("rs_vs_spy")) or float(row["rs_vs_spy"]) > -0.05)
            and float(row.get("avg_dollar_vol_20d", 0)) >= 5_000_000
        )
    except (TypeError, ValueError, KeyError):
        return False


def _regime_risk_on(spy_ind: pd.Series) -> bool:
    """SPY above 200-day SMA → risk on. Approximates market_regime() without VIX."""
    v = spy_ind.get("above_sma200")
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return True   # insufficient history → allow
    return bool(v)


# ── Backtester ────────────────────────────────────────────────────────────────

class Backtester:
    """Run Joe's strategy rules against historical daily bars.

    Parameters
    ----------
    universe    : list of ticker symbols to scan each day
    start_date  : first simulation date  (YYYY-MM-DD)
    end_date    : last  simulation date  (YYYY-MM-DD, default: today)
    starting_equity : initial cash
    """

    def __init__(
        self,
        universe:        list[str] | None = None,
        start_date:      str = "2023-01-01",
        end_date:        str | None = None,
        starting_equity: float = 10_000.0,
    ) -> None:
        self.universe        = list(universe or DEFAULT_UNIVERSE)
        self.start_date      = start_date
        self.end_date        = end_date or datetime.now(timezone.utc).date().isoformat()
        self.starting_equity = starting_equity

        self._cash:      float                     = starting_equity
        self._equity:    float                     = starting_equity
        self._positions: dict[str, _Position]      = {}
        self._trades:    list[TradeRecord]          = []
        self._eq_curve:  list[dict]                 = []

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """Fetch bars, simulate, return results dict."""
        all_bars = self._fetch_bars()
        if isinstance(all_bars, str):
            return {"error": all_bars}

        spy_df = all_bars.get("SPY")
        if spy_df is None:
            return {"error": "SPY bars unavailable — required for regime filter"}

        print("Precomputing indicators …")
        ind: dict[str, pd.DataFrame] = {}
        for sym, df in all_bars.items():
            try:
                ind[sym] = indicator_series(df, spy_df=spy_df if sym != "SPY" else None)
            except Exception as exc:
                print(f"  skip {sym}: {exc}")

        # Trading days inside the backtest window
        bt_start = pd.Timestamp(self.start_date)
        bt_end   = pd.Timestamp(self.end_date)
        trading_days = [d for d in spy_df.index if bt_start <= d <= bt_end]

        print(f"Simulating {len(trading_days)} trading days "
              f"({self.start_date} → {self.end_date}) …")

        pending_buys:  list[dict] = []
        pending_sells: list[dict] = []

        for i, ts in enumerate(trading_days):
            day = ts.date()

            # ── Execute yesterday's pending orders at today's open ──────────
            for order in pending_sells:
                sym = order["symbol"]
                if sym not in self._positions:
                    continue
                pos        = self._positions.pop(sym)
                fill_price = self._open_price(all_bars.get(sym), ts, slippage=-SLIPPAGE)
                if fill_price is None:
                    fill_price = pos.entry_price   # worst case: no P&L
                plpc = (fill_price / pos.entry_price) - 1
                self._cash += fill_price * pos.qty
                self._trades.append(TradeRecord(
                    symbol      = sym,
                    entry_date  = pos.entry_date,
                    exit_date   = day,
                    entry_price = pos.entry_price,
                    exit_price  = round(fill_price, 2),
                    qty         = pos.qty,
                    plpc        = round(plpc, 4),
                    hold_days   = (day - pos.entry_date).days,
                    exit_reason = order["reason"],
                ))
            pending_sells = []

            for order in pending_buys:
                sym = order["symbol"]
                if sym in self._positions:
                    continue
                fill_price = self._open_price(all_bars.get(sym), ts, slippage=+SLIPPAGE)
                if fill_price is None or fill_price <= 0:
                    continue
                cost = fill_price * order["qty"]
                if cost > self._cash * 1.01:  # small tolerance for rounding
                    continue
                self._cash -= cost
                self._positions[sym] = _Position(
                    symbol      = sym,
                    qty         = order["qty"],
                    entry_price = round(fill_price, 2),
                    entry_date  = day,
                    stop_pct    = order["stop_pct"],
                )
            pending_buys = []

            # ── Today's indicator snapshot ──────────────────────────────────
            def _row(sym: str) -> pd.Series | None:
                df = ind.get(sym)
                if df is None or ts not in df.index:
                    return None
                r = df.loc[ts]
                # Require a minimum of MIN_BARS history before this date
                pos_in_df = df.index.get_loc(ts)
                if pos_in_df < MIN_BARS:
                    return None
                return r

            spy_row = _row("SPY")
            risk_on = _regime_risk_on(spy_row) if spy_row is not None else True

            # ── Update peak P&L for held positions ──────────────────────────
            for sym, pos in self._positions.items():
                r = _row(sym)
                if r is not None:
                    price = float(r.get("price", 0) or 0)
                    if price > 0:
                        plpc = (price / pos.entry_price) - 1
                        pos.peak_plpc = max(pos.peak_plpc, plpc)

            # ── Exit signals ────────────────────────────────────────────────
            for sym, pos in list(self._positions.items()):
                r = _row(sym)
                if r is None:
                    continue
                price = float(r.get("price", 0) or 0)
                if price <= 0:
                    continue
                plpc  = (price / pos.entry_price) - 1
                floor = effective_stop_floor(pos.peak_plpc, pos.stop_pct)
                if plpc <= floor:
                    reason = (
                        "trailing_stop_profit"    if floor >= 0.04  else
                        "trailing_stop_breakeven" if floor > -pos.stop_pct else
                        "stop_loss"
                    )
                    pending_sells.append({"symbol": sym, "reason": reason})
                elif plpc >= RISK.take_profit_pct:
                    pending_sells.append({"symbol": sym, "reason": "take_profit"})

            # ── Entry signals ───────────────────────────────────────────────
            exiting = {o["symbol"] for o in pending_sells}
            slots   = RISK.max_open_positions - len(self._positions) - len(exiting)

            if risk_on and slots > 0:
                candidates: list[tuple[str, pd.Series]] = []
                for sym in self.universe:
                    if sym in self._positions or sym in exiting:
                        continue
                    r = _row(sym)
                    if r is None:
                        continue
                    if _entry_signal(r):
                        candidates.append((sym, r))

                # Rank highest momentum first
                candidates.sort(
                    key=lambda x: float(x[1].get("mom_12_1") or -999),
                    reverse=True,
                )

                for sym, r in candidates[:slots]:
                    price    = float(r.get("price", 0) or 0)
                    atr_pct  = float(r.get("atr_pct") or 0)
                    tech_stub = {"price": price, "atr_pct": atr_pct}
                    sp       = stop_pct_for(tech_stub)
                    stop_dist = price * sp
                    if stop_dist <= 0:
                        continue
                    risk_qty  = math.floor(
                        (self._equity * STRATEGY.risk_per_trade_pct) / stop_dist
                    )
                    cap_budget = min(self._equity * RISK.max_position_pct, self._cash)
                    cap_qty    = math.floor(cap_budget / price)
                    qty        = min(risk_qty, cap_qty)
                    if qty < 1:
                        continue
                    pending_buys.append({"symbol": sym, "qty": qty, "stop_pct": sp})

            # ── Equity snapshot ─────────────────────────────────────────────
            mkt_value = 0.0
            for sym, pos in self._positions.items():
                r = _row(sym)
                price = float(r.get("price", 0)) if r is not None else pos.entry_price
                mkt_value += price * pos.qty
            self._equity = self._cash + mkt_value
            self._eq_curve.append({
                "date":        day.isoformat(),
                "equity":      round(self._equity, 2),
                "cash":        round(self._cash, 2),
                "n_positions": len(self._positions),
            })

        return self._results()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _fetch_bars(self) -> dict[str, pd.DataFrame] | str:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests  import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        all_syms = sorted(set(self.universe) | {"SPY"})
        # Fetch enough extra history for the 252-bar warmup
        fetch_start = (
            datetime.fromisoformat(self.start_date) - timedelta(days=500)
        )
        print(f"Fetching bars for {len(all_syms)} symbols "
              f"from {fetch_start.date()} …")
        try:
            client = StockHistoricalDataClient(CREDS.alpaca_key, CREDS.alpaca_secret)
            req    = StockBarsRequest(
                symbol_or_symbols = all_syms,
                timeframe         = TimeFrame.Day,
                start             = fetch_start,
            )
            raw = client.get_stock_bars(req).df
        except Exception as exc:
            return f"Bar fetch failed: {exc}"

        if raw is None or raw.empty:
            return "No bars returned from Alpaca"

        result: dict[str, pd.DataFrame] = {}
        for sym in raw.index.get_level_values(0).unique():
            df             = raw.xs(sym, level=0).copy()
            df.index       = pd.to_datetime(df.index).normalize()
            result[str(sym)] = df
        return result

    @staticmethod
    def _open_price(
        df: pd.DataFrame | None,
        ts: pd.Timestamp,
        slippage: float = 0.0,
    ) -> float | None:
        if df is None:
            return None
        try:
            price = float(df.loc[ts, "open"])
            return price * (1 + slippage)
        except (KeyError, TypeError):
            pass
        # Fallback: prior close
        try:
            idx = df.index.get_loc(ts)
            if idx > 0:
                return float(df.iloc[idx - 1]["close"]) * (1 + slippage)
        except Exception:
            pass
        return None

    def _results(self) -> dict:
        n_trades = len(self._trades)
        if n_trades == 0:
            return {
                "start_date":      self.start_date,
                "end_date":        self.end_date,
                "starting_equity": self.starting_equity,
                "ending_equity":   round(self._equity, 2),
                "total_trades":    0,
                "note": (
                    "No trades executed — entry signal may be too strict "
                    "or backtest period too short."
                ),
                "equity_curve": self._eq_curve,
                "trades":       [],
            }

        plpcs  = [t.plpc for t in self._trades]
        wins   = [t for t in self._trades if t.plpc > 0]
        losses = [t for t in self._trades if t.plpc <= 0]

        total_ret = (self._equity / self.starting_equity) - 1
        n_days    = len(self._eq_curve)
        years     = max(n_days / 252, 1 / 252)
        cagr      = (self._equity / self.starting_equity) ** (1.0 / years) - 1

        # Sharpe (annualised, risk-free = 0 for simplicity)
        daily_rets = []
        for j in range(1, len(self._eq_curve)):
            prev = self._eq_curve[j - 1]["equity"]
            curr = self._eq_curve[j]["equity"]
            if prev > 0:
                daily_rets.append((curr / prev) - 1)
        sharpe = None
        if len(daily_rets) >= 20:
            mu  = mean(daily_rets)
            sig = stdev(daily_rets)
            sharpe = round(mu / sig * (252 ** 0.5), 2) if sig > 0 else None

        # Max drawdown
        max_dd  = 0.0
        peak_eq = self.starting_equity
        for pt in self._eq_curve:
            eq = pt["equity"]
            peak_eq = max(peak_eq, eq)
            dd = (peak_eq - eq) / peak_eq
            max_dd = max(max_dd, dd)

        # Exit reason summary
        by_reason: dict[str, dict] = {}
        for t in self._trades:
            r = t.exit_reason
            if r not in by_reason:
                by_reason[r] = {"count": 0, "wins": 0, "plpc_sum": 0.0}
            by_reason[r]["count"]    += 1
            by_reason[r]["plpc_sum"] += t.plpc
            if t.plpc > 0:
                by_reason[r]["wins"] += 1

        hold_all = [t.hold_days for t in self._trades]
        hold_w   = [t.hold_days for t in wins]
        hold_l   = [t.hold_days for t in losses]

        return {
            "start_date":            self.start_date,
            "end_date":              self.end_date,
            "starting_equity":       self.starting_equity,
            "ending_equity":         round(self._equity, 2),
            "total_return_pct":      round(total_ret  * 100, 2),
            "cagr_pct":              round(cagr       * 100, 2),
            "sharpe_ratio":          sharpe,
            "max_drawdown_pct":      round(max_dd     * 100, 2),
            "total_trades":          n_trades,
            "win_rate":              round(len(wins) / n_trades, 3),
            "avg_plpc_pct":          round(mean(plpcs) * 100, 2),
            "avg_plpc_winners_pct":  round(mean([t.plpc for t in wins])   * 100, 2) if wins   else None,
            "avg_plpc_losers_pct":   round(mean([t.plpc for t in losses]) * 100, 2) if losses else None,
            "avg_hold_days":         round(mean(hold_all), 1) if hold_all else None,
            "avg_hold_days_winners": round(mean(hold_w),   1) if hold_w   else None,
            "avg_hold_days_losers":  round(mean(hold_l),   1) if hold_l   else None,
            "exits_by_reason": {
                r: {
                    "count":    v["count"],
                    "win_rate": round(v["wins"] / v["count"], 3),
                    "avg_plpc_pct": round(v["plpc_sum"] / v["count"] * 100, 2),
                }
                for r, v in by_reason.items()
            },
            "note": "Fills at next-day open +/- 0.1% slippage. No VIX filter (SPY SMA only).",
            "equity_curve": self._eq_curve,
            "trades": [t.as_dict() for t in self._trades],
        }
