import time
import logging
from binance.lib.utils import config_logging
from binance.websocket.cm_futures.websocket_client import CMFuturesWebsocketClient
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from binance.um_futures import UMFutures
import json
import schedule  
import time  
from apscheduler.schedulers.background import BackgroundScheduler  


config_logging(logging, logging.DEBUG)

class symbolInfo:
    def __init__(self, symbol, op_symbol):
        self.symbol = symbol
        self.op_symbol = op_symbol
        self.sum_price = 0
        self.mid_price = 0
        self.time_stamp = 0 
        self.thresh = 0
        self.num = 0

    def calc(self, ask, bid, stamp):
        self.mid_price = (float(ask) + float(bid)) / float(2)
        self.sum_price = self.sum_price + self.mid_price
        self.num = self.num + 1
        self.time_stamp = int(stamp)


eth_perp_sy = symbolInfo("ETHUSD_PERP", "ETHUSDT")
btc_perp_sy = symbolInfo("BTCUSD_PERP", "BTCUSDT")
sol_perp_sy = symbolInfo("SOLUSD_PERP", "SOLUSDT")

eth_swap_sy = symbolInfo("ETHUSDT", "ETHUSD_PERP")
btc_swap_sy = symbolInfo("BTCUSDT", "BTCUSD_PERP")
sol_swap_sy = symbolInfo("SOLUSDT", "SOLUSD_PERP")

dic = {eth_swap_sy:eth_perp_sy, btc_swap_sy:btc_perp_sy, sol_swap_sy:sol_perp_sy}

lst = []
lst.append(eth_perp_sy)
lst.append(btc_perp_sy)
lst.append(sol_perp_sy)
lst.append(eth_swap_sy)
lst.append(btc_swap_sy)
lst.append(sol_swap_sy)

def message_handler(_, message):
    # print(message)
    obj = json.loads(message)
    for it in lst:
        if it.symbol == obj["s"]:
            it.calc(obj["a"], obj["b"], obj["T"])

def time_calc():
    for it in lst:
        it.thresh = it.sum_price / it.num
        logging.info("time calc symbol : {}, thresh : {}, timestamp : {}, mid_price : {}, sum_price : {}, num : {} "\
                    .format(it.symbol, it.thresh, it.time_stamp, it.mid_price, it.sum_price, it.num))
        it.num = 0
        it.sum_price = 0
    for key, value in dic.items():
        if 'PERP' in key.op_symbol:
            thresh = (key.thresh - value.thresh) / value.thresh
            logging.info("time calc key symbol : {}, value symbol : {}, key thresh : {}, value thresh : {}, thresh : {}"\
                .format(key.symbol, value.symbol , key.thresh, value.thresh, thresh))

        

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

    scheduler = BackgroundScheduler()
    scheduler.add_job(time_calc, 'interval', seconds=300)
    scheduler.start()

    while True:  
        time.sleep(1)
    