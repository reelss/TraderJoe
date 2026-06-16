"""Technical indicators computed from daily OHLCV bars.

Pure pandas/numpy — no external TA dependency. Each function takes a bars
DataFrame (columns: open/high/low/close/volume) and returns plain numbers,
so the brain receives a compact, readable snapshot per ticker.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty and not np.isnan(rsi.iloc[-1]) else float("nan")


def _macd(close: pd.Series) -> tuple[float, float]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return float(macd.iloc[-1]), float(signal.iloc[-1])


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return float(atr.iloc[-1]) if not atr.empty else float("nan")


def indicator_series(df: pd.DataFrame, spy_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Vectorised indicator computation for a full bar series.

    Used by the backtester to avoid recomputing rolling windows on each
    simulated day. Each row is a trading date; each column is an indicator.
    Rows with insufficient history (< 252 bars) have NaN for most columns.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    out = pd.DataFrame(index=df.index)
    out["price"]   = close.round(2)
    out["sma20"]   = close.rolling(20).mean().round(2)
    out["sma50"]   = close.rolling(50).mean().round(2)
    out["sma200"]  = close.rolling(200).mean().round(2)
    out["above_sma20"]  = close > out["sma20"]
    out["above_sma50"]  = close > out["sma50"]
    out["above_sma200"] = close > out["sma200"]

    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    sig    = macd.ewm(span=9, adjust=False).mean()
    out["macd_bullish"] = macd > sig

    delta  = close.diff()
    gain   = delta.clip(lower=0).rolling(14).mean()
    loss   = (-delta.clip(upper=0)).rolling(14).mean()
    rs     = gain / loss.replace(0, np.nan)
    out["rsi14"] = (100 - (100 / (1 + rs))).round(1)

    prev_close = close.shift(1)
    tr = pd.concat([high - low,
                    (high - prev_close).abs(),
                    (low  - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    out["atr14"]   = atr.round(2)
    out["atr_pct"] = (atr / close).round(4)

    out["ret_20d"]  = (close / close.shift(21) - 1).round(4)
    out["mom_12_1"] = (close.shift(21) / close.shift(252) - 1).round(4)

    vol_avg = volume.rolling(20).mean()
    out["vol_ratio"]      = (volume / vol_avg).round(2)
    out["vol_confirming"] = out["vol_ratio"] >= 1.5
    out["avg_dollar_vol_20d"] = (close * volume).rolling(20).mean().round(0)

    # 52-week high uses intraday high; min_periods=20 for early rows.
    hi52 = high.rolling(252, min_periods=20).max()
    out["hi52w"]         = hi52.round(2)
    out["pct_from_hi52w"] = (close / hi52 - 1).round(4)
    out["near_52w_high"] = out["pct_from_hi52w"] >= -0.15

    if spy_df is not None:
        spy_close  = spy_df["close"].reindex(df.index, method="ffill")
        spy_r20    = (spy_close / spy_close.shift(21) - 1).round(4)
        out["rs_vs_spy"] = (out["ret_20d"] - spy_r20).round(4)
    else:
        out["rs_vs_spy"] = np.nan

    return out


def snapshot(df: pd.DataFrame, spy_ret_20d: float | None = None) -> dict:
    """Compact technical summary for one ticker. Safe on short histories.

    spy_ret_20d: SPY's 20-session return, used to compute rs_vs_spy.
    Optional — omit or pass None and rs_vs_spy will be None.
    """
    if df is None or len(df) < 20:
        return {"insufficient_data": True, "bars": 0 if df is None else len(df)}

    close = df["close"]
    last = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(df) >= 50 else float("nan")
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else float("nan")
    macd, signal = _macd(close)
    atr = _atr(df)
    avg_dollar_vol = float((df["close"] * df["volume"]).rolling(20).mean().iloc[-1])

    # Momentum: % change over 5 and 20 sessions.
    ret_5 = float(close.iloc[-1] / close.iloc[-6] - 1) if len(df) >= 6 else float("nan")
    ret_20 = float(close.iloc[-1] / close.iloc[-21] - 1) if len(df) >= 21 else float("nan")
    # 12-1 momentum (Jegadeesh-Titman): return from ~252 to ~21 sessions ago,
    # excluding the most recent month. The robust cross-sectional momentum signal.
    mom_12_1 = (float(close.iloc[-21] / close.iloc[-252] - 1)
                if len(df) >= 252 else float("nan"))

    # Volume confirmation: today's volume vs. 20-day average.
    vol_today = float(df["volume"].iloc[-1])
    vol_avg_20 = float(df["volume"].rolling(20).mean().iloc[-1])
    vol_ratio = round(vol_today / vol_avg_20, 2) if vol_avg_20 > 0 else None

    # 52-week high proximity. Uses intraday high for accuracy.
    # Falls back to all available bars when history < 252 sessions.
    window_52w = min(252, len(df))
    hi52w = float(df["high"].rolling(window_52w).max().iloc[-1])
    pct_from_hi52w = round(last / hi52w - 1, 4) if hi52w > 0 else None
    near_52w_high = pct_from_hi52w is not None and pct_from_hi52w >= -0.15

    # Relative strength vs. SPY: positive = outperforming, negative = lagging.
    rs_vs_spy = (round(ret_20 - spy_ret_20d, 4)
                 if (not np.isnan(ret_20) and spy_ret_20d is not None)
                 else None)

    return {
        "price": round(last, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2) if not np.isnan(sma50) else None,
        "sma200": round(sma200, 2) if not np.isnan(sma200) else None,
        "above_sma20": last > sma20,
        "above_sma50": (last > sma50) if not np.isnan(sma50) else None,
        "above_sma200": (last > sma200) if not np.isnan(sma200) else None,
        "rsi14": round(_rsi(close), 1),
        "macd": round(macd, 3),
        "macd_signal": round(signal, 3),
        "macd_bullish": macd > signal,
        "atr14": round(atr, 2),
        "atr_pct": round(atr / last, 4) if last else None,
        "ret_5d": round(ret_5, 4) if not np.isnan(ret_5) else None,
        "ret_20d": round(ret_20, 4) if not np.isnan(ret_20) else None,
        "mom_12_1": round(mom_12_1, 4) if not np.isnan(mom_12_1) else None,
        "avg_dollar_vol_20d": round(avg_dollar_vol, 0),
        # Volume confirmation
        "vol_ratio": vol_ratio,          # today / 20d avg; >1.5 = high-volume move
        "vol_confirming": (vol_ratio is not None and vol_ratio >= 1.5),
        # 52-week high proximity
        "hi52w": round(hi52w, 2),
        "pct_from_hi52w": pct_from_hi52w,   # 0 = at high; -0.15 = 15% below
        "near_52w_high": near_52w_high,      # True if within 15% of 52w high
        # Relative strength vs. SPY (20-day window)
        "rs_vs_spy": rs_vs_spy,              # positive = outperforming SPY
        "bars": len(df),
    }
