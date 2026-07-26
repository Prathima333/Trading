# -*- coding: utf-8 -*-
"""
Helper functions for Alpaca ITM LEAPS options trading strategy.
"""

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient

from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment
from alpaca.data.requests import (
    StockLatestTradeRequest,
    StockBarsRequest,
    OptionLatestQuoteRequest,
)
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    MarketOrderRequest,
    LimitOrderRequest,
    TrailingStopOrderRequest,
)
from alpaca.trading.enums import (
    AssetStatus,
    ExerciseStyle,
    OrderSide,
    OrderType,
    TimeInForce,
    AssetClass,
)


def wait_for_order_fill(order_id, trade_client, max_attempts=5, delay_seconds=1):
    """
    Reusable Helper Function: Polls and waits until an order reaches 'FILLED' status or until max_attempts timeout.
    Returns the updated order object.
    """
    attempts = 0
    filled_order = trade_client.get_order_by_id(order_id)
    while filled_order.status.name != 'FILLED' and attempts < max_attempts:
        time.sleep(delay_seconds)
        attempts += 1
        filled_order = trade_client.get_order_by_id(order_id)
    return filled_order


def get_latest_price(symbol, data_client):
    """
    Fetches the latest trade price for a given stock symbol using StockHistoricalDataClient.
    """
    request_params = StockLatestTradeRequest(symbol_or_symbols=[symbol])
    latest_trade = data_client.get_stock_latest_trade(request_params)
    return latest_trade[symbol].price


def select_high_interest_ITM_call_leap(symbol, trade_client, data_client, itm_discount_pct=0.07):
    """
    Selects the 70-75 Delta ITM American call LEAP contract (300-400 days out, ~7% ITM strike) with highest open interest.
    """
    now = datetime.now(tz=ZoneInfo("America/New_York"))
    day300 = now + timedelta(days=300)
    day400 = now + timedelta(days=400)

    latest_price = get_latest_price(symbol, data_client)
    target_strike = latest_price * (1.0 - itm_discount_pct)
    min_strike = round(target_strike * 0.98, 2)
    max_strike = round(target_strike * 1.02, 2)

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


