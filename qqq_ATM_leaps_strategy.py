# -*- coding: utf-8 -*-
"""
QQQ LEAPS Trading Strategy Main Execution Script.
"""

import nest_asyncio
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient

from credentials import get_alpaca_credentials
from helpers import (
    get_all_option_positions,
    select_high_interest_ATM_call_leap,
    place_order_with_exit_at_50pct_profit,
    get_latest_price,
    check_bullish_ema_crossover,
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

# Print account status for verification
acct = trade_client.get_account()
acct_config = trade_client.get_account_configurations()

# Strategy execution
if __name__ == "__main__":
    underlying_symbol = "QQQ"

    positions = get_all_option_positions(underlying_symbol, trade_client)
    num_positions = len(positions)

    if num_positions == 0:
        print("No active QQQ option positions found. Entering new LEAP position...")
        selected_contract = select_high_interest_ATM_call_leap(
            underlying_symbol, trade_client, data_client
        )
        place_order_with_exit_at_50pct_profit(selected_contract, trade_client)

    elif num_positions == 1:
        print("Currently holding 1 active QQQ option position.")
        # Add size 1 specific logic here
        print("Checking for 8/21 EMA bullish crossover on QQQ (8 EMA > 21 EMA today, 8 EMA < 21 EMA yesterday)...")
        has_crossover = check_bullish_ema_crossover(
            underlying_symbol, data_client, fast_period=8, slow_period=21
        )

        if has_crossover:
            print("Bullish 8/21 EMA crossover confirmed! Entering second LEAP position...")
            selected_contract = select_high_interest_ATM_call_leap(
                underlying_symbol, trade_client, data_client
            )
            place_order_with_exit_at_50pct_profit(selected_contract, trade_client)
        else:
            print("No bullish 8/21 EMA crossover detected today. Not entering additional position.")

    elif num_positions == 2:
        print("Currently holding 2 active QQQ option positions.")
        # Add size 2 specific logic here

    else:  # num_positions >= 3
        print(f"Maximum position limit reached or exceeded. Not entering new position.")

