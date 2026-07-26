# -*- coding: utf-8 -*-
"""
QQQ LEAPS Trading Strategy Main Execution Script.
Uses Portfolio Allocation % (0%, <40%, <70%) to scale positions based on exact real-time option quotes.
"""

import nest_asyncio
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient

from credentials import get_alpaca_credentials
from helpers import (
    close_positions_nearing_expiration,
    get_all_option_positions,
    get_portfolio_allocation_pct,
    select_high_interest_ITM_call_leap,
    place_order_with_trailing_stop,
    get_latest_price,
    check_bullish_ema_crossover,
    check_price_above_200sma,
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

    # Step 2: Fetch portfolio allocation percentage
    positions, total_equity, total_allocated, allocated_pct = get_portfolio_allocation_pct(
        underlying_symbol, trade_client
    )

    # Condition 1: 0% portfolio allocated to QQQ options
    if allocated_pct == 0 or len(positions) == 0:
        print("0% portfolio allocated to QQQ options. Entering 1st ITM LEAP position (~30% portfolio equity)...")
        selected_contract = select_high_interest_ITM_call_leap(
            underlying_symbol, trade_client, data_client, itm_discount_pct=0.07
        )
        place_order_with_trailing_stop(
            selected_contract, trade_client, option_data_client, target_pct=0.30, trail_percent=15.0
        )

    # Condition 2: Portfolio allocation < 40%
    elif allocated_pct < 40.0:
        print(f"Current QQQ option allocation is {allocated_pct:.2f}% (< 40%).")
        print("Checking for 8/21 EMA bullish crossover on QQQ (8 EMA > 21 EMA today, 8 EMA < 21 EMA yesterday)...")
        has_crossover = check_bullish_ema_crossover(
            underlying_symbol, data_client, fast_period=8, slow_period=21
        )
        price_above_200sma = check_price_above_200sma(underlying_symbol, data_client)

        if has_crossover and price_above_200sma:
            print(f"Bullish 8/21 EMA crossover confirmed! Entering 2nd ITM LEAP position (~30% portfolio equity)...")
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
        price_above_200sma = check_price_above_200sma(underlying_symbol, data_client)

        if has_crossover and price_above_200sma:
            print(f"Bullish 21/200 EMA crossover confirmed! Entering 3rd ITM LEAP position (~30% portfolio equity)...")
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