def calculate_position_quantity(selected_contract, trade_client, data_client, target_pct=0.30):
    """
    Calculates exact number of contract units to buy based on deploying ~30% of total portfolio equity
    using the real-time ask price of the selected option contract.
    Returns (qty, opt_price)
    """
    acct = trade_client.get_account()
    total_equity = float(acct.equity)
    target_budget = total_equity * target_pct

    # Fetch exact real-time quote for selected option contract
    quote_req = OptionLatestQuoteRequest(symbol_or_symbols=[selected_contract.symbol])
    quotes = data_client.get_option_latest_quote(quote_req)
    contract_quote = quotes[selected_contract.symbol]

    opt_price = float(contract_quote.ask_price) if float(contract_quote.ask_price) > 0 else float(contract_quote.bid_price)
    contract_cost = opt_price * 100.0

    qty = max(1, int(target_budget // contract_cost))
    print(f"Position Sizing: Portfolio Equity = ${total_equity:,.2f} | Target Budget ({target_pct*100:.1f}%) = ${target_budget:,.2f} | Contract Ask = ${opt_price:.2f} (Cost/unit = ${contract_cost:,.2f}) | Qty = {qty}")
    return qty, opt_price


def place_order_with_trailing_stop(selected_contract, trade_client, data_client, target_pct=0.30, trail_percent=15.0):
    """
    Submits a limit buy order (at ask price) for ~30% portfolio equity allocation and places a 15% trailing stop exit order once filled.
    Supports submission both during market hours and outside market hours.
    """
    qty, opt_price = calculate_position_quantity(selected_contract, trade_client, data_client, target_pct=target_pct)

    place_order_req = LimitOrderRequest(
        symbol=selected_contract.symbol,
        qty=qty,
        side=OrderSide.BUY,
        limit_price=opt_price,
        time_in_force=TimeInForce.GTC,
    )
    place_order_res = trade_client.submit_order(place_order_req)
    print(f"Submitted limit buy order for {selected_contract.symbol} ({qty} units @ ${opt_price:.2f}). Order ID: {place_order_res.id}")

    filled_order = wait_for_order_fill(place_order_res.id, trade_client)

    if filled_order.status.name == 'FILLED':
        actual_fill_price = float(filled_order.filled_avg_price)
        print(f"Order filled ({qty} units) at avg price: ${actual_fill_price:.2f}")
        print(f"Setting {trail_percent}% trailing stop loss exit order for {qty} units...")

        exit_request = TrailingStopOrderRequest(
            symbol=filled_order.symbol,
            qty=qty,
            side=OrderSide.SELL,
            trail_percent=trail_percent,
            time_in_force=TimeInForce.GTC,
        )
        exit_order = trade_client.submit_order(exit_request)
        print("Trailing stop exit order successfully placed and active!")
        return exit_order
    else:
        print(f"Order status for {selected_contract.symbol}: {filled_order.status.name} (queued for execution when market opens).")
        return filled_order


def close_positions_nearing_expiration(symbol, trade_client, min_dte=90):
    """
    Inspects open option positions for symbol.
    If Days To Expiration (DTE) < min_dte (default 90 days), cancels open orders and closes the position.
    """
    print(f"Checking for open option positions with DTE < {min_dte} days...")
    all_positions = trade_client.get_all_positions()
    today = datetime.now(tz=ZoneInfo("America/New_York")).date()

    option_positions = [
        pos for pos in all_positions
        if pos.asset_class == AssetClass.US_OPTION and pos.symbol.startswith(symbol)
    ]

    closed_count = 0
    for pos in option_positions:
        dte = None
        try:
            contract = trade_client.get_option_contract(pos.symbol)
            exp_date = contract.expiration_date
            exp_dt = exp_date if hasattr(exp_date, "strftime") else datetime.strptime(str(exp_date), "%Y-%m-%d").date()
            dte = (exp_dt - today).days
        except Exception:
            try:
                import re
                match = re.search(r'([0-9]{6})[CP]', pos.symbol)
                if match:
                    exp_dt = datetime.strptime("20" + match.group(1), "%Y%m%d").date()
                    dte = (exp_dt - today).days
            except Exception:
                pass

        if dte is not None and dte < min_dte:
            print(f"Closing position {pos.symbol} (DTE = {dte} days < {min_dte} days) to prevent accelerated theta decay...")
            try:
                orders = trade_client.get_orders()
                for order in orders:
                    if order.symbol == pos.symbol:
                        print(f"  Canceling open exit order {order.id} for {pos.symbol}...")
                        trade_client.cancel_order_by_id(order.id)
                
                close_order = trade_client.close_position(pos.symbol)
                print(f"Submitted close order for {pos.symbol} (ID: {close_order.id}). Waiting for fill...")

                filled_order = wait_for_order_fill(close_order.id, trade_client)

                if filled_order.status.name == 'FILLED':
                    print(f"Successfully closed position {pos.symbol} at avg fill price: ${filled_order.filled_avg_price}.")
                else:
                    print(f"Close order status for {pos.symbol}: {filled_order.status.name}.")

                closed_count += 1
            except Exception as e:
                print(f"Error closing position {pos.symbol}: {e}")

    if closed_count == 0:
        print(f"No option positions with DTE < {min_dte} days were found.")


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


def get_portfolio_allocation_pct(symbol, trade_client):
    """
    Calculates percentage of total account equity currently allocated to active option positions for symbol.
    Returns (positions_list, total_equity, total_allocated_value, allocation_pct)
    """
    acct = trade_client.get_account()
    total_equity = float(acct.equity)

    positions = get_all_option_positions(symbol, trade_client)
    total_allocated = sum(float(pos.market_value) for pos in positions)
    
    allocated_pct = (total_allocated / total_equity * 100.0) if total_equity > 0 else 0.0
    print(f"Portfolio Allocation Analysis for {symbol}:")
    print(f"  Account Equity: ${total_equity:,.2f} | Options Value: ${total_allocated:,.2f} | Allocated: {allocated_pct:.2f}%")

    return positions, total_equity, total_allocated, allocated_pct


def tv_ema(series: pd.Series, period: int) -> pd.Series:
    """TradingView standard Exponential Moving Average (EMA) with initial SMA seeding."""
    ema = np.zeros_like(series, dtype=float)
    ema[period - 1] = series.iloc[:period].mean()
    multiplier = 2 / (period + 1)
    for i in range(period, len(series)):
        ema[i] = (series.iloc[i] - ema[i - 1]) * multiplier + ema[i - 1]
    ema[:period - 1] = np.nan
    return pd.Series(ema, index=series.index)


def check_bullish_ema_crossover(symbol, data_client, fast_period=8, slow_period=21):
    """
    Checks if a bullish EMA crossover occurred for the given symbol using split/dividend-adjusted daily bars.
    Returns True if today's fast_period EMA > slow_period EMA while yesterday's fast_period EMA < slow_period EMA.
    """
    start_date = datetime.now(tz=ZoneInfo("America/New_York")) - timedelta(days=365)
    request_params = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Day,
        start=start_date,
        adjustment=Adjustment.ALL,
    )
    bars = data_client.get_stock_bars(request_params)

    df = bars.df
    close_series = df.loc[symbol]['close'] if isinstance(df.index, pd.MultiIndex) else df['close']

    ema_fast = tv_ema(close_series, fast_period)
    ema_slow = tv_ema(close_series, slow_period)

    today_fast = float(ema_fast.iloc[-1])
    today_slow = float(ema_slow.iloc[-1])
    yesterday_fast = float(ema_fast.iloc[-2])
    yesterday_slow = float(ema_slow.iloc[-2])

    crossover = (yesterday_fast < yesterday_slow) and (today_fast > today_slow)

    print(f"EMA Analysis for {symbol} ({fast_period} EMA vs {slow_period} EMA):")
    print(f"  Yesterday: {fast_period} EMA = ${yesterday_fast:.2f}, {slow_period} EMA = ${yesterday_slow:.2f}")
    print(f"  Today:     {fast_period} EMA = ${today_fast:.2f}, {slow_period} EMA = ${today_slow:.2f}")
    print(f"  Bullish Crossover: {crossover}")

    return crossover


def check_price_above_200sma(symbol, data_client, trend_period=200):
    """
    Macro Filter: Checks if the current close price of symbol is greater than its 200-day Simple Moving Average (SMA).
    """
    start_date = datetime.now(tz=ZoneInfo("America/New_York")) - timedelta(days=400)
    request_params = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Day,
        start=start_date,
        adjustment=Adjustment.ALL,
    )
    bars = data_client.get_stock_bars(request_params)

    df = bars.df
    close_series = df.loc[symbol]['close'] if isinstance(df.index, pd.MultiIndex) else df['close']

    sma_200 = close_series.rolling(window=trend_period).mean()

    today_price = float(close_series.iloc[-1])
    today_200sma = float(sma_200.iloc[-1])

    is_above = today_price > today_200sma

    print(f"Macro Filter Analysis for {symbol} (Price vs {trend_period}-day SMA):")
    print(f"  Today Close: ${today_price:.2f} | {trend_period} SMA: ${today_200sma:.2f}")
    print(f"  Price > {trend_period} SMA: {is_above}")

    return is_above
