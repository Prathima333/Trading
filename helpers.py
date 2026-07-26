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


def is_market_open(trade_client):
    """
    Checks Alpaca Market Clock API. Returns True if market is currently open, False if closed.
    """
    try:
        clock = trade_client.get_clock()
        return bool(clock.is_open)
    except Exception as e:
        print(f"Warning: Could not fetch market clock ({e}). Defaulting to False.")
        return False


def cancel_outstanding_buy_orders(symbol, trade_client):
    """
    Cancels all open or queued limit buy orders for options of symbol at the start of execution
    to prevent duplicate order accumulation.
    """
    print(f"Checking for outstanding open buy orders for {symbol} options...")
    try:
        orders = trade_client.get_orders()
        canceled_count = 0
        for order in orders:
            is_symbol_match = order.symbol.startswith(symbol)
            is_buy = order.side == OrderSide.BUY
            is_open = order.status.name in ['NEW', 'ACCEPTED', 'PENDING_NEW', 'HELD']

            if is_symbol_match and is_buy and is_open:
                print(f"  Canceling open buy order {order.id} for {order.symbol} ({order.qty} units)...")
                trade_client.cancel_order_by_id(order.id)
                canceled_count += 1

        if canceled_count == 0:
            print(f"No outstanding buy orders found for {symbol}.")
        else:
            print(f"Successfully canceled {canceled_count} outstanding buy order(s).")
        return canceled_count
    except Exception as e:
        print(f"Error canceling outstanding buy orders: {e}")
        return 0


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
    Submits buy orders ONLY during open market hours to prevent order accumulation outside market hours.
    """
    if not is_market_open(trade_client):
        print(f"Market is currently CLOSED. Skipping new buy order submission for {selected_contract.symbol} to prevent queued order buildup.")
        return None

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
        print(f"Order status for {selected_contract.symbol}: {filled_order.status.name}.")
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


def close_peak_overbought_positions(symbol, trade_client, data_client, min_unrealized_pl_pct=30.0):
    """
    Peak Exit Rule: If market is overextended (Price >= 1.18 * 200 SMA OR RSI >= 75) AND position has > 30% profit,
    harvests profits immediately near the peak.
    """
    is_overbought, today_price, ratio_200sma, today_rsi = check_peak_overbought_exit(symbol, data_client)

    if not is_overbought:
        return 0

    print(f"Market peak overbought condition detected for {symbol} (Ratio: {ratio_200sma:.2f}x, RSI: {today_rsi:.1f})! Checking profitable positions to harvest...")

    all_positions = trade_client.get_all_positions()
    option_positions = [
        pos for pos in all_positions
        if pos.asset_class == AssetClass.US_OPTION and pos.symbol.startswith(symbol)
    ]

    closed_count = 0
    for pos in option_positions:
        unrealized_plpc = float(pos.unrealized_plpc) * 100.0 if hasattr(pos, 'unrealized_plpc') else 0.0
        if unrealized_plpc >= min_unrealized_pl_pct:
            print(f"Harvesting peak profits on position {pos.symbol} (Unrealized PnL: +{unrealized_plpc:.1f}% >= +{min_unrealized_pl_pct:.1f}%)...")
            try:
                orders = trade_client.get_orders()
                for order in orders:
                    if order.symbol == pos.symbol:
                        print(f"  Canceling open trailing stop order {order.id} for {pos.symbol}...")
                        trade_client.cancel_order_by_id(order.id)

                close_order = trade_client.close_position(pos.symbol)
                print(f"Submitted peak profit close order for {pos.symbol} (ID: {close_order.id}). Waiting for fill...")
                filled_order = wait_for_order_fill(close_order.id, trade_client)
                print(f"Peak profit harvest order status for {pos.symbol}: {filled_order.status.name}.")
                closed_count += 1
            except Exception as e:
                print(f"Error harvesting peak profit for position {pos.symbol}: {e}")

    return closed_count


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


def check_price_above_200sma(symbol, data_client, trend_period=200, slope_lookback=20, require_upward_slope=True):
    """
    Macro Filter: Checks if the current close price of symbol is greater than its 200-day Simple Moving Average (SMA)
    AND optionally enforces that the 200-day SMA is sloping upwards over the last slope_lookback days.
    """
    start_date = datetime.now(tz=ZoneInfo("America/New_York")) - timedelta(days=450)
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
    past_200sma = float(sma_200.iloc[-slope_lookback])

    is_above = today_price > today_200sma
    is_sloping_up = today_200sma > past_200sma

    if require_upward_slope:
        is_bullish_regime = is_above and is_sloping_up
    else:
        is_bullish_regime = is_above

    print(f"Macro Filter Analysis for {symbol} ({trend_period}-day SMA & Slope):")
    print(f"  Today Close: ${today_price:.2f} | 200 SMA: ${today_200sma:.2f} | {slope_lookback}-Day Past SMA: ${past_200sma:.2f}")
    print(f"  Price > 200 SMA: {is_above} | 200 SMA Sloping Up: {is_sloping_up}")
    print(f"  Bullish Regime Active: {is_bullish_regime}")

    return is_bullish_regime


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Computes standard Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def check_peak_overbought_exit(symbol, data_client, stretch_ratio=1.18, rsi_threshold=75.0):
    """
    Peak Exit Rule: Checks if symbol close price is overextended (>= 18% above 200-day SMA) OR RSI >= 75.
    Returns (is_overbought_peak, today_price, ratio_200sma, today_rsi)
    """
    start_date = datetime.now(tz=ZoneInfo("America/New_York")) - timedelta(days=450)
    request_params = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Day,
        start=start_date,
        adjustment=Adjustment.ALL,
    )
    bars = data_client.get_stock_bars(request_params)

    df = bars.df
    close_series = df.loc[symbol]['close'] if isinstance(df.index, pd.MultiIndex) else df['close']

    sma_200 = close_series.rolling(window=200).mean()
    rsi_series = compute_rsi(close_series, period=14)

    today_price = float(close_series.iloc[-1])
    today_200sma = float(sma_200.iloc[-1])
    today_rsi = float(rsi_series.iloc[-1])

    ratio_200sma = today_price / today_200sma if today_200sma > 0 else 1.0

    is_stretched = ratio_200sma >= stretch_ratio
    is_rsi_overbought = today_rsi >= rsi_threshold

    is_overbought_peak = is_stretched or is_rsi_overbought

    print(f"Peak Overbought Analysis for {symbol}:")
    print(f"  Price: ${today_price:.2f} | 200 SMA: ${today_200sma:.2f} | Ratio: {ratio_200sma:.2f}x (Threshold: >={stretch_ratio:.2f}x)")
    print(f"  14-Day RSI: {today_rsi:.1f} (Threshold: >={rsi_threshold:.1f})")
    print(f"  Peak Overbought Signal: {is_overbought_peak}")

    return is_overbought_peak, today_price, ratio_200sma, today_rsi


def check_overbought_entry_allowed(symbol, data_client, max_stretch_ratio=1.18, max_rsi=75.0, resume_stretch_ratio=1.12, resume_rsi=60.0):
    """
    Peak Overbought Entry Block & Resumption Rule:
    Blocks new option entries if QQQ is overbought (Price >= 1.18 * 200 SMA OR RSI >= 75).
    Resumes new entries when QQQ cools down (Price <= 1.12 * 200 SMA AND RSI <= 60).
    Returns (entry_allowed, is_cooldown_active, ratio_200sma, today_rsi)
    """
    start_date = datetime.now(tz=ZoneInfo("America/New_York")) - timedelta(days=450)
    request_params = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Day,
        start=start_date,
        adjustment=Adjustment.ALL,
    )
    bars = data_client.get_stock_bars(request_params)

    df = bars.df
    close_series = df.loc[symbol]['close'] if isinstance(df.index, pd.MultiIndex) else df['close']

    sma_200 = close_series.rolling(window=200).mean()
    rsi_series = compute_rsi(close_series, period=14)

    today_price = float(close_series.iloc[-1])
    today_200sma = float(sma_200.iloc[-1])
    today_rsi = float(rsi_series.iloc[-1])

    ratio_200sma = today_price / today_200sma if today_200sma > 0 else 1.0

    # Overbought entry block check
    is_overbought = (ratio_200sma >= max_stretch_ratio) or (today_rsi >= max_rsi)
    is_cooled_down = (ratio_200sma <= resume_stretch_ratio) and (today_rsi <= resume_rsi)

    entry_allowed = not is_overbought

    print(f"Overbought Entry Filter Analysis for {symbol}:")
    print(f"  Price / 200 SMA Ratio: {ratio_200sma:.2f}x (Block: >={max_stretch_ratio:.2f}x, Resume: <={resume_stretch_ratio:.2f}x)")
    print(f"  14-Day RSI: {today_rsi:.1f} (Block: >={max_rsi:.1f}, Resume: <={resume_rsi:.1f})")
    print(f"  Entry Allowed: {entry_allowed}")

    return entry_allowed, is_overbought, ratio_200sma, today_rsi
