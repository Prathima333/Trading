# -*- coding: utf-8 -*-
"""
Helper functions for Alpaca options trading strategy.
"""

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient

from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    MarketOrderRequest,
    LimitOrderRequest,
)
from alpaca.trading.enums import (
    AssetStatus,
    ExerciseStyle,
    OrderSide,
    OrderType,
    TimeInForce,
    AssetClass,
)


def get_latest_price(symbol, data_client):
    """
    Fetches the latest trade price for a given stock symbol using StockHistoricalDataClient.
    """
    request_params = StockLatestTradeRequest(symbol_or_symbols=[symbol])
    latest_trade = data_client.get_stock_latest_trade(request_params)
    return latest_trade[symbol].price


def select_high_interest_ATM_call_leap(symbol, trade_client, data_client):
    """
    Selects the American call LEAP contract (300-400 days out, ~1% ITM/ATM) with the highest open interest.
    """
    now = datetime.now(tz=ZoneInfo("America/New_York"))
    day300 = now + timedelta(days=300)
    day400 = now + timedelta(days=400)

    latest_price = get_latest_price(symbol, data_client)
    min_strike = round(latest_price * 0.99, 2)
    max_strike = round(latest_price * 1.01, 2)

    req = GetOptionContractsRequest(
        underlying_symbols=[symbol],
        status=AssetStatus.ACTIVE,
        expiration_date=None,
        expiration_date_gte=day300.strftime(format="%Y-%m-%d"),
        expiration_date_lte=day400.strftime(format="%Y-%m-%d"),
        root_symbol=None,
        type="call",
        style=ExerciseStyle.AMERICAN,
        strike_price_gte=str(min_strike),
        strike_price_lte=str(max_strike),
        limit=100,
        page_token=None,
    )
    res = trade_client.get_option_contracts(req)
    selected_contract = max(res.option_contracts, key=lambda c: int(c.open_interest))

    if res.next_page_token is not None:
        req = GetOptionContractsRequest(
            underlying_symbols=[symbol],
            status=AssetStatus.ACTIVE,
            expiration_date=None,
            expiration_date_gte=day300.strftime(format="%Y-%m-%d"),
            expiration_date_lte=day400.strftime(format="%Y-%m-%d"),
            root_symbol=None,
            type="call",
            style=ExerciseStyle.AMERICAN,
            strike_price_gte=str(min_strike),
            strike_price_lte=str(max_strike),
            limit=100,
            page_token=res.next_page_token,
        )
        res = trade_client.get_option_contracts(req)
        selected_contract = max(
            selected_contract,
            max(res.option_contracts, key=lambda c: int(c.open_interest)),
            key=lambda obj: int(obj.open_interest),
        )

    return selected_contract


def place_order_with_exit_at_50pct_profit(selected_contract, trade_client):
    """
    Submits a market buy order for the selected contract and places a 50% take-profit limit sell order once filled.
    """
    place_order_req = MarketOrderRequest(
        symbol=selected_contract.symbol,
        qty=1,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
    )
    place_order_res = trade_client.submit_order(place_order_req)

    filled_order = trade_client.get_order_by_id(place_order_res.id)
    while filled_order.status.name != 'FILLED':
        time.sleep(1)
        filled_order = trade_client.get_order_by_id(place_order_res.id)

    actual_fill_price = float(filled_order.filled_avg_price)
    target_price = round(actual_fill_price * 1.5, 2)

    print(f"Order filled exactly at: ${actual_fill_price}")
    print(f"Setting 50% profit exit target at: ${target_price}")

    exit_request = LimitOrderRequest(
        symbol=filled_order.symbol,
        qty=1,
        side=OrderSide.SELL,
        limit_price=target_price,
        time_in_force=TimeInForce.GTC,
    )

    exit_order = trade_client.submit_order(exit_request)
    print("Take-profit limit order successfully placed and waiting!")
    return exit_order


def get_all_option_positions(symbol, trade_client):
    """
    Fetches all active option positions for the given underlying symbol.
    """
    all_positions = trade_client.get_all_positions()

    qqq_option_positions = [
        position for position in all_positions
        if position.asset_class == AssetClass.US_OPTION and position.symbol.startswith(symbol)
    ]

    if qqq_option_positions:
        print(f"Found {len(qqq_option_positions)} active {symbol} option position(s):")
        for pos in qqq_option_positions:
            market_value = float(pos.market_value)
            print(f"Contract: {pos.symbol} | Qty: {pos.qty} | Side: {pos.side.name} | Value: ${market_value:.2f}")
    else:
        print(f"No active {symbol} option positions found in the account.")

    return qqq_option_positions
