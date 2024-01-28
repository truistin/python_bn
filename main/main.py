import time
import logging
from binance.lib.utils import config_logging
from binance.websocket.cm_futures.websocket_client import CMFuturesWebsocketClient
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from binance.um_futures import UMFutures

config_logging(logging, logging.DEBUG)

def message_handler(_, message):
    print(message)

def subscribeUM():
    my_client = UMFuturesWebsocketClient(on_message=message_handler)
    my_client.book_ticker(symbol="ethusdt")
    my_client.book_ticker(symbol="btcusdt")
    my_client.book_ticker(symbol="solusdt")

def subscribeCM():
    my_client = CMFuturesWebsocketClient(on_message=message_handler)

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="btcusd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="ethusd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="solusd_perp",
    )

if __name__ == "__main__":
    subscribeUM()
    subscribeCM()