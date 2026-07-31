"""Alpaca paper-trading wrapper — Joe's hands on the market.

Thin, typed layer over alpaca-py so the rest of the code speaks in plain
Python dicts/DataFrames and never touches Alpaca request objects directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    StopLossRequest,
    StopOrderRequest,
    TakeProfitRequest,
)

from .config import CREDS


class Broker:
    def __init__(self) -> None:
        self.trading = TradingClient(
            CREDS.alpaca_key, CREDS.alpaca_secret, paper=True
        )
        self.data = StockHistoricalDataClient(
            CREDS.alpaca_key, CREDS.alpaca_secret
        )

    # --- account state ---
    def account(self) -> dict:
        a = self.trading.get_account()
        return {
            "equity": float(a.equity),
            "last_equity": float(a.last_equity),   # equity at prior close
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
            "daytrade_count": int(a.daytrade_count or 0),
        }

    def positions(self) -> list[dict]:
        out = []
        for p in self.trading.get_all_positions():
            out.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            })
        return out

    def is_market_open(self) -> bool:
        return bool(self.trading.get_clock().is_open)

    # --- market data ---
    def daily_bars(self, symbols: list[str], lookback_days: int = 420) -> dict[str, pd.DataFrame]:
        """Daily OHLCV bars per symbol, indexed by date. Empty dict-safe."""
        if not symbols:
            return {}
        start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start,
        )
        bars = self.data.get_stock_bars(req).df
        result: dict[str, pd.DataFrame] = {}
        if bars is None or bars.empty:
            return result
        # alpaca-py returns a MultiIndex (symbol, timestamp); split per symbol.
        for sym in bars.index.get_level_values(0).unique():
            df = bars.xs(sym, level=0).copy()
            df.index = pd.to_datetime(df.index)
            result[str(sym)] = df
        return result

    def intraday_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Current price, today's change %, and today's running volume per symbol.

        Uses Alpaca's snapshot endpoint which bundles the latest trade,
        today's partial bar, and yesterday's close in one request.
        Returns {} on any error — never blocks a cycle.

        Keys per symbol: price, prev_close, change_today_pct, vol_today,
                         intraday_high, intraday_low
        """
        if not symbols:
            return {}
        try:
            req = StockSnapshotRequest(symbol_or_symbols=symbols)
            snaps = self.data.get_stock_snapshot(req)
            result: dict[str, dict] = {}
            for sym, snap in snaps.items():
                try:
                    price = float(snap.latest_trade.price) if snap.latest_trade else None
                    prev_close = float(snap.previous_daily_bar.close) if snap.previous_daily_bar else None
                    today_bar = snap.daily_bar
                    vol_today = float(today_bar.volume) if today_bar else None
                    intraday_high = float(today_bar.high) if today_bar else None
                    intraday_low = float(today_bar.low) if today_bar else None
                    change_today = (
                        round(price / prev_close - 1, 4)
                        if price and prev_close and prev_close > 0
                        else None
                    )
                    result[str(sym)] = {
                        "price": round(price, 2) if price else None,
                        "prev_close": round(prev_close, 2) if prev_close else None,
                        "change_today_pct": change_today,
                        "vol_today": vol_today,
                        "intraday_high": round(intraday_high, 2) if intraday_high else None,
                        "intraday_low": round(intraday_low, 2) if intraday_low else None,
                    }
                except Exception:
                    pass
            return result
        except Exception:
            return {}

    # --- order execution ---
    def buy_market(self, symbol: str, qty: int) -> dict:
        """Plain whole-share market BUY (no bracket). Stops/targets are managed
        in-cycle by Joe so they can't auto-fire the same day and create an
        involuntary day trade (PDT protection on a sub-$25k account)."""
        order = MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        return self._submit(order)

    def symbols_bought_today(self) -> set[str]:
        """Symbols with a BUY that filled today (UTC) — i.e. opened this session.
        Selling any of these same-day would be a PDT-counting day trade, so Joe
        avoids it. Source of truth = Alpaca fills (captures manual buys too)."""
        today = datetime.now(timezone.utc).date()
        out: set[str] = set()
        try:
            orders = self.trading.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=200)
            )
            for o in orders:
                if (str(o.side).endswith("BUY") and o.filled_at
                        and o.filled_at.date() == today
                        and float(o.filled_qty or 0) > 0):
                    out.add(o.symbol)
        except Exception:
            pass
        return out

    def resting_stops(self) -> dict[str, dict]:
        """Open GTC stop orders keyed by symbol: {symbol: {id, stop_price, qty}}.

        These are Joe's overnight gap protection — a resting stop at the broker
        fires on a gap-down at the open, whereas Joe's in-cycle stop check only
        runs hourly during market hours. Returns {} on any error.
        """
        out: dict[str, dict] = {}
        try:
            orders = self.trading.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=200)
            )
            for o in orders:
                if str(o.order_type).lower().endswith("stop") and str(o.side).endswith("SELL"):
                    out[o.symbol] = {
                        "id": str(o.id),
                        "stop_price": float(o.stop_price) if o.stop_price else None,
                        "qty": float(o.qty) if o.qty else None,
                    }
        except Exception:
            pass
        return out

    def place_stop(self, symbol: str, qty: int, stop_price: float) -> dict | None:
        """Place a GTC sell-stop as overnight protection. None on failure.

        Safe under PDT: only called for positions opened on a PRIOR day, so a
        fill can never create a same-day round trip.
        """
        try:
            order = StopOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                stop_price=round(stop_price, 2),
            )
            o = self.trading.submit_order(order)
            return {"id": str(o.id), "symbol": symbol, "status": str(o.status)}
        except Exception as exc:
            # Never silent: an unplaced protective stop means an unprotected
            # position, which is exactly the failure this system exists to stop.
            from . import logbook as log
            log.info(f"place_stop FAILED {symbol} @ ${stop_price:.2f}: {exc!r}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            self.trading.cancel_order_by_id(order_id)
            return True
        except Exception:
            return False

    def pending_buys(self) -> dict[str, float]:
        """Unfilled BUY quantities by symbol: {symbol: qty}.

        Alpaca does not decrement `cash` until an order fills, so without this
        two cycles can commit the same dollars — and stack a position past its
        size cap, since the cap is measured against filled positions only.
        Returns {} on any error.
        """
        out: dict[str, float] = {}
        try:
            orders = self.trading.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=200)
            )
            for o in orders:
                if str(o.side).endswith("BUY"):
                    qty = float(o.qty or 0) - float(o.filled_qty or 0)
                    if qty > 0:
                        out[o.symbol] = out.get(o.symbol, 0.0) + qty
        except Exception:
            pass
        return out

    def partial_exit(self, symbol: str, qty: int) -> dict:
        """Sell a specific number of shares from a held position.

        Used when Joe takes partial profits (e.g. sells half at +12% while
        letting the remainder run). Cancels open orders on the symbol first
        so they can't conflict with the partial sale.
        """
        try:
            open_orders = self.trading.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            )
            for o in open_orders:
                try:
                    self.trading.cancel_order_by_id(o.id)
                except Exception:
                    pass
        except Exception:
            pass
        order = MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        return self._submit(order)

    def exit_position(self, symbol: str) -> dict:
        """Early exit on the brain's call: cancel the symbol's open bracket legs
        first (so they can't conflict), then liquidate the position."""
        try:
            open_orders = self.trading.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            )
            for o in open_orders:
                try:
                    self.trading.cancel_order_by_id(o.id)
                except Exception:
                    pass
        except Exception:
            pass
        o = self.trading.close_position(symbol)
        return {"id": str(o.id), "symbol": symbol, "status": str(o.status)}

    def _submit(self, order: MarketOrderRequest) -> dict:
        o = self.trading.submit_order(order)
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": str(o.side),
            "qty": float(o.qty) if o.qty else None,
            "notional": float(o.notional) if o.notional else None,
            "status": str(o.status),
        }
