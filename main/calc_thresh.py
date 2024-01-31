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
from decimal import Decimal


config_logging(logging, logging.DEBUG)

class symbolInfo:
    def __init__(self, symbol, op_symbol):
        self.symbol = symbol
        self.op_symbol = op_symbol
        self.sum_price = 0
        self.mid_price = 0
        self.time_stamp = 0 
        self.avg_mid_price = 0
        self.num = 0

    def calc(self, ask, bid, stamp):
        self.mid_price = (Decimal(ask) + Decimal(bid)) / Decimal(2)
        self.sum_price = self.sum_price + self.mid_price
        self.num = self.num + 1
        self.time_stamp = int(stamp)

"""

etc,ada,fil,avax,bch,link,op,sol,eth,bnb,dot,matic,doge,ltc,xrp,btc
"""

eth_perp_sy = symbolInfo("ETHUSD_PERP", "ETHUSDT")
btc_perp_sy = symbolInfo("BTCUSD_PERP", "BTCUSDT")
sol_perp_sy = symbolInfo("SOLUSD_PERP", "SOLUSDT")

ada_perp_sy = symbolInfo("ADAUSD_PERP", "ADAUSDT")
fil_perp_sy = symbolInfo("FILUSD_PERP", "FILUSDT")
avax_perp_sy = symbolInfo("AVAXUSD_PERP", "AVAXUSDT")
bch_perp_sy = symbolInfo("BCHUSD_PERP", "BCHUSDT")
link_perp_sy = symbolInfo("LINKUSD_PERP", "LINKUSDT")

op_perp_sy = symbolInfo("OPUSD_PERP", "OPUSDT")
sol_perp_sy = symbolInfo("SOlUSD_PERP", "SOLUSDT")
bnb_perp_sy = symbolInfo("BNBUSD_PERP", "BNBUSDT")
dot_perp_sy = symbolInfo("DOTUSD_PERP", "DOTUSDT")
matic_perp_sy = symbolInfo("MATICUSD_PERP", "MATICUSDT")
doge_perp_sy = symbolInfo("DOGEUSD_PERP", "DOGEUSDT")
ltc_perp_sy = symbolInfo("LTCUSD_PERP", "LTCUSDT")
xrp_perp_sy = symbolInfo("XRPUSD_PERP", "XRPUSDT")

eth_swap_sy = symbolInfo("ETHUSDT", "ETHUSD_PERP")
btc_swap_sy = symbolInfo("BTCUSDT", "BTCUSD_PERP")
sol_swap_sy = symbolInfo("SOLUSDT", "SOLUSD_PERP")

ada_swap_sy = symbolInfo("ADAUSDT", "ADAUSD_PERP")
fil_swap_sy = symbolInfo("FILUSDT", "FILUSD_PERP")
avax_swap_sy = symbolInfo("AVAXUSDT", "AVAXUSD_PERP")
bch_swap_sy = symbolInfo("BCHUSDT", "BCHUSD_PERP")
link_swap_sy = symbolInfo("LINKUSDT", "LINKUSD_PERP")

op_swap_sy = symbolInfo("OPUSDT", "OPUSD_PERP")
sol_swap_sy = symbolInfo("SOlUSDT", "SOlUSD_PERP")
bnb_swap_sy = symbolInfo("BNBUSDT", "BNBUSD_PERP")
dot_swap_sy = symbolInfo("DOTUSDT", "DOTUSD_PERP")
matic_swap_sy = symbolInfo("MATICUSDT", "MATICUSD_PERP")
doge_swao_sy = symbolInfo("DOGEUSDT", "DOGEUSD_PERP")
ltc_swap_sy = symbolInfo("LTCUSDT", "LTCUSD_PERP")
xrp_swap_sy = symbolInfo("XRPUSDT", "XRPUSD_PERP")

dic = {eth_swap_sy:eth_perp_sy, btc_swap_sy:btc_perp_sy, sol_swap_sy:sol_perp_sy}

lst = []
lst.append(eth_perp_sy)
lst.append(btc_perp_sy)
lst.append(sol_perp_sy)

lst.append(ada_perp_sy)
lst.append(fil_perp_sy)
lst.append(avax_perp_sy)
lst.append(bch_perp_sy)
lst.append(link_perp_sy)

lst.append(op_perp_sy)
lst.append(sol_perp_sy)
lst.append(bnb_perp_sy)
lst.append(dot_perp_sy)
lst.append(matic_perp_sy)
lst.append(doge_perp_sy)
lst.append(ltc_perp_sy)
lst.append(xrp_perp_sy)

lst.append(eth_swap_sy)
lst.append(btc_swap_sy)
lst.append(sol_swap_sy)

lst.append(ada_swap_sy)
lst.append(fil_swap_sy)
lst.append(avax_swap_sy)
lst.append(bch_swap_sy)
lst.append(link_swap_sy)

lst.append(op_swap_sy)
lst.append(sol_swap_sy)
lst.append(bnb_swap_sy)
lst.append(dot_swap_sy)
lst.append(matic_swap_sy)
lst.append(doge_swao_sy)
lst.append(ltc_swap_sy)
lst.append(xrp_swap_sy)


def message_handler(_, message):
    # print(message)
    obj = json.loads(message)
    for it in lst:
        if it.symbol == obj["s"]:
            it.calc(obj["a"], obj["b"], obj["T"])

def time_calc():
    for it in lst:
        it.avg_mid_price = it.sum_price / it.num
        # logging.info("time calc symbol : {}, avg_mid_price : {}, timestamp : {}, mid_price : {}, sum_price : {}, num : {} "\
        #             .format(it.symbol, it.avg_mid_price, it.time_stamp, it.mid_price, it.sum_price, it.num))
        it.num = 0
        it.sum_price = 0
    for key, value in dic.items():
        if 'PERP' in key.op_symbol:
            thresh = (key.avg_mid_price - value.avg_mid_price) / value.avg_mid_price

            logging.info("time calc key symbol : {}, value symbol : {}, key avg_mid_price : {}, value avg_mid_price : {}, thresh : {}"\
                .format(key.symbol, value.symbol , key.avg_mid_price, value.avg_mid_price, thresh))
            if thresh >= 0.0006:
                logging.info("valid symbol : {}, value symbol : {}, key avg_mid_price : {}, value avg_mid_price : {}, thresh : {}"\
                    .format(key.symbol, value.symbol , key.avg_mid_price, value.avg_mid_price, thresh))

        

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
    