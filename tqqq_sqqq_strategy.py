# -*- coding: utf-8 -*-
"""
WhiteLight TQQQ/SQQQ 7 Sub-Strategy Ensemble Main Execution Script.
Replicates Mallik's "WhiteLight" Systematic Strategy featured in "This Trader Made +$700K in 6 MONTHS".

Combines 7 distinct sub-strategies across Trend Following and Mean Reversion:
1. Sub-Strategy 1: 200-Day SMA Macro Trend Regimer (QQQ > 200 SMA)
2. Sub-Strategy 2: 50-Day SMA Intermediate Trend Regimer (QQQ > 50 SMA)
3. Sub-Strategy 3: 20-Day EMA Trend Follower (20 EMA > 50 SMA)
4. Sub-Strategy 4: 10-Day EMA Fast Momentum (10 EMA > 20 EMA)
5. Sub-Strategy 5: Bollinger Band Volatility Breakout (20 SMA, 2.0 Std Dev)
6. Sub-Strategy 6: RSI Mean Reversion Dip Buyer (RSI < 45 in Bullish Regime)
7. Sub-Strategy 7: RSI Overbought Profit Harvester (RSI > 70 exit to Cash)

Enforces Market Hours Guard & Auto-Cancels Open Buy Orders at Startup.
"""

import nest_asyncio
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, TrailingStopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment

from credentials import get_alpaca_credentials
from helpers import (
    is_market_open,
    cancel_outstanding_buy_orders,
    tv_ema,
    compute_rsi,
)

# Enable async code support in notebook environments
nest_asyncio.apply()

# Trading configuration
paper = True
trade_api_url = None

# Fetch API credentials
api_key, secret_key = get_alpaca_credentials()

# Initialize Alpaca clients
trade_client = TradingClient(
    api_key=api_key,
    secret_key=secret_key,
    paper=paper,
    url_override=trade_api_url,
)
data_client = StockHistoricalDataClient(
    api_key=api_key,
    secret_key=secret_key,
)


def compute_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0):
    """Computes Bollinger Bands (Middle Band = SMA, Upper Band, Lower Band)."""
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper_band = sma + (std * num_std)
    lower_band = sma - (std * num_std)
    return sma, upper_band, lower_band


def execute_whitelight_strategy():
    """Executes the WhiteLight 7 Sub-Strategy Ensemble Strategy on Alpaca."""
    underlying_symbol = "QQQ"
    print("\n=======================================================")
    print("   WHITELIGHT 7 SUB-STRATEGY ENSEMBLE SYSTEMATIC EXEC ")
    print("=======================================================\n")

    # Step 1: Auto-cancel open buy orders for TQQQ and SQQQ at startup
    cancel_outstanding_buy_orders("TQQQ", trade_client)
    cancel_outstanding_buy_orders("SQQQ", trade_client)

    # Step 2: Fetch Account Equity & Active Positions
    acct = trade_client.get_account()
    total_equity = float(acct.equity)

    all_positions = trade_client.get_all_positions()
    tqqq_pos = next((p for p in all_positions if p.symbol == "TQQQ"), None)
    sqqq_pos = next((p for p in all_positions if p.symbol == "SQQQ"), None)

    # Step 3: Fetch QQQ Historical Bar Data (450 days)
    start_date = datetime.now(tz=ZoneInfo("America/New_York")) - timedelta(days=450)
    req = StockBarsRequest(
        symbol_or_symbols=[underlying_symbol, "TQQQ", "SQQQ"],
        timeframe=TimeFrame.Day,
        start=start_date,
        adjustment=Adjustment.ALL,
    )
    bars = data_client.get_stock_bars(req)
    df_qqq = bars.df.loc[underlying_symbol] if isinstance(bars.df.index, pd.MultiIndex) else bars.df

    qqq_close = df_qqq["close"]

    # Calculate 7 Sub-Strategy Indicators
    ema10 = tv_ema(qqq_close, 10)
    ema20 = tv_ema(qqq_close, 20)
    sma50 = qqq_close.rolling(window=50).mean()
    sma200 = qqq_close.rolling(window=200).mean()
    sma200_slope = sma200.diff(20)
    rsi14 = compute_rsi(qqq_close, period=14)
    sma20, bb_upper, bb_lower = compute_bollinger_bands(qqq_close, period=20, num_std=2.0)

    p_qqq = float(qqq_close.iloc[-1])
    t_ema10 = float(ema10.iloc[-1])
    t_ema20 = float(ema20.iloc[-1])
    t_sma50 = float(sma50.iloc[-1])
    t_sma200 = float(sma200.iloc[-1])
    t_sma200_slope = float(sma200_slope.iloc[-1]) if not math.isnan(sma200_slope.iloc[-1]) else 0.0
    t_rsi = float(rsi14.iloc[-1]) if not math.isnan(rsi14.iloc[-1]) else 50.0

    t_bb_upper = float(bb_upper.iloc[-1])
    t_bb_lower = float(bb_lower.iloc[-1])

    # Evaluate 7 Sub-Strategy Consensus Votes
    s1 = 1 if (p_qqq > t_sma200 and t_sma200_slope > 0) else (-1 if p_qqq < t_sma200 else 0)
    s2 = 1 if p_qqq > t_sma50 else -1
    s3 = 1 if t_ema20 > t_sma50 else -1
    s4 = 1 if t_ema10 > t_ema20 else -1
    s5 = 1 if p_qqq > t_bb_upper else (-1 if p_qqq < t_bb_lower else 0)
    s6 = 1 if (p_qqq > t_sma200 and t_rsi < 45) else (1 if t_rsi < 30 else (-1 if t_rsi > 70 else 0))
    s7 = 1 if p_qqq > t_ema20 else -1

    total_votes = s1 + s2 + s3 + s4 + s5 + s6 + s7

    print("WhiteLight 7 Sub-Strategy Signals:")
    print(f"  Sub-1 (200 SMA Macro): {s1:+d} | Sub-2 (50 SMA Trend): {s2:+d}")
    print(f"  Sub-3 (20/50 EMA Cross): {s3:+d} | Sub-4 (10/20 EMA Fast): {s4:+d}")
    print(f"  Sub-5 (BB Breakout): {s5:+d} | Sub-6 (RSI Dip/Overbought): {s6:+d}")
    print(f"  Sub-7 (Price vs 20 EMA): {s7:+d}")
    print(f"  --> TOTAL CONSENSUS VOTES: {total_votes:+d} / +7\n")

    # Determine Target Allocation
    if total_votes >= 2:
        target_symbol = "TQQQ"
        target_alloc_pct = 0.98
    elif total_votes <= -4:
        target_symbol = "SQQQ"
        target_alloc_pct = 0.50
    else:
        target_symbol = "CASH"
        target_alloc_pct = 0.0

    print(f"Ensemble Decision: Hold {target_symbol} ({target_alloc_pct*100:.0f}% Allocation).")

    # Step 4: Rebalance Positions if Target Symbol differs from current position
    current_symbol = "TQQQ" if tqqq_pos is not None else ("SQQQ" if sqqq_pos is not None else "CASH")

    if current_symbol != target_symbol:
        # Close existing position if changing target
        if tqqq_pos is not None and target_symbol != "TQQQ":
            print("Closing existing TQQQ position...")
            try:
                trade_client.close_position("TQQQ")
            except Exception as e:
                print(f"Error closing TQQQ: {e}")

        if sqqq_pos is not None and target_symbol != "SQQQ":
            print("Closing existing SQQQ position...")
            try:
                trade_client.close_position("SQQQ")
            except Exception as e:
                print(f"Error closing SQQQ: {e}")

        # Step 5: Open Market Hours Guard
        if not is_market_open(trade_client):
            print("Market is currently CLOSED. Skipping new order placement to prevent queued order buildup.")
            return

        # Enter new position if target is TQQQ or SQQQ
        if target_symbol in ["TQQQ", "SQQQ"]:
            target_budget = total_equity * target_alloc_pct
            latest_bars = bars.df.loc[target_symbol] if isinstance(bars.df.index, pd.MultiIndex) else bars.df
            curr_etf_price = float(latest_bars["close"].iloc[-1])

            qty = max(1, int(target_budget // curr_etf_price))
            print(f"Submitting buy order for {qty} shares of {target_symbol} @ ~${curr_etf_price:.2f}...")

            order_req = MarketOrderRequest(
                symbol=target_symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.GTC,
            )
            try:
                order_res = trade_client.submit_order(order_req)
                print(f"Successfully submitted buy order for {target_symbol} ({qty} shares). Order ID: {order_res.id}")
            except Exception as e:
                print(f"Error submitting order for {target_symbol}: {e}")
    else:
        print(f"Current portfolio position ({current_symbol}) matches target allocation ({target_symbol}). No rebalancing required.")


if __name__ == "__main__":
    execute_whitelight_strategy()
