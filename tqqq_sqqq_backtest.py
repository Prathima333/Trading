# -*- coding: utf-8 -*-
"""
WhiteLight TQQQ/SQQQ Systematic Strategy Backtester.
Based on Mallik's "WhiteLight" Systematic Rotation Approach (Featured in "This Trader Made +$700K in 6 MONTHS").

Strategy Overview:
- Trades TQQQ (3x Bullish Nasdaq-100) & SQQQ (3x Bearish Nasdaq-100) / Cash.
- Uses QQQ (underlying index) technical indicators:
  1. 200-Day SMA & Slope Macro Filter:
     - Bullish Regime (QQQ > 200 SMA & 20-Day Slope > 0): Focus on TQQQ long.
     - Bearish Regime (QQQ < 200 SMA & 20-Day Slope < 0): Focus on SQQQ long.
     - Choppy / Flat Regime: Hold 100% Cash to avoid 3x ETF decay.
  2. Bollinger Bands (20-Day SMA, 2.0 Std Dev) & 14-Day RSI:
     - TQQQ Momentum Entry: QQQ > 20 EMA and breaks Upper Bollinger Band.
     - TQQQ Mean Reversion Dip Entry: QQQ pulls back to 20 SMA / Lower Band with RSI < 45 in Bullish Regime.
     - SQQQ Bearish Entry: QQQ breaks Lower Bollinger Band with RSI < 45 in Bearish Regime.
  3. Risk Management: 12% Trailing Stop loss on 3x leveraged ETF positions.
"""

import math
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf

from helpers import tv_ema, compute_rsi


def compute_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0):
    """Computes Bollinger Bands (Middle Band = SMA, Upper Band, Lower Band)."""
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper_band = sma + (std * num_std)
    lower_band = sma - (std * num_std)
    return sma, upper_band, lower_band


class LeveragedPosition:
    """Tracks an open position in TQQQ, SQQQ, or Cash."""
    def __init__(self, symbol, entry_date, entry_price, shares, capital_allocated):
        self.symbol = symbol
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.capital_allocated = capital_allocated
        self.peak_price = entry_price


