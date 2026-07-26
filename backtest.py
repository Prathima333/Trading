# -*- coding: utf-8 -*-
"""
QQQ LEAPS Strategy Backtesting Engine.
Simulates daily execution of the trading strategy over historical market data.
"""

import os
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment
from alpaca.data.requests import StockBarsRequest

from credentials import get_alpaca_credentials


def norm_cdf(x):
    """Cumulative distribution function for standard normal distribution."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_call(S, K, T, r=0.045, sigma=0.22):
    """
    Calculates Black-Scholes European call option price.
    S = Current Underlying Price, K = Strike Price, T = Time to Expiration in Years
    r = Risk-free Interest Rate, sigma = Implied Volatility
    """
    if T <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


def tv_ema(series: pd.Series, period: int) -> pd.Series:
    """TradingView standard Exponential Moving Average (EMA) with initial SMA seeding."""
    ema = np.zeros_like(series, dtype=float)
    ema[period - 1] = series.iloc[:period].mean()
    multiplier = 2 / (period + 1)
    for i in range(period, len(series)):
        ema[i] = (series.iloc[i] - ema[i - 1]) * multiplier + ema[i - 1]
    ema[:period - 1] = np.nan
    return pd.Series(ema, index=series.index)


class Position:
    def __init__(self, entry_date, entry_price, strike, buy_opt_price, initial_dte=365):
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.strike = strike
        self.buy_opt_price = buy_opt_price
        self.target_opt_price = round(buy_opt_price * 1.5, 2)
        self.initial_dte = initial_dte
        self.contract_size = 100


def run_backtest(symbol="QQQ", lookback_days=1000, initial_capital=20000.0):
    """
    Runs the LEAPS strategy backtest day-by-day over historical data.
    """
    print(f"=== Starting LEAPS Backtest for {symbol} ===")
    print(f"Initial Capital: ${initial_capital:,.2f} | Lookback Window: {lookback_days} days\n")

    api_key, secret_key = get_alpaca_credentials()
    data_client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)

    end_date = datetime.now(tz=ZoneInfo("America/New_York"))
    start_date = end_date - timedelta(days=lookback_days)

    req = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Day,
        start=start_date,
        adjustment=Adjustment.ALL,
    )
    bars = data_client.get_stock_bars(req)
    df = bars.df
    close_series = df.loc[symbol]['close'] if isinstance(df.index, pd.MultiIndex) else df['close']

    # Compute technical indicators
    ema8 = tv_ema(close_series, 8)
    ema21 = tv_ema(close_series, 21)
    sma200 = close_series.rolling(window=200).mean()

    cash = initial_capital
    open_positions = []
    closed_trades = []
    equity_curve = []

    start_idx = 201
    dates = close_series.index[start_idx:]

    for idx_num, current_dt in enumerate(dates):
        curr_i = start_idx + idx_num
        today_date = current_dt.date() if hasattr(current_dt, 'date') else current_dt
        today_price = float(close_series.iloc[curr_i])
        today_ema8 = float(ema8.iloc[curr_i])
        today_ema21 = float(ema21.iloc[curr_i])
        today_sma200 = float(sma200.iloc[curr_i])

        yest_ema8 = float(ema8.iloc[curr_i - 1])
        yest_ema21 = float(ema21.iloc[curr_i - 1])
        yest_sma200 = float(sma200.iloc[curr_i - 1])

        # Step 1: Manage open positions (Runs once per day at market close)
        remaining_positions = []
        for pos in open_positions:
            days_held = (today_date - pos.entry_date.date() if hasattr(pos.entry_date, 'date') else today_date - pos.entry_date).days
            current_dte = max(0, pos.initial_dte - days_held)
            T_years = current_dte / 365.0

            curr_opt_price = black_scholes_call(today_price, pos.strike, T_years)

            # Check Exit Condition A: 50% Profit Target
            if curr_opt_price >= pos.target_opt_price:
                sell_proceeds = curr_opt_price * pos.contract_size
                pnl = (curr_opt_price - pos.buy_opt_price) * pos.contract_size
                pnl_pct = (curr_opt_price / pos.buy_opt_price - 1.0) * 100
                cash += sell_proceeds

                closed_trades.append({
                    'entry_date': pos.entry_date,
                    'exit_date': today_date,
                    'strike': pos.strike,
                    'buy_opt_price': pos.buy_opt_price,
                    'exit_opt_price': curr_opt_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'reason': '50% Profit Target',
                    'holding_days': days_held,
                })
                print(f"[{today_date}] EXIT (50% Profit): Sold Strike ${pos.strike} @ ${curr_opt_price:.2f} (Cost: ${pos.buy_opt_price:.2f}, PnL: +${pnl:.2f})")

            # Check Exit Condition B: 90 DTE Exit Rule
            elif current_dte <= 90:
                sell_proceeds = curr_opt_price * pos.contract_size
                pnl = (curr_opt_price - pos.buy_opt_price) * pos.contract_size
                pnl_pct = (curr_opt_price / pos.buy_opt_price - 1.0) * 100
                cash += sell_proceeds

                closed_trades.append({
                    'entry_date': pos.entry_date,
                    'exit_date': today_date,
                    'strike': pos.strike,
                    'buy_opt_price': pos.buy_opt_price,
                    'exit_opt_price': curr_opt_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'reason': '90 DTE Risk Exit',
                    'holding_days': days_held,
                })
                print(f"[{today_date}] EXIT (90 DTE Exit): Sold Strike ${pos.strike} @ ${curr_opt_price:.2f} (Cost: ${pos.buy_opt_price:.2f}, PnL: ${pnl:.2f})")

            else:
                remaining_positions.append(pos)

        open_positions = remaining_positions

        # Step 2: Evaluate Daily Entry Signals (Runs once per day)
        num_positions = len(open_positions)
        price_above_200 = today_price > today_sma200

        if num_positions == 0:
            strike = round(today_price, 2)
            buy_opt_price = black_scholes_call(today_price, strike, 1.0)
            cost = buy_opt_price * 100

            if cash >= cost:
                cash -= cost
                new_pos = Position(today_date, today_price, strike, buy_opt_price)
                open_positions.append(new_pos)
                print(f"[{today_date}] ENTRY (Pos #1): Bought ATM Call Strike ${strike} @ ${buy_opt_price:.2f} (Cost: ${cost:.2f})")

        elif num_positions == 1:
            ema_8_21_cross = (yest_ema8 < yest_ema21) and (today_ema8 > today_ema21)

            if ema_8_21_cross and price_above_200:
                strike = round(today_price, 2)
                buy_opt_price = black_scholes_call(today_price, strike, 1.0)
                cost = buy_opt_price * 100

                if cash >= cost:
                    cash -= cost
                    new_pos = Position(today_date, today_price, strike, buy_opt_price)
                    open_positions.append(new_pos)
                    print(f"[{today_date}] ENTRY (Pos #2 - 8/21 EMA Cross): Bought Call Strike ${strike} @ ${buy_opt_price:.2f}")

        elif num_positions == 2:
            ema_21_200_cross = (yest_ema21 < yest_sma200) and (today_ema21 > today_sma200)

            if ema_21_200_cross and price_above_200:
                strike = round(today_price, 2)
                buy_opt_price = black_scholes_call(today_price, strike, 1.0)
                cost = buy_opt_price * 100

                if cash >= cost:
                    cash -= cost
                    new_pos = Position(today_date, today_price, strike, buy_opt_price)
                    open_positions.append(new_pos)
                    print(f"[{today_date}] ENTRY (Pos #3 - 21/200 EMA Cross): Bought Call Strike ${strike} @ ${buy_opt_price:.2f}")

        # Calculate daily portfolio equity
        open_pos_value = 0.0
        for pos in open_positions:
            days_held = (today_date - pos.entry_date.date() if hasattr(pos.entry_date, 'date') else today_date - pos.entry_date).days
            current_dte = max(0, pos.initial_dte - days_held)
            opt_val = black_scholes_call(today_price, pos.strike, current_dte / 365.0)
            open_pos_value += opt_val * pos.contract_size

        total_equity = cash + open_pos_value
        equity_curve.append(total_equity)

    # Step 3: Backtest Performance Report
    print("\n=== Backtest Execution Complete ===")

    start_price = float(close_series.iloc[start_idx])
    end_price = float(close_series.iloc[-1])
    qqq_buy_hold_return = ((end_price / start_price) - 1.0) * 100

    final_equity = equity_curve[-1]
    strategy_return = ((final_equity / initial_capital) - 1.0) * 100

    total_trades = len(closed_trades)
    winning_trades = [t for t in closed_trades if t['pnl'] > 0]
    losing_trades = [t for t in closed_trades if t['pnl'] <= 0]

    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0.0
    total_gains = sum(t['pnl'] for t in winning_trades)
    total_losses = abs(sum(t['pnl'] for t in losing_trades))
    profit_factor = (total_gains / total_losses) if total_losses > 0 else float('inf')

    avg_holding_days = (sum(t['holding_days'] for t in closed_trades) / total_trades) if total_trades > 0 else 0

    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    drawdown = (eq_series - peak) / peak
    max_drawdown = abs(float(drawdown.min())) * 100

    print("\n" + "=" * 55)
    print(f"               STRATEGY BACKTEST RESULTS             ")
    print("=" * 55)
    print(f"Initial Capital:         ${initial_capital:,.2f}")
    print(f"Final Equity:            ${final_equity:,.2f}")
    print(f"Strategy Total Return:   {strategy_return:+.2f}%")
    print(f"QQQ Buy & Hold Return:   {qqq_buy_hold_return:+.2f}%")
    print("-" * 55)
    print(f"Total Trades Closed:     {total_trades}")
    print(f"Winning Trades:          {len(winning_trades)}")
    print(f"Losing Trades:           {len(losing_trades)}")
    print(f"Win Rate:                {win_rate:.2f}%")
    print(f"Profit Factor:           {profit_factor:.2f}")
    print(f"Max Drawdown:            {max_drawdown:.2f}%")
    print(f"Avg Trade Holding Period:{avg_holding_days:.1f} days")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    run_backtest(symbol="QQQ", lookback_days=1000, initial_capital=20000.0)
