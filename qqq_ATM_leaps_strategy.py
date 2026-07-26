# -*- coding: utf-8 -*-
"""
QQQ LEAPS Trading Strategy Main Execution Script.
Uses Portfolio Allocation % (0%, <40%, <70%) to scale positions based on exact real-time option quotes.
Enforces Macro Regime Filter: Price > 200 SMA AND 200 SMA Sloping Upward.
Enforces Peak Overbought Exit Rules: Price >= 1.18 * 200 SMA OR RSI(14) >= 75.
Enforces Peak Overbought Entry Block & Resumption Thresholds (Price <= 1.12 * 200 SMA AND RSI <= 60).
"""

import nest_asyncio
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient

from credentials import get_alpaca_credentials
from helpers import (
    close_positions_nearing_expiration,
    close_peak_overbought_positions,
    get_all_option_positions,
    get_portfolio_allocation_pct,
    select_high_interest_ITM_call_leap,
    place_order_with_trailing_stop,
    get_latest_price,
    check_bullish_ema_crossover,
    check_price_above_200sma,
    check_peak_overbought_exit,
    check_overbought_entry_allowed,
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
option_data_client = OptionHistoricalDataClient(
    api_key=api_key,
    secret_key=secret_key,
)

# Print account status for verification
acct = trade_client.get_account()
acct_config = trade_client.get_account_configurations()

# Strategy execution
if __name__ == "__main__":
    underlying_symbol = "QQQ"

    # Step 1: Execute 90 DTE exit rule first (close any option position with DTE < 90 days)
    close_positions_nearing_expiration(underlying_symbol, trade_client, min_dte=90)

    # Step 2: Execute Peak Overbought Exit Rule (Price >= 1.18 * 200 SMA OR RSI >= 75)
    close_peak_overbought_positions(underlying_symbol, trade_client, data_client, min_unrealized_pl_pct=30.0)

    # Step 3: Fetch portfolio allocation percentage
    positions, total_equity, total_allocated, allocated_pct = get_portfolio_allocation_pct(
        underlying_symbol, trade_client
    )

    # Step 4: Check Macro Bullish Trend Regime (Price > 200 SMA AND 200 SMA Sloping Upward)
    bullish_regime = check_price_above_200sma(underlying_symbol, data_client, trend_period=200, slope_lookback=20, require_upward_slope=True)

    # Step 5: Check Peak Overbought Entry Block & Resumption Filter
    entry_allowed, is_overbought, ratio_200sma, today_rsi = check_overbought_entry_allowed(underlying_symbol, data_client)

    # Global Entry Guard: Check macro regime & overbought filters before evaluating allocation branches
    if not bullish_regime or not entry_allowed:
        reason = "Macro Bullish Regime INACTIVE" if not bullish_regime else "Market Peak Overbought (Entries Blocked)"
        print(f"Entry blocked: {reason}. Skipping position entries.")
    else:
        # Condition 1: Portfolio allocation < 30%
        if allocated_pct < 30.0:
            target_pct = (30.0 - allocated_pct) / 100.0
            print(f"Allocation is {allocated_pct:.2f}% (< 30%). Bullish regime active and entry allowed! Entering ITM LEAP position (Target Budget: {target_pct*100:.1f}%)...")
            selected_contract = select_high_interest_ITM_call_leap(
                underlying_symbol, trade_client, data_client, itm_discount_pct=0.07
            )
            place_order_with_trailing_stop(
                selected_contract, trade_client, option_data_client, target_pct=target_pct, trail_percent=15.0
            )

        # Condition 2: Portfolio allocation < 40%
        elif allocated_pct < 40.0:
            print(f"Current QQQ option allocation is {allocated_pct:.2f}% (< 40%).")
            print("Checking for 8/21 EMA bullish crossover on QQQ (8 EMA > 21 EMA today, 8 EMA < 21 EMA yesterday)...")
            has_crossover = check_bullish_ema_crossover(
                underlying_symbol, data_client, fast_period=8, slow_period=21
            )

            if has_crossover:
                print("Bullish 8/21 EMA crossover confirmed! Entering 2nd ITM LEAP position (~30% portfolio equity)...")
                selected_contract = select_high_interest_ITM_call_leap(
                    underlying_symbol, trade_client, data_client, itm_discount_pct=0.07
                )
                place_order_with_trailing_stop(
                    selected_contract, trade_client, option_data_client, target_pct=0.30, trail_percent=15.0
                )
            else:
                print("No bullish 8/21 EMA crossover detected today. Not entering additional position.")

        # Condition 3: Portfolio allocation < 70%
        elif allocated_pct < 70.0:
            print(f"Current QQQ option allocation is {allocated_pct:.2f}% (< 70%).")
            print("Checking for 21/200 EMA bullish crossover on QQQ (21 EMA > 200 EMA today, 21 EMA < 200 EMA yesterday)...")
            has_crossover = check_bullish_ema_crossover(
                underlying_symbol, data_client, fast_period=21, slow_period=200
            )

            if has_crossover:
                print("Bullish 21/200 EMA crossover confirmed! Entering 3rd ITM LEAP position (~30% portfolio equity)...")
                selected_contract = select_high_interest_ITM_call_leap(
                    underlying_symbol, trade_client, data_client, itm_discount_pct=0.07
                )
                place_order_with_trailing_stop(
                    selected_contract, trade_client, option_data_client, target_pct=0.30, trail_percent=15.0
                )
            else:
                print("No bullish 21/200 EMA crossover detected today. Not entering additional position.")

        # Condition 4: Portfolio allocation >= 70%
        else:  # allocated_pct >= 70.0
            print(f"Maximum allocation limit reached ({allocated_pct:.2f}% >= 70.0%). Not entering new position.")