def run_whitelight_backtest(start_date_str="2000-03-27", initial_capital=20000.0, trail_pct=12.0):
    """
    Runs the WhiteLight TQQQ/SQQQ Systematic Strategy backtest.
    Utilizes daily prices and synthetic 3x daily return math prior to ETF inception (2010).
    """
    print(f"\n=======================================================")
    print(f"   WHITELIGHT TQQQ/SQQQ STRATEGY BACKTEST ({start_date_str} to Present)   ")
    print(f"=======================================================")
    print(f"Initial Capital: ${initial_capital:,.2f} | Trailing Stop: {trail_pct}%\n")

    # Fetch QQQ, TQQQ, SQQQ data from Yahoo Finance
    yf_qqq = yf.Ticker("QQQ")
    df_qqq = yf_qqq.history(start="1999-03-10", end="2026-07-26", auto_adjust=True)
    qqq_close = df_qqq["Close"].dropna()

    # Create synthetic daily returns for TQQQ (3x QQQ daily pct change) and SQQQ (-3x QQQ daily pct change)
    qqq_pct_change = qqq_close.pct_change().fillna(0.0)

    # Historical actual ETF data if available
    try:
        df_tqqq = yf.Ticker("TQQQ").history(start="2010-02-11", end="2026-07-26", auto_adjust=True)["Close"]
        df_sqqq = yf.Ticker("SQQQ").history(start="2010-02-11", end="2026-07-26", auto_adjust=True)["Close"]
    except Exception:
        df_tqqq = pd.Series(dtype=float)
        df_sqqq = pd.Series(dtype=float)

    # Build full synthetic TQQQ and SQQQ price series
    tqqq_sim_prices = [10.0]
    sqqq_sim_prices = [100.0]
    for r in qqq_pct_change.iloc[1:]:
        # 3x daily return with small expense ratio drag (~0.95% annual)
        t_ret = (r * 3.0) - (0.0095 / 252.0)
        s_ret = (-r * 3.0) - (0.0095 / 252.0)
        tqqq_sim_prices.append(max(0.001, tqqq_sim_prices[-1] * (1.0 + t_ret)))
        sqqq_sim_prices.append(max(0.001, sqqq_sim_prices[-1] * (1.0 + s_ret)))

    tqqq_series = pd.Series(tqqq_sim_prices, index=qqq_close.index)
    sqqq_series = pd.Series(sqqq_sim_prices, index=qqq_close.index)

    # Use actual ETF market prices after 2010 inception date
    tqqq_series.update(df_tqqq)
    sqqq_series.update(df_sqqq)

    # Technical Indicators on QQQ
    ema20 = tv_ema(qqq_close, 20)
    sma200 = qqq_close.rolling(window=200).mean()
    sma200_slope = sma200.diff(20)
    rsi14 = compute_rsi(qqq_close, period=14)
    sma20, bb_upper, bb_lower = compute_bollinger_bands(qqq_close, period=20, num_std=2.0)

    # Start date alignment
    target_start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    start_idx = None
    for i, dt in enumerate(qqq_close.index):
        d = dt.date() if hasattr(dt, "date") else dt
        if d >= target_start:
            start_idx = i
            break

    if start_idx is None or start_idx < 201:
        start_idx = 201

    cash = initial_capital
    active_position = None  # LeveragedPosition or None
    closed_trades = []
    equity_curve = []
    dates = qqq_close.index[start_idx:]

    for idx_num, current_dt in enumerate(dates):
        curr_i = start_idx + idx_num
        today_date = current_dt.date() if hasattr(current_dt, "date") else current_dt

        p_qqq = float(qqq_close.iloc[curr_i])
        p_tqqq = float(tqqq_series.iloc[curr_i])
        p_sqqq = float(sqqq_series.iloc[curr_i])

        t_ema20 = float(ema20.iloc[curr_i])
        t_sma200 = float(sma200.iloc[curr_i])
        t_sma200_slope = float(sma200_slope.iloc[curr_i]) if not math.isnan(sma200_slope.iloc[curr_i]) else 0.0
        t_rsi = float(rsi14.iloc[curr_i]) if not math.isnan(rsi14.iloc[curr_i]) else 50.0

        t_bb_upper = float(bb_upper.iloc[curr_i])
        t_bb_lower = float(bb_lower.iloc[curr_i])
        t_sma20 = float(sma20.iloc[curr_i])

        y_qqq = float(qqq_close.iloc[curr_i - 1])
        y_bb_upper = float(bb_upper.iloc[curr_i - 1])
        y_bb_lower = float(bb_lower.iloc[curr_i - 1])

        # Regime Flags
        bullish_regime = (p_qqq > t_sma200) and (t_sma200_slope > 0)
        bearish_regime = (p_qqq < t_sma200) and (t_sma200_slope < 0)

        # 1. Manage Active Position Exits
        if active_position is not None:
            curr_price = p_tqqq if active_position.symbol == "TQQQ" else p_sqqq
            active_position.peak_price = max(active_position.peak_price, curr_price)

            gain_pct = (curr_price / active_position.entry_price - 1.0)
            is_trail_hit = curr_price <= active_position.peak_price * (1.0 - trail_pct / 100.0)

            # Signal Reversal Exit
            is_regime_reversal = (active_position.symbol == "TQQQ" and bearish_regime) or (active_position.symbol == "SQQQ" and bullish_regime)

            # Overbought Exhaustion Exit for TQQQ (RSI > 75 or stretch > 2.0 std dev)
            is_tqqq_overbought = (active_position.symbol == "TQQQ") and (t_rsi >= 75.0 or p_qqq >= t_bb_upper * 1.02)

            if is_trail_hit or is_regime_reversal or is_tqqq_overbought:
                exit_proceeds = active_position.shares * curr_price
                pnl = exit_proceeds - active_position.capital_allocated
                cash += exit_proceeds

                reason = "Trailing Stop" if is_trail_hit else ("Regime Reversal" if is_regime_reversal else "Overbought Harvest")
                closed_trades.append({
                    "symbol": active_position.symbol,
                    "entry_date": active_position.entry_date,
                    "exit_date": today_date,
                    "entry_price": active_position.entry_price,
                    "exit_price": curr_price,
                    "pnl": pnl,
                    "pnl_pct": gain_pct * 100.0,
                    "reason": reason
                })
                active_position = None

        # 2. Calculate Total Equity
        if active_position is not None:
            curr_price = p_tqqq if active_position.symbol == "TQQQ" else p_sqqq
            pos_val = active_position.shares * curr_price
        else:
            pos_val = 0.0

        total_equity = cash + pos_val
        equity_curve.append(total_equity)

        # 3. Evaluate New Position Entries (Only if currently in Cash)
        if active_position is None and total_equity > 0:
            # Signal A: TQQQ Momentum Breakout (Bullish Regime & QQQ > Upper Bollinger Band)
            tqqq_momentum_entry = bullish_regime and (y_qqq <= y_bb_upper) and (p_qqq > t_bb_upper)

            # Signal B: TQQQ Mean Reversion Dip Entry (Bullish Regime, QQQ <= 20 EMA, RSI < 45)
            tqqq_dip_entry = bullish_regime and (p_qqq <= t_ema20) and (t_rsi < 45.0)

            # Signal C: SQQQ Bearish Breakdown Entry (Bearish Regime & QQQ < Lower Bollinger Band, RSI < 45)
            sqqq_bear_entry = bearish_regime and (p_qqq < t_bb_lower) and (t_rsi < 45.0)

            if tqqq_momentum_entry or tqqq_dip_entry:
                shares = int(total_equity // p_tqqq)
                if shares > 0:
                    cost = shares * p_tqqq
                    cash -= cost
                    active_position = LeveragedPosition("TQQQ", today_date, p_tqqq, shares, cost)

            elif sqqq_bear_entry:
                shares = int(total_equity // p_sqqq)
                if shares > 0:
                    cost = shares * p_sqqq
                    cash -= cost
                    active_position = LeveragedPosition("SQQQ", today_date, p_sqqq, shares, cost)

    # Metrics Calculation
    final_equity = equity_curve[-1]
    strategy_return = ((final_equity / initial_capital) - 1.0) * 100.0

    qqq_start_price = float(qqq_close.iloc[start_idx])
    qqq_end_price = float(qqq_close.iloc[-1])
    qqq_return = ((qqq_end_price / qqq_start_price) - 1.0) * 100.0

    total_trades = len(closed_trades)
    wins = [t for t in closed_trades if t["pnl"] > 0]
    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    max_drawdown = abs(float(((eq_series - peak) / peak).min())) * 100.0

    print(f"Final Equity:            ${final_equity:,.2f}")
    print(f"Strategy Total Return:   +{strategy_return:,.2f}%")
    print(f"QQQ Buy & Hold Return:   +{qqq_return:,.2f}%")
    print(f"Total Trades Closed:     {total_trades}")
    print(f"Win Rate:                {win_rate:.2f}%")
    print(f"Max Drawdown:            {max_drawdown:.2f}%")
    print("=======================================================\n")

    return equity_curve, closed_trades, dates, qqq_close.iloc[start_idx:]


if __name__ == "__main__":
    run_whitelight_backtest()
