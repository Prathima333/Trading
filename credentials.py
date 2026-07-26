# -*- coding: utf-8 -*-
"""
Credentials helper for Alpaca API authentication.
"""

import os


def get_alpaca_credentials():
    """
    Fetches Alpaca API key and secret key from Google Colab userdata or OS environment variables.
    """
    api_key = ''
    secret_key = ''

    try:
        from google.colab import userdata  # type: ignore
        IN_COLAB = True
    except ImportError:
        IN_COLAB = False

    if IN_COLAB:
        print("Running in Colab: Fetching from userdata...")
        api_key = userdata.get('ALPACA_API_KEY')
        secret_key = userdata.get('ALPACA_SECRET_KEY')
    else:
        print("Running outside Colab: Fetching from OS environment...")
        try:
            from dotenv import load_dotenv  # type: ignore
            load_dotenv()
        except ImportError:
            pass

        api_key = os.environ.get('ALPACA_API_KEY')
        secret_key = os.environ.get('ALPACA_SECRET_KEY')

        if not api_key or not secret_key:
            print("Warning: ALPACA_API_KEY or ALPACA_SECRET_KEY is not set in environment variables.")

    return api_key, secret_key
