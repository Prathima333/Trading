# -*- coding: utf-8 -*-
"""
WhiteLight TQQQ/SQQQ Systematic Strategy Main Execution Script.
Trades TQQQ (3x Bullish Nasdaq-100) & SQQQ (3x Bearish Nasdaq-100) / Cash based on QQQ technical signals.

Key Safety Features:
- Market hours check (is_market_open): Skips order placement outside open market hours.
- Auto-cancellation of open buy orders at startup (cancel_outstanding_buy_orders).
- Enforces 200 SMA Slope Macro Filter on QQQ.
- Enforces Bollinger Bands (20 SMA, 2.0 Std Dev) & 14-Day RSI.
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
    check_peak_overbought_exit,
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
    """Executes the WhiteLight TQQQ/SQQQ Systematic Strategy on Alpaca."""
    underlying_symbol = "QQQ"
    print("\n=======================================================")
    print("   WHITELIGHT TQQQ/SQQQ STRATEGY SYSTEMATIC EXECUTION   ")
    print("=======================================================\n")

    # Step 1: Auto-cancel any open buy orders for TQQQ and SQQQ at startup
    cancel_outstanding_buy_orders("TQQQ", trade_client)
    cancel_outstanding_buy_orders("SQQQ", trade_client)

    # Step 2: Fetch Account Equity & Active Positions
    acct = trade_client.get_account()
    total_equity = float(acct.equity)
    cash_balance = float(acct.cash)

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
    ema20 = tv_ema(qqq_close, 20)
    sma200 = qqq_close.rolling(window=200).mean()
    sma200_slope = sma200.diff(20)
    rsi14 = compute_rsi(qqq_close, period=14)
    sma20, bb_upper, bb_lower = compute_bollinger_bands(qqq_close, period=20, num_std=2.0)

    p_qqq = float(qqq_close.iloc[-1])
    y_qqq = float(qqq_close.iloc[-2])
    t_ema20 = float(ema20.iloc[-1])
    t_sma200 = float(sma200.iloc[-1])
    t_sma200_slope = float(sma200_slope.iloc[-1]) if not math.isnan(sma200_slope.iloc[-1]) else 0.0
    t_rsi = float(rsi14.iloc[-1]) if not math.isnan(rsi14.iloc[-1]) else 50.0

    t_bb_upper = float(bb_upper.iloc[-1])
    t_bb_lower = float(bb_lower.iloc[-1])
    y_bb_upper = float(bb_upper.iloc[-2])

    bullish_regime = (p_qqq > t_sma200) and (t_sma200_slope > 0)
    bearish_regime = (p_qqq < t_sma200) and (t_sma200_slope < 0)

    print(f"Market Signal Analysis for {underlying_symbol}:")
    print(f"  Close: ${p_qqq:.2f} | 200 SMA: ${t_sma200:.2f} | 200 SMA Slope: ${t_sma200_slope:.2f}")
    print(f"  20 EMA: ${t_ema20:.2f} | Upper BB: ${t_bb_upper:.2f} | Lower BB: ${t_bb_lower:.2f}")
    print(f"  14-Day RSI: {t_rsi:.1f}")
    print(f"  Regime: Bullish={bullish_regime} | Bearish={bearish_regime}\n")

    # Step 4: Manage Existing Positions (TQQQ / SQQQ)
    if tqqq_pos is not None:
        unrealized_plpc = float(tqqq_pos.unrealized_plpc) * 100.0 if hasattr(tqqq_pos, "unrealized_plpc") else 0.0
        print(f"Active TQQQ Position: {tqqq_pos.qty} shares (Unrealized PnL: {unrealized_plpc:+.1f}%).")

        # Exit Signal: Regime reversed OR RSI overbought (>72)
        if not bullish_regime or t_rsi >= 72.0 or p_qqq >= t_bb_upper:
            print(f"Exit signal triggered for TQQQ (Bullish Regime={bullish_regime}, RSI={t_rsi:.1f}). Closing position...")
            try:
                trade_client.close_position("TQQQ")
                print("Submitted position close order for TQQQ.")
            except Exception as e:
                print(f"Error closing TQQQ position: {e}")

    if sqqq_pos is not None:
        unrealized_plpc = float(sqqq_pos.unrealized_plpc) * 100.0 if hasattr(sqqq_pos, "unrealized_plpc") else 0.0
        print(f"Active SQQQ Position: {sqqq_pos.qty} shares (Unrealized PnL: {unrealized_plpc:+.1f}%).")

        # Exit Signal: Bearish regime inactive
        if not bearish_regime:
            print(f"Exit signal triggered for SQQQ (Bearish Regime={bearish_regime}). Closing position...")
            try:
                trade_client.close_position("SQQQ")
                print("Submitted position close order for SQQQ.")
            except Exception as e:
                print(f"Error closing SQQQ position: {e}")

    # Step 5: Open Market Hours Guard
    if not is_market_open(trade_client):
        print("Market is currently CLOSED. Skipping new order placement to prevent queued order buildup.")
        return

    # Step 6: Evaluate New Positions (Only if in Cash)
    if tqqq_pos is None and sqqq_pos is None:
        tqqq_breakout = bullish_regime and (y_qqq <= y_bb_upper) and (p_qqq > t_bb_upper)
        tqqq_dip = bullish_regime and (p_qqq <= t_ema20) and (t_rsi < 45.0)
        sqqq_breakdown = bearish_regime and (p_qqq < t_bb_lower) and (t_rsi < 35.0)

        if tqqq_breakout or tqqq_dip:
            target_symbol = "TQQQ"
            target_alloc_pct = 0.95
            reason = "Breakout" if tqqq_breakout else "Mean Reversion Dip"
        elif sqqq_breakdown:
            target_symbol = "SQQQ"
            target_alloc_pct = 0.50
            reason = "Bearish Breakdown"
        else:
            print("No entry signals triggered today. Portfolio remains 100% Cash.")
            return

        target_budget = total_equity * target_alloc_pct
        latest_bars = bars.df.loc[target_symbol] if isinstance(bars.df.index, pd.MultiIndex) else bars.df
        curr_etf_price = float(latest_bars["close"].iloc[-1])

        qty = max(1, int(target_budget // curr_etf_price))
        print(f"Entry Signal Triggered ({reason}): Buying {qty} shares of {target_symbol} @ ~${curr_etf_price:.2f}...")

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


if __name__ == "__main__":
    execute_whitelight_strategy()
