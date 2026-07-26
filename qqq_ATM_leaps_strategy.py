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

    if get_all_option_positions(underlying_symbol, trade_client):
        print("Already in QQQ. Not entering new position.")
    else:
        selected_contract = select_high_interest_ATM_call_leap(
            underlying_symbol, trade_client, data_client
        )
        place_order_with_exit_at_50pct_profit(selected_contract, trade_client)
