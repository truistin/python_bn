#!/usr/bin/env python

import time
import logging
from binance.lib.utils import config_logging
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

config_logging(logging, logging.DEBUG)


def message_handler(_, message):
    print(message)

def subscribeUM():
    my_client = UMFuturesWebsocketClient(on_message=message_handler)
    my_client.book_ticker(symbol="ethusdt")
    my_client.book_ticker(symbol="btcusdt")
    my_client.book_ticker(symbol="solusdt")

# time.sleep(10)

# logging.debug("closing ws connection")
# my_client.stop()
