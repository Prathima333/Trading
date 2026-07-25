{
  "cells": [
    {
      "cell_type": "markdown",
      "metadata": {
        "id": "view-in-github",
        "colab_type": "text"
      },
      "source": [
        "<a href=\"https://colab.research.google.com/github/Prathima333/Trading/blob/main/prathimad_qqq_leaps_strategy.py\" target=\"_parent\"><img src=\"https://colab.research.google.com/assets/colab-badge.svg\" alt=\"Open In Colab\"/></a>"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {
        "id": "LM-HNVPwaVLj"
      },
      "source": [
        "# Alpaca-py options trading basic"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {
        "id": "2gct4xfNaVLk"
      },
      "source": [
        "[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/alpacahq/alpaca-py/blob/master/examples/options/options-trading-basic.ipynb)"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {
        "id": "vAnzSMvxaVLl"
      },
      "source": [
        "- This notebook shows how to use alpaca-py with options trading API endpoints\n",
        "- Please use ``paper account``. Please ``DO NOT`` use this notebook with live account. In this notebook, we place orders for options as an example."
      ]
    },
    {
      "cell_type": "markdown",
      "source": [],
      "metadata": {
        "id": "3XNMBy9Dkbr7"
      }
    },
    {
      "cell_type": "markdown",
      "metadata": {
        "id": "S2ZkDIfhkcVH"
      },
      "source": [
        "# Setup"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": 1,
      "metadata": {
        "id": "e2PHq8M3aVLl"
      },
      "outputs": [],
      "source": [
        "#### We use paper environment for this example ####\n",
        "paper = True # Please do not modify this. This example is for paper trading only.\n",
        "####\n",
        "\n",
        "# Below are the variables for development this documents\n",
        "# Please do not change these variables\n",
        "\n",
        "trade_api_url = None\n",
        "trade_api_wss = None\n",
        "data_api_url = None\n",
        "option_stream_data_wss = None"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": 11,
      "metadata": {
        "id": "EJMlboSfaVLn",
        "colab": {
          "base_uri": "https://localhost:8080/"
        },
        "outputId": "732c8614-5115-4cfc-ae96-8db4397f5912"
      },
      "outputs": [
        {
          "output_type": "stream",
          "name": "stdout",
          "text": [
            "Running in Colab: Fetching from userdata...\n"
          ]
        }
      ],
      "source": [
        "# install alpaca-py if it is not available\n",
        "try:\n",
        "    import alpaca\n",
        "except ImportError:\n",
        "    !python3 -m pip install alpaca-py\n",
        "    import alpaca\n",
        "\n",
        "import os, json, time\n",
        "from datetime import datetime, timedelta\n",
        "from zoneinfo import ZoneInfo\n",
        "\n",
        "from alpaca.trading.client import TradingClient\n",
        "from alpaca.data.timeframe import TimeFrame, TimeFrameUnit\n",
        "from alpaca.data.historical.option import OptionHistoricalDataClient\n",
        "from alpaca.trading.stream import TradingStream\n",
        "from alpaca.data.live.option import OptionDataStream\n",
        "from alpaca.data.historical.corporate_actions import CorporateActionsClient\n",
        "from alpaca.data.historical.stock import StockHistoricalDataClient\n",
        "from alpaca.data.live.stock import StockDataStream\n",
        "\n",
        "from alpaca.data.requests import (\n",
        "    OptionBarsRequest,\n",
        "    OptionTradesRequest,\n",
        "    OptionLatestQuoteRequest,\n",
        "    OptionLatestTradeRequest,\n",
        "    OptionSnapshotRequest,\n",
        "    OptionChainRequest,\n",
        "\n",
        "    CorporateActionsRequest,\n",
        "    StockBarsRequest,\n",
        "    StockQuotesRequest,\n",
        "    StockTradesRequest,\n",
        "    StockLatestTradeRequest,\n",
        ")\n",
        "from alpaca.trading.requests import (\n",
        "    GetOptionContractsRequest,\n",
        "    GetAssetsRequest,\n",
        "    MarketOrderRequest,\n",
        "    GetOrdersRequest,\n",
        "    ClosePositionRequest,\n",
        "\n",
        "    LimitOrderRequest,\n",
        "    StopLimitOrderRequest,\n",
        "    StopLossRequest,\n",
        "    StopOrderRequest,\n",
        "    TakeProfitRequest,\n",
        "    TrailingStopOrderRequest,\n",
        ")\n",
        "from alpaca.trading.enums import (\n",
        "    AssetStatus,\n",
        "    ExerciseStyle,\n",
        "    OrderSide,\n",
        "    OrderType,\n",
        "    TimeInForce,\n",
        "    QueryOrderStatus,\n",
        "\n",
        "    AssetExchange,\n",
        "    AssetClass,\n",
        "    OrderClass,\n",
        ")\n",
        "from alpaca.common.exceptions import APIError\n",
        "\n",
        "# to run async code in jupyter notebook\n",
        "import nest_asyncio\n",
        "nest_asyncio.apply()\n",
        "\n",
        "# check version of alpaca-py\n",
        "alpaca.__version__\n",
        "\n",
        "# Please change the following to your own PAPER api key and secret\n",
        "# or set them as environment variables (ALPACA_API_KEY, ALPACA_SECRET_KEY).\n",
        "# You can get them from https://alpaca.markets/\n",
        "\n",
        "api_key = ''\n",
        "secret_key = ''\n",
        "\n",
        "# Try to import Colab's userdata module\n",
        "try:\n",
        "    from google.colab import userdata\n",
        "    IN_COLAB = True\n",
        "except ImportError:\n",
        "    IN_COLAB = False\n",
        "\n",
        "# Fetch the secret based on the environment\n",
        "if IN_COLAB:\n",
        "    print(\"Running in Colab: Fetching from userdata...\")\n",
        "    api_key = userdata.get('ALPACA_API_KEY')\n",
        "    secret_key = userdata.get('ALPACA_SECRET_KEY')\n",
        "else:\n",
        "    print(\"Running outside Colab: Fetching from OS environment...\")\n",
        "    # This will pull from the GitHub Actions YAML 'env' block\n",
        "    api_key = os.environ.get('ALPACA_API_KEY')\n",
        "    secret_key = os.environ.get('ALPACA_SECRET_KEY')"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {
        "id": "T5TaKkb6aVLo"
      },
      "source": [
        "# Helper Functions(No Execution)"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": 3,
      "metadata": {
        "id": "EzgHfHOnaVLo"
      },
      "outputs": [],
      "source": [
        "# setup clients\n",
        "trade_client = TradingClient(api_key=api_key, secret_key=secret_key, paper=paper, url_override=trade_api_url)\n",
        "data_client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)\n",
        "\n",
        "\n",
        "# check trading account\n",
        "# There are trhee new columns in the account object:\n",
        "# - options_buying_power\n",
        "# - options_approved_level\n",
        "# - options_trading_level\n",
        "acct = trade_client.get_account()\n",
        "\n",
        "# check account configuration\n",
        "# - we have new field `max_options_trading_level`\n",
        "acct_config = trade_client.get_account_configurations()"
      ]
    },
    {
      "cell_type": "code",
      "source": [
        "def get_latest_price(symbol):\n",
        "    \"\"\"\n",
        "    Fetches the latest trade price for a given stock symbol.\n",
        "    \"\"\"\n",
        "\n",
        "    # 1. Build the request object for the provided symbol\n",
        "    request_params = StockLatestTradeRequest(symbol_or_symbols=[symbol])\n",
        "\n",
        "    # 2. Fetch the latest trade data\n",
        "    latest_trade = data_client.get_stock_latest_trade(request_params)\n",
        "\n",
        "    # 3. Extract and return the price value\n",
        "    #display(latest_trade)\n",
        "    return latest_trade[symbol].price"
      ],
      "metadata": {
        "id": "UH1q29azunKd"
      },
      "execution_count": 4,
      "outputs": []
    },
    {
      "cell_type": "code",
      "execution_count": 5,
      "metadata": {
        "id": "vEVYDmqUaVLp",
        "collapsed": true
      },
      "outputs": [],
      "source": [
        "def select_high_interest_call_leap(symbol):\n",
        "    # specify expiration date range\n",
        "    now = datetime.now(tz = ZoneInfo(\"America/New_York\"))\n",
        "    day300 = now + timedelta(days = 300)\n",
        "    day400 = now + timedelta(days = 400)\n",
        "\n",
        "    latest_price = get_latest_price(symbol)\n",
        "    # 1. Calculate the 1% lower boundary\n",
        "    # We use round() to ensure standard strike price formatting\n",
        "    min_strike = round(latest_price * 0.99, 2)\n",
        "    max_strike = round(latest_price * 1.01, 2) # Optional: if you want a strict 1% ceiling\n",
        "\n",
        "\n",
        "    req = GetOptionContractsRequest(\n",
        "          underlying_symbols = [symbol],                     # specify underlying symbols\n",
        "          status = AssetStatus.ACTIVE,                                 # specify asset status: active (default)\n",
        "          expiration_date = None,                                      # specify expiration date (specified date + 1 day range)\n",
        "          expiration_date_gte = day300.strftime(format = \"%Y-%m-%d\"),                           # we can pass date object\n",
        "          expiration_date_lte = day400.strftime(format = \"%Y-%m-%d\"),   # or string\n",
        "          root_symbol = None,                                          # specify root symbol\n",
        "          type = \"call\",                                                # specify option type: put\n",
        "          style = ExerciseStyle.AMERICAN,                              # specify option style: american\n",
        "          strike_price_gte = str(min_strike),                     # specify strike price range\n",
        "          strike_price_lte = str(max_strike),                     # specify strike price range\n",
        "          limit = 100,                                                 # specify limit\n",
        "          page_token = None,                                          # specify page\n",
        "      )\n",
        "    res = trade_client.get_option_contracts(req)\n",
        "    selected_contract = max(res.option_contracts, key=lambda c: int(c.open_interest))\n",
        "\n",
        "    if res.next_page_token is not None:\n",
        "      req = GetOptionContractsRequest(\n",
        "          underlying_symbols = [symbol],                     # specify underlying symbols\n",
        "          status = AssetStatus.ACTIVE,                                 # specify asset status: active (default)\n",
        "          expiration_date = None,                                      # specify expiration date (specified date + 1 day range)\n",
        "          expiration_date_gte = day300.strftime(format = \"%Y-%m-%d\"),                           # we can pass date object\n",
        "          expiration_date_lte = day400.strftime(format = \"%Y-%m-%d\"),   # or string\n",
        "          root_symbol = None,                                          # specify root symbol\n",
        "          type = \"call\",                                                # specify option type: put\n",
        "          style = ExerciseStyle.AMERICAN,                              # specify option style: american\n",
        "          strike_price_gte = str(min_strike),                                       # specify strike price range\n",
        "          strike_price_lte = str(max_strike),                                   # specify strike price range\n",
        "          limit = 100,                                                 # specify limit\n",
        "          page_token = res.next_page_token,                                           # specify page\n",
        "      )\n",
        "      res = trade_client.get_option_contracts(req)\n",
        "      selected_contract = max(selected_contract,\n",
        "                              max(res.option_contracts, key=lambda c: int(c.open_interest)),\n",
        "                              key=lambda obj: int(obj.open_interest))\n",
        "      #display(res)\n",
        "\n",
        "    #display(selected_contract)\n",
        "    return selected_contract"
      ]
    },
    {
      "cell_type": "code",
      "execution_count": 6,
      "metadata": {
        "id": "QUSTTMUhaVLp"
      },
      "outputs": [],
      "source": [
        "def place_order_with_exit_at_50pct_profit(selected_contract):\n",
        "    # place buy put option order\n",
        "    # - we can place buy put option order same as buy stock/crypto order\n",
        "    place_order_req = MarketOrderRequest(\n",
        "        symbol = selected_contract.symbol,\n",
        "        qty = 1,\n",
        "        side = OrderSide.BUY,\n",
        "        type = OrderType.MARKET,\n",
        "        time_in_force = TimeInForce.DAY,\n",
        "    )\n",
        "    place_order_res = trade_client.submit_order(place_order_req)\n",
        "\n",
        "\n",
        "    # 2. Wait for the order  to fill to get the true execution price\n",
        "    # (Using a simple while loop here to check the status every 1 second)\n",
        "    filled_order = trade_client.get_order_by_id(place_order_res.id)\n",
        "    while filled_order.status.name != 'FILLED':\n",
        "        time.sleep(1)\n",
        "        filled_order = trade_client.get_order_by_id(place_order_res.id)\n",
        "\n",
        "    # 3. Calculate the 50% profit target\n",
        "    actual_fill_price = float(filled_order.filled_avg_price)\n",
        "    target_price = round(actual_fill_price * 1.5, 2)\n",
        "\n",
        "    print(f\"Order filled exactly at: ${actual_fill_price}\")\n",
        "    print(f\"Setting 50% profit exit target at: ${target_price}\")\n",
        "\n",
        "    # 4. Place the Take-Profit Limit Order\n",
        "    # Using GTC (Good 'Til Canceled) so it remains active across multiple trading days\n",
        "    exit_request = LimitOrderRequest(\n",
        "        symbol=filled_order.symbol,\n",
        "        qty=1,\n",
        "        side=OrderSide.SELL,\n",
        "        limit_price=target_price,\n",
        "        time_in_force=TimeInForce.GTC\n",
        "    )\n",
        "\n",
        "    exit_order = trade_client.submit_order(exit_request)\n",
        "    print(\"Take-profit limit order successfully placed and waiting!\")"
      ]
    },
    {
      "cell_type": "code",
      "source": [
        "def get_all_option_positions(symbol):\n",
        "    # 1. Fetch ALL currently open positions in your account\n",
        "    all_positions = trade_client.get_all_positions()\n",
        "\n",
        "    # 2. Filter the list for QQQ options\n",
        "    # We check that the asset is an option, and the OCC symbol starts with \"QQQ\"\n",
        "    qqq_option_positions = [\n",
        "        position for position in all_positions\n",
        "        if position.asset_class == AssetClass.US_OPTION and position.symbol.startswith(\"QQQ\")\n",
        "    ]\n",
        "\n",
        "    # 3. Display the results\n",
        "\n",
        "    if qqq_option_positions:\n",
        "        print(f\"Found {len(qqq_option_positions)} active QQQ option position(s):\")\n",
        "\n",
        "        for pos in qqq_option_positions:\n",
        "            # Market value is returned as a string, so we convert to float for formatting\n",
        "            market_value = float(pos.market_value)\n",
        "            print(f\"Contract: {pos.symbol} | Qty: {pos.qty} | Side: {pos.side.name} | Value: ${market_value:.2f}\")\n",
        "    else:\n",
        "        print(\"No active QQQ option positions found in the account.\")\n",
        "\n",
        "    return qqq_option_positions"
      ],
      "metadata": {
        "id": "NgOkgm8nfOLK"
      },
      "execution_count": 7,
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "source": [
        "# QQQ LEAP execution"
      ],
      "metadata": {
        "id": "2Cl5uyVXnLFQ"
      }
    },
    {
      "cell_type": "code",
      "source": [
        "underlying_symbol = \"QQQ\"\n",
        "\n",
        "if (get_all_option_positions(underlying_symbol)):\n",
        "  display(\"Already in QQQ. Not entering new position\")\n",
        "else:\n",
        "  selected_contract = select_high_interest_call_leap(underlying_symbol)\n",
        "  place_order_with_exit_at_50pct_profit(selected_contract)\n"
      ],
      "metadata": {
        "colab": {
          "base_uri": "https://localhost:8080/",
          "height": 71
        },
        "id": "onXBiHK5eBB8",
        "outputId": "9c4964f5-44bf-4c61-bf9d-37b1e939fae6"
      },
      "execution_count": 8,
      "outputs": [
        {
          "output_type": "stream",
          "name": "stdout",
          "text": [
            "Found 1 active QQQ option position(s):\n",
            "Contract: QQQ270617C00680000 | Qty: 1 | Side: LONG | Value: $8300.00\n"
          ]
        },
        {
          "output_type": "display_data",
          "data": {
            "text/plain": [
              "'Already in QQQ. Not entering new position'"
            ],
            "application/vnd.google.colaboratory.intrinsic+json": {
              "type": "string"
            }
          },
          "metadata": {}
        }
      ]
    }
  ],
  "metadata": {
    "kernelspec": {
      "display_name": ".venv",
      "language": "python",
      "name": "python3"
    },
    "language_info": {
      "codemirror_mode": {
        "name": "ipython",
        "version": 3
      },
      "file_extension": ".py",
      "mimetype": "text/x-python",
      "name": "python",
      "nbconvert_exporter": "python",
      "pygments_lexer": "ipython3",
      "version": "3.12.2"
    },
    "colab": {
      "provenance": [],
      "collapsed_sections": [
        "S2ZkDIfhkcVH"
      ],
      "include_colab_link": true
    }
  },
  "nbformat": 4,
  "nbformat_minor": 0
}