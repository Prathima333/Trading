# -*- coding: utf-8 -*-
"""
Backtester for ITM LEAPS Strategy with Portfolio Allocation % Branching,
200 SMA Upward Slope Macro Filter, Peak Overbought Exit Rules (Price >= 1.18 * 200 SMA OR RSI >= 75),
and Peak Overbought Entry Block & Resumption Thresholds (Price <= 1.12 * 200 SMA AND RSI <= 60).
"""

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment

from credentials import get_alpaca_credentials
from helpers import tv_ema, compute_rsi


def black_scholes_call(S, K, T, r=0.04, sigma=0.22):
    """Simplified Black-Scholes call option pricing model."""
    if T <= 0:
        return max(0.0, S - K)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    def norm_cdf(x):
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


class Position:
    """Tracks an open option position in backtest."""
    def __init__(self, entry_date, entry_stock_price, strike, buy_opt_price, initial_dte=365):
        self.entry_date = entry_date
        self.entry_stock_price = entry_stock_price
        self.strike = strike
        self.buy_opt_price = buy_opt_price
        self.initial_dte = initial_dte
        self.peak_opt_price = buy_opt_price
        self.contract_size = 100


def run_backtest(symbol="QQQ", lookback_days=1825, initial_capital=20000.0, itm_discount=0.07, trail_pct=15.0):
    """
    Simulates the ITM LEAPS trading strategy over historical daily bar data.
    """
    print(f"=== Starting ITM LEAPS Backtest for {symbol} ===")
    print(f"Initial Capital: ${initial_capital:,.2f} | Lookback Window: {lookback_days} days | ITM Discount: {itm_discount*100}% | Trailing Stop: {trail_pct}%\n")

    api_key, secret_key = get_alpaca_credentials()
    data_client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)

    end_date = datetime.now(tz=ZoneInfo("America/New_York"))
    start_date = end_date - timedelta(days=lookback_days + 450)

    request_params = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Day,
        start=start_date,
        adjustment=Adjustment.ALL,
    )
    bars = data_client.get_stock_bars(request_params)

    df = bars.df
    close_series = df.loc[symbol]["close"] if isinstance(df.index, pd.MultiIndex) else df["close"]

    ema8 = tv_ema(close_series, 8)
    ema21 = tv_ema(close_series, 21)
    sma200 = close_series.rolling(window=200).mean()
    sma200_slope = sma200.diff(20)
    rsi_series = compute_rsi(close_series, period=14)

    cash = initial_capital
    open_positions = []
    closed_trades = []
    equity_curve = []
    is_overbought_cooldown_active = False

    start_idx = 201
    dates = close_series.index[start_idx:]

    for idx_num, current_dt in enumerate(dates):
        curr_i = start_idx + idx_num
        today_date = current_dt.date() if hasattr(current_dt, "date") else current_dt
        today_price = float(close_series.iloc[curr_i])
        today_ema8 = float(ema8.iloc[curr_i])
        today_ema21 = float(ema21.iloc[curr_i])
        today_sma200 = float(sma200.iloc[curr_i])
        today_sma200_slope = float(sma200_slope.iloc[curr_i]) if not math.isnan(sma200_slope.iloc[curr_i]) else 0.0
        today_rsi = float(rsi_series.iloc[curr_i]) if not math.isnan(rsi_series.iloc[curr_i]) else 50.0

        yest_ema8 = float(ema8.iloc[curr_i - 1])
        yest_ema21 = float(ema21.iloc[curr_i - 1])
        yest_sma200 = float(sma200.iloc[curr_i - 1])

        ratio_200sma = today_price / today_sma200 if today_sma200 > 0 else 1.0

        # Overbought entry block trigger
        if ratio_200sma >= 1.18 or today_rsi >= 75.0:
            is_overbought_cooldown_active = True

        # Resumption threshold trigger
        if ratio_200sma <= 1.12 and today_rsi <= 60.0:
            is_overbought_cooldown_active = False

        # Step 1: Manage open positions
        remaining_positions = []
        for pos in open_positions:
            days_held = (today_date - (pos.entry_date.date() if hasattr(pos.entry_date, "date") else pos.entry_date)).days
            current_dte = max(0, pos.initial_dte - days_held)
            T_years = current_dte / 365.0

            curr_opt_price = black_scholes_call(today_price, pos.strike, T_years)
            pos.peak_opt_price = max(pos.peak_opt_price, curr_opt_price)

            gain_pct = (curr_opt_price / pos.buy_opt_price - 1.0)
            is_trail_hit = (gain_pct > 0.40) and (curr_opt_price <= pos.peak_opt_price * (1.0 - trail_pct / 100.0))

            # Peak Overbought Exit Rule: Price >= 1.18 * 200 SMA OR RSI >= 75 (when in profit > 30%)
            is_peak_exit = (gain_pct > 0.30) and (ratio_200sma >= 1.18 or today_rsi >= 75.0)

            # Exit Condition A: 15% Trailing Stop after +40% gain
            if is_trail_hit:
                sell_proceeds = curr_opt_price * pos.contract_size
                pnl = (curr_opt_price - pos.buy_opt_price) * pos.contract_size
                pnl_pct = gain_pct * 100
                cash += sell_proceeds

                closed_trades.append({
                    "entry_date": pos.entry_date,
                    "exit_date": today_date,
                    "strike": pos.strike,
                    "buy_opt_price": pos.buy_opt_price,
                    "exit_opt_price": curr_opt_price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "reason": f"{trail_pct}% Trailing Stop Exit",
                    "holding_days": days_held,
                })
                print(f"[{today_date}] EXIT ({trail_pct}% Trailing Stop): Sold Strike ${pos.strike} @ ${curr_opt_price:.2f} (Cost: ${pos.buy_opt_price:.2f}, PnL: +${pnl:.2f})")

            # Exit Condition B: Peak Overbought Profit Harvest Exit
            elif is_peak_exit:
                sell_proceeds = curr_opt_price * pos.contract_size
                pnl = (curr_opt_price - pos.buy_opt_price) * pos.contract_size
                pnl_pct = gain_pct * 100
                cash += sell_proceeds

                closed_trades.append({
                    "entry_date": pos.entry_date,
                    "exit_date": today_date,
                    "strike": pos.strike,
                    "buy_opt_price": pos.buy_opt_price,
                    "exit_opt_price": curr_opt_price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "reason": "Peak Overbought Harvest Exit",
                    "holding_days": days_held,
                })
                print(f"[{today_date}] EXIT (Peak Overbought Harvest): Sold Strike ${pos.strike} @ ${curr_opt_price:.2f} (Cost: ${pos.buy_opt_price:.2f}, PnL: +${pnl:.2f})")

            # Exit Condition C: 90 DTE Risk Exit
            elif current_dte <= 90:
                sell_proceeds = curr_opt_price * pos.contract_size
                pnl = (curr_opt_price - pos.buy_opt_price) * pos.contract_size
                pnl_pct = gain_pct * 100
                cash += sell_proceeds

                closed_trades.append({
                    "entry_date": pos.entry_date,
                    "exit_date": today_date,
                    "strike": pos.strike,
                    "buy_opt_price": pos.buy_opt_price,
                    "exit_opt_price": curr_opt_price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "reason": "90 DTE Risk Exit",
                    "holding_days": days_held,
                })
                print(f"[{today_date}] EXIT (90 DTE Risk Exit): Sold Strike ${pos.strike} @ ${curr_opt_price:.2f} (Cost: ${pos.buy_opt_price:.2f}, PnL: ${pnl:.2f})")

            else:
                remaining_positions.append(pos)

        open_positions = remaining_positions

        # Step 2: Calculate Portfolio Allocation %
        open_pos_value = 0.0
        for pos in open_positions:
            days_held = (today_date - (pos.entry_date.date() if hasattr(pos.entry_date, "date") else pos.entry_date)).days
            current_dte = max(0, pos.initial_dte - days_held)
            opt_val = black_scholes_call(today_price, pos.strike, current_dte / 365.0)
            open_pos_value += opt_val * pos.contract_size

        total_equity = cash + open_pos_value
        allocated_pct = (open_pos_value / total_equity * 100.0) if total_equity > 0 else 0.0
        bullish_regime = (today_price > today_sma200) and (today_sma200_slope > 0)
        entry_allowed = bullish_regime and (not is_overbought_cooldown_active)

        # Condition 1: Portfolio allocation < 30%
        if allocated_pct < 30.0 and entry_allowed:
            target_pos_cost = total_equity * ((30.0 - allocated_pct) / 100.0)
            strike = round(today_price * (1.0 - itm_discount), 2)
            buy_opt_price = black_scholes_call(today_price, strike, 1.0)
            qty = max(1, int(target_pos_cost // (buy_opt_price * 100)))
            cost = buy_opt_price * 100 * qty

            if cash >= cost:
                cash -= cost
                new_pos = Position(today_date, today_price, strike, buy_opt_price)
                new_pos.contract_size = qty * 100
                open_positions.append(new_pos)
                print(f"[{today_date}] ENTRY (<30% Alloc -> Pos #1): Bought Strike ${strike} ({qty} units) @ ${buy_opt_price:.2f} (Cost: ${cost:.2f})")

        # Condition 2: Portfolio allocation < 40%
        elif allocated_pct < 40.0:
            ema_8_21_cross = (yest_ema8 < yest_ema21) and (today_ema8 > today_ema21)

            if ema_8_21_cross and entry_allowed:
                target_pos_cost = total_equity * 0.30
                strike = round(today_price * (1.0 - itm_discount), 2)
                buy_opt_price = black_scholes_call(today_price, strike, 1.0)
                qty = max(1, int(target_pos_cost // (buy_opt_price * 100)))
                cost = buy_opt_price * 100 * qty

                if cash >= cost:
                    cash -= cost
                    new_pos = Position(today_date, today_price, strike, buy_opt_price)
                    new_pos.contract_size = qty * 100
                    open_positions.append(new_pos)
                    print(f"[{today_date}] ENTRY (<40% Alloc -> Pos #2 - 8/21 EMA Cross): Bought Strike ${strike} ({qty} units) @ ${buy_opt_price:.2f}")

        # Condition 3: Portfolio allocation < 70%
        elif allocated_pct < 70.0:
            ema_21_200_cross = (yest_ema21 < yest_sma200) and (today_ema21 > today_sma200)

            if ema_21_200_cross and entry_allowed:
                target_pos_cost = total_equity * 0.30
                strike = round(today_price * (1.0 - itm_discount), 2)
                buy_opt_price = black_scholes_call(today_price, strike, 1.0)
                qty = max(1, int(target_pos_cost // (buy_opt_price * 100)))
                cost = buy_opt_price * 100 * qty

                if cash >= cost:
                    cash -= cost
                    new_pos = Position(today_date, today_price, strike, buy_opt_price)
                    new_pos.contract_size = qty * 100
                    open_positions.append(new_pos)
                    print(f"[{today_date}] ENTRY (<70% Alloc -> Pos #3 - 21/200 EMA Cross): Bought Strike ${strike} ({qty} units) @ ${buy_opt_price:.2f}")

        open_pos_value = sum(black_scholes_call(today_price, p.strike, max(0, 365 - (today_date - (p.entry_date.date() if hasattr(p.entry_date, "date") else p.entry_date)).days) / 365.0) * p.contract_size for p in open_positions)
        total_equity = cash + open_pos_value
        equity_curve.append(total_equity)

    print("\n=== Backtest Execution Complete ===")
    start_price = float(close_series.iloc[start_idx])
    end_price = float(close_series.iloc[-1])
    qqq_buy_hold_return = ((end_price / start_price) - 1.0) * 100.0

    final_equity = equity_curve[-1]
    strategy_return = ((final_equity / initial_capital) - 1.0) * 100.0

    total_trades = len(closed_trades)
    winning_trades = [t for t in closed_trades if t["pnl"] > 0]
    losing_trades = [t for t in closed_trades if t["pnl"] <= 0]
    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

    total_gross_profit = sum(t["pnl"] for t in winning_trades)
    total_gross_loss = abs(sum(t["pnl"] for t in losing_trades))
    profit_factor = (total_gross_profit / total_gross_loss) if total_gross_loss > 0 else float("inf")

    avg_holding = sum(t["holding_days"] for t in closed_trades) / total_trades if total_trades > 0 else 0.0

    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    drawdown = (eq_series - peak) / peak
    max_drawdown = abs(float(drawdown.min())) * 100.0

    print("\n=======================================================")
    print("         ITM LEAPS STRATEGY BACKTEST RESULTS         ")
    print("=======================================================")
    print(f"Initial Capital:         ${initial_capital:,.2f}")
    print(f"Final Equity:            ${final_equity:,.2f}")
    print(f"Strategy Total Return:   {strategy_return:+.2f}%")
    print(f"QQQ Buy & Hold Return:   {qqq_buy_hold_return:+.2f}%")
    print("-------------------------------------------------------")
    print(f"Total Trades Closed:     {total_trades}")
    print(f"Winning Trades:          {len(winning_trades)}")
    print(f"Losing Trades:           {len(losing_trades)}")
    print(f"Win Rate:                {win_rate:.2f}%")
    print(f"Profit Factor:           {profit_factor:.2f}")
    print(f"Max Drawdown:            {max_drawdown:.2f}%")
    print(f"Avg Trade Holding Period:{avg_holding:.1f} days")
    print("=======================================================\n")

    return equity_curve, closed_trades


if __name__ == "__main__":
    run_backtest()
