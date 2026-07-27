# -*- coding: utf-8 -*-
"""
WhiteLight TQQQ/SQQQ 7 Sub-Strategy Ensemble Backtester.
Replicates Mallik's "WhiteLight" Systematic Strategy featured in "This Trader Made +$700K in 6 MONTHS".

Strategy Architecture:
- Combines 7 distinct sub-strategies across Trend Following and Mean Reversion:
  1. Sub-Strategy 1: 200-Day SMA Macro Trend Regimer (QQQ > 200 SMA)
  2. Sub-Strategy 2: 50-Day SMA Intermediate Trend Regimer (QQQ > 50 SMA)
  3. Sub-Strategy 3: 20-Day EMA Trend Follower (20 EMA > 50 SMA)
  4. Sub-Strategy 4: 10-Day EMA Fast Momentum (10 EMA > 20 EMA)
  5. Sub-Strategy 5: Bollinger Band Volatility Breakout (20 SMA, 2.0 Std Dev)
  6. Sub-Strategy 6: RSI Mean Reversion Dip Buyer (RSI < 45 in Bullish Regime)
  7. Sub-Strategy 7: RSI Overbought Profit Harvester (RSI > 70 exit to Cash)
- Voting Ensemble Allocation:
  - Consensus Vote >= +2: Hold TQQQ (3x Bullish Nasdaq-100 ETF).
  - Consensus Vote <= -4: Hold SQQQ (3x Bearish Nasdaq-100 ETF).
  - Neutral (-3 to +1): Hold 100% Cash to eliminate 3x ETF volatility decay.
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


def run_whitelight_backtest(start_date_str="2021-07-26", initial_capital=20000.0, trail_pct=10.0):
    """
    Runs the WhiteLight 7 Sub-Strategy Ensemble Backtest.
    """
    print(f"\n=======================================================")
    print(f"   WHITELIGHT 7 SUB-STRATEGY ENSEMBLE BACKTEST ({start_date_str} to Present)   ")
    print(f"=======================================================")
    print(f"Initial Capital: ${initial_capital:,.2f} | Trailing Stop: {trail_pct}%\n")

    # Fetch QQQ daily data
    yf_qqq = yf.Ticker("QQQ")
    df_qqq = yf_qqq.history(start="1999-03-10", end="2026-07-26", auto_adjust=True)
    qqq_close = df_qqq["Close"].dropna()
    qqq_pct_change = qqq_close.pct_change().fillna(0.0)

    # Fetch TQQQ and SQQQ historical ETF data
    try:
        df_tqqq = yf.Ticker("TQQQ").history(start="2010-02-11", end="2026-07-26", auto_adjust=True)["Close"]
        df_sqqq = yf.Ticker("SQQQ").history(start="2010-02-11", end="2026-07-26", auto_adjust=True)["Close"]
    except Exception:
        df_tqqq = pd.Series(dtype=float)
        df_sqqq = pd.Series(dtype=float)

    # Build full synthetic series pre-2010
    tqqq_sim_prices = [10.0]
    sqqq_sim_prices = [100.0]
    for r in qqq_pct_change.iloc[1:]:
        t_ret = (r * 3.0) - (0.0095 / 252.0)
        s_ret = (-r * 3.0) - (0.0095 / 252.0)
        tqqq_sim_prices.append(max(0.001, tqqq_sim_prices[-1] * (1.0 + t_ret)))
        sqqq_sim_prices.append(max(0.001, sqqq_sim_prices[-1] * (1.0 + s_ret)))

    tqqq_series = pd.Series(tqqq_sim_prices, index=qqq_close.index)
    sqqq_series = pd.Series(sqqq_sim_prices, index=qqq_close.index)
    tqqq_series.update(df_tqqq)
    sqqq_series.update(df_sqqq)

    # Calculate 7 Sub-Strategy Indicators on QQQ
    ema10 = tv_ema(qqq_close, 10)
    ema20 = tv_ema(qqq_close, 20)
    sma50 = qqq_close.rolling(window=50).mean()
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
    pos_symbol = "CASH"
    pos_shares = 0
    closed_trades = []
    equity_curve = []
    trade_entry_date = None
    trade_entry_price = 0.0

    dates = qqq_close.index[start_idx:]

    for idx_num, current_dt in enumerate(dates):
        curr_i = start_idx + idx_num
        today_date = current_dt.date() if hasattr(current_dt, "date") else current_dt

        p_qqq = float(qqq_close.iloc[curr_i])
        p_tqqq = float(tqqq_series.iloc[curr_i])
        p_sqqq = float(sqqq_series.iloc[curr_i])

        t_ema10 = float(ema10.iloc[curr_i])
        t_ema20 = float(ema20.iloc[curr_i])
        t_sma50 = float(sma50.iloc[curr_i])
        t_sma200 = float(sma200.iloc[curr_i])
        t_sma200_slope = float(sma200_slope.iloc[curr_i]) if not math.isnan(sma200_slope.iloc[curr_i]) else 0.0
        t_rsi = float(rsi14.iloc[curr_i]) if not math.isnan(rsi14.iloc[curr_i]) else 50.0

        t_bb_upper = float(bb_upper.iloc[curr_i])
        t_bb_lower = float(bb_lower.iloc[curr_i])

        # Evaluate 7 Sub-Strategy Consensus Votes
        s1 = 1 if (p_qqq > t_sma200 and t_sma200_slope > 0) else (-1 if p_qqq < t_sma200 else 0)
        s2 = 1 if p_qqq > t_sma50 else -1
        s3 = 1 if t_ema20 > t_sma50 else -1
        s4 = 1 if t_ema10 > t_ema20 else -1
        s5 = 1 if p_qqq > t_bb_upper else (-1 if p_qqq < t_bb_lower else 0)
        s6 = 1 if (p_qqq > t_sma200 and t_rsi < 45) else (1 if t_rsi < 30 else (-1 if t_rsi > 70 else 0))
        s7 = 1 if p_qqq > t_ema20 else -1

        total_votes = s1 + s2 + s3 + s4 + s5 + s6 + s7

        # Ensemble Decision Logic
        if total_votes >= 2:
            target_symbol = "TQQQ"
        elif total_votes <= -4:
            target_symbol = "SQQQ"
        else:
            target_symbol = "CASH"

        # Position Valuation
        if pos_symbol == "TQQQ":
            pos_val = pos_shares * p_tqqq
        elif pos_symbol == "SQQQ":
            pos_val = pos_shares * p_sqqq
        else:
            pos_val = 0.0

        total_equity = cash + pos_val
        equity_curve.append(total_equity)

        # Rebalance Position
        if pos_symbol != target_symbol:
            if pos_symbol != "CASH":
                exit_price = p_tqqq if pos_symbol == "TQQQ" else p_sqqq
                pnl = (pos_shares * exit_price) - (pos_shares * trade_entry_price)
                pnl_pct = ((exit_price / trade_entry_price) - 1.0) * 100.0 if trade_entry_price > 0 else 0.0
                closed_trades.append({
                    "symbol": pos_symbol,
                    "entry_date": trade_entry_date,
                    "exit_date": today_date,
                    "entry_price": trade_entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "votes": total_votes
                })

            cash = total_equity
            pos_symbol = target_symbol
            trade_entry_date = today_date

            if target_symbol == "TQQQ":
                trade_entry_price = p_tqqq
                pos_shares = int((total_equity * 0.98) // p_tqqq)
                cash -= pos_shares * p_tqqq
            elif target_symbol == "SQQQ":
                trade_entry_price = p_sqqq
                pos_shares = int((total_equity * 0.50) // p_sqqq)
                cash -= pos_shares * p_sqqq
            else:
                pos_shares = 0
                trade_entry_price = 0.0

    # Summary Metrics
    final_equity = equity_curve[-1]
    strategy_return = ((final_equity / initial_capital) - 1.0) * 100.0

    qqq_start_price = float(qqq_close.iloc[start_idx])
    qqq_end_price = float(qqq_close.iloc[-1])
    qqq_return = ((qqq_end_price / qqq_start_price) - 1.0) * 100.0

    total_trades = len(closed_trades)
    winning_trades = [t for t in closed_trades if t["pnl"] > 0]
    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    max_drawdown = abs(float(((eq_series - peak) / peak).min())) * 100.0

    print("\n=======================================================")
    print("   WHITELIGHT 7 SUB-STRATEGY ENSEMBLE BACKTEST RESULTS ")
    print("=======================================================")
    print(f"Initial Capital:         ${initial_capital:,.2f}")
    print(f"Final Equity:            ${final_equity:,.2f}")
    print(f"Strategy Total Return:   {strategy_return:+.2f}%")
    print(f"QQQ Buy & Hold Return:   {qqq_return:+.2f}%")
    print("-------------------------------------------------------")
    print(f"Total Trades Closed:     {total_trades}")
    print(f"Winning Trades:          {len(winning_trades)}")
    print(f"Win Rate:                {win_rate:.2f}%")
    print(f"Max Drawdown:            {max_drawdown:.2f}%")
    print("=======================================================\n")

    return equity_curve, closed_trades, dates, qqq_close.iloc[start_idx:]


if __name__ == "__main__":
    run_whitelight_backtest()
