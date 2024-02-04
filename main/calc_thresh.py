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
from datetime import datetime 
import numpy as np 
import threading  

lock = threading.Lock()  
# 创建一个logger  
logger = logging.getLogger('my_logger')  
logger.setLevel(logging.INFO) 

err_logger = logging.getLogger('my_err_logger')  
err_logger.setLevel(logging.ERROR)  
  
# 创建一个文件处理器，并设置日志级别和格式化器  
file_handler = logging.FileHandler('thresh_calc.log')  
file_handler.setLevel(logging.INFO)  
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')  
file_handler.setFormatter(formatter)  

logger.addHandler(file_handler)
err_logger.addHandler(file_handler)  

len_np = 120

dict = {"BTC":1,"ETC":1,"ADA":1,"FIL":1,"AVAX":1,"BCH":1,"LINK":1,"OP":1,"SOL":1,"ETH":1,"BNB":1,"DOT":1,"MATIC":1,"DOGE":1,"LTC":1,"XRP":1}
class symbolInfo:
    def __init__(self, symbol, op_symbol, base_symbol):
        self.base_symbol = base_symbol
        self.symbol = symbol
        self.op_symbol = op_symbol
        self.avg_price = 0
        self.data = np.zeros(len_np)

        self.sum_price = 0
        self.num = 0
        self.last_time_stamp = 0
        self.last_index_np = 0
        self.index_np = 0

    def __hash__(self):  
        return hash((self.symbol, self.op_symbol))  
  
    def __eq__(self, other):  
        if isinstance(other, symbolInfo):  
            return self.symbol == other.symbol and self.op_symbol == other.op_symbol  
        return False  

    def calc(self, ask, bid, stamp1):
        stamp = int(stamp1)
        mid_price = (Decimal(ask) + Decimal(bid)) / Decimal(2)
        self.index_np = self.last_time_stamp % len_np

        if self.last_time_stamp != int(stamp / 1000):
            print("52 symbol : {}, index_np : {}, last_index_np : {}, last_time_stamp : {}, stamp : {}".format(self.symbol, self.index_np, self.last_index_np, self.last_time_stamp, stamp))

            self.last_time_stamp = int(stamp / 1000)

            self.sum_price = 0
            self.num = 0
            
            self.sum_price = self.sum_price + mid_price
            self.num = self.num + 1

            self.avg_price = self.sum_price / self.num

            if self.index_np == self.last_index_np:
                self.data[self.last_index_np] = self.avg_price

            if self.index_np > self.last_index_np:
                self.data[(self.last_index_np+1):(self.index_np+1)] = self.avg_price
                print("69 symbol : {}, index_np : {}, last_index_np : {}".format(self.symbol, self.index_np, self.last_index_np))

            if self.index_np < self.last_index_np:
                self.data[(self.last_index_np+1):len_np] = self.avg_price
                self.data[0:(self.index_np+1)] = self.avg_price

                print("75 symbol : {}, index_np : {}, last_index_np : {}".format(self.symbol, self.index_np, self.last_index_np))
                logger.info("common symbol : {}, op symbol : {}, index_np : {}, last_index_np : {}".format(self.symbol, self.op_symbol , self.index_np, self.last_index_np))
                with lock:
                    if dict[self.base_symbol] == 0:
                        self.last_index_np = self.index_np
                        dict[self.base_symbol] = 1
                        return
                    self.time_calc()
            
            self.last_index_np = self.index_np            

        else:
            self.sum_price = self.sum_price + mid_price
            self.num = self.num + 1

            self.avg_price = self.sum_price / self.num
            
            if self.index_np == self.last_index_np:
                self.data[self.last_index_np] = self.avg_price
                
            # if self.index_np > self.last_index_np:
            #     self.data[(self.last_index_np+1):(self.index_np+1)] = self.avg_price


    def time_calc(self):
        value = dic[self.symbol]
        utc_now = datetime.utcnow() 

        key_mean = np.mean(self.data)
        value_mean = np.mean(value.data)
        # value.data[(len_np + value.index_np - 1) % len_np]
        logger.info("self.data : {}, value.data : {}".format(self.data, value.data))
        value.data[value.data == 0] = value.data[value.index_np]

        mean_thresh = 0
        if "USDT" in self.symbol:
            mean_thresh = (key_mean - value_mean) / value_mean
        else:
            mean_thresh = (value_mean - key_mean) / key_mean

        data = np.zeros(0)
        
        if "USDT" in self.symbol:
            for i in range(len_np):
                new_data = np.array([self.data[i] - value.data[i]])
                data = np.concatenate((data, new_data))
        else:
            for i in range(len_np):
                new_data = np.array([value.data[i] - self.data[i]])
                data = np.concatenate((data, new_data))  

        std_thresh = np.std(data)

        logger.info("vaild symbol : {}, value symbol : {}, key mean : {}, value mean : {}, mean thresh : {}, std thresh : {}, value index data : {}, value lastindex data : {}, data size : {}, time : {}"
            .format(self.symbol, value.symbol , key_mean, value_mean, mean_thresh, std_thresh, value.data[value.last_index_np], value.data[value.index_np], np.size(data), utc_now))  
            
        if mean_thresh >= 0.0008 or mean_thresh <= -0.0008:
            logger.info("vaild symbol : {}, value symbol : {}, key mean : {}, value mean : {}, mean thresh : {}, std thresh : {}, value index data : {}, value lastindex data : {}, data size : {}, time : {}"
                .format(self.symbol, value.symbol , key_mean, value_mean, mean_thresh, std_thresh, value.data[value.last_index_np], value.data[value.index_np], np.size(data), utc_now))  
        
        self.data.fill(0)
        value.data.fill(0)
        dict[self.base_symbol] = 0

def message_handler(_, message):
    # print(message)
    obj = json.loads(message)
    for it in lst:
        if it.symbol == obj["s"]:
            it.calc(obj["a"], obj["b"], obj["T"])

def subscribeUM():
    my_client = UMFuturesWebsocketClient(on_message=message_handler)
    # my_client1 = UMFuturesWebsocketClient(on_message=message_handler)
    my_client.book_ticker(symbol="ethusdt")
    # my_client.book_ticker(symbol="btcusdt")
    # my_client.book_ticker(symbol="solusdt")

    # my_client.book_ticker(symbol="adausdt")
    # my_client.book_ticker(symbol="filusdt")
    # my_client.book_ticker(symbol="avaxusdt")
    # my_client.book_ticker(symbol="bchusdt")
    # my_client.book_ticker(symbol="linkusdt")

    # my_client1.book_ticker(symbol="opusdt")
    # my_client1.book_ticker(symbol="bnbusdt")
    # my_client1.book_ticker(symbol="dotusdt")
    # my_client1.book_ticker(symbol="maticusdt")
    # my_client1.book_ticker(symbol="dogeusdt")
    # my_client1.book_ticker(symbol="ltcusdt")
    # my_client1.book_ticker(symbol="xrpusdt")

def subscribeCM():
    my_client = CMFuturesWebsocketClient(on_message=message_handler)
    # my_client1 = CMFuturesWebsocketClient(on_message=message_handler)

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="ethusd_perp",
    )
"""
    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="btcusd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="solusd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="adausd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="filusd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="avaxusd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="bchusd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="linkusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="opusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="bnbusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="dotusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="maticusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="dogeusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="ltcusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="xrpusd_perp",
    )"""

if __name__ == "__main__":
    """

    etc,ada,fil,avax,bch,link,op,sol,eth,bnb,dot,matic,doge,ltc,xrp,btc
    """

    eth_perp_sy = symbolInfo("ETHUSD_PERP", "ETHUSDT", "ETH")
    btc_perp_sy = symbolInfo("BTCUSD_PERP", "BTCUSDT", "BTC")
    sol_perp_sy = symbolInfo("SOLUSD_PERP", "SOLUSDT", "SOL")

    ada_perp_sy = symbolInfo("ADAUSD_PERP", "ADAUSDT", "ADA")
    fil_perp_sy = symbolInfo("FILUSD_PERP", "FILUSDT", "FIL")
    avax_perp_sy = symbolInfo("AVAXUSD_PERP", "AVAXUSDT", "AVAX")
    bch_perp_sy = symbolInfo("BCHUSD_PERP", "BCHUSDT", "BCH")
    link_perp_sy = symbolInfo("LINKUSD_PERP", "LINKUSDT", "LINK")

    op_perp_sy = symbolInfo("OPUSD_PERP", "OPUSDT", "OP")
    bnb_perp_sy = symbolInfo("BNBUSD_PERP", "BNBUSDT", "BNB")
    dot_perp_sy = symbolInfo("DOTUSD_PERP", "DOTUSDT", "DOT")
    matic_perp_sy = symbolInfo("MATICUSD_PERP", "MATICUSDT", "MATIC")
    doge_perp_sy = symbolInfo("DOGEUSD_PERP", "DOGEUSDT", "DOGE")
    ltc_perp_sy = symbolInfo("LTCUSD_PERP", "LTCUSDT", "LTC")
    xrp_perp_sy = symbolInfo("XRPUSD_PERP", "XRPUSDT", "XRP")

    eth_swap_sy = symbolInfo("ETHUSDT", "ETHUSD_PERP", "ETH")
    btc_swap_sy = symbolInfo("BTCUSDT", "BTCUSD_PERP", "BTC")
    sol_swap_sy = symbolInfo("SOLUSDT", "SOLUSD_PERP", "SOL")

    ada_swap_sy = symbolInfo("ADAUSDT", "ADAUSD_PERP", "ADA")
    fil_swap_sy = symbolInfo("FILUSDT", "FILUSD_PERP", "FIL")
    avax_swap_sy = symbolInfo("AVAXUSDT", "AVAXUSD_PERP", "AVAX")
    bch_swap_sy = symbolInfo("BCHUSDT", "BCHUSD_PERP", "BCH")
    link_swap_sy = symbolInfo("LINKUSDT", "LINKUSD_PERP", "LINK")

    op_swap_sy = symbolInfo("OPUSDT", "OPUSD_PERP", "OP")
    bnb_swap_sy = symbolInfo("BNBUSDT", "BNBUSD_PERP", "BNB")
    dot_swap_sy = symbolInfo("DOTUSDT", "DOTUSD_PERP", "DOT")
    matic_swap_sy = symbolInfo("MATICUSDT", "MATICUSD_PERP", "MATIC")
    doge_swao_sy = symbolInfo("DOGEUSDT", "DOGEUSD_PERP", "DOGE")
    ltc_swap_sy = symbolInfo("LTCUSDT", "LTCUSD_PERP", "LTC")
    xrp_swap_sy = symbolInfo("XRPUSDT", "XRPUSD_PERP", "XRP")
    """
    dic = {eth_swap_sy:eth_perp_sy, btc_swap_sy:btc_perp_sy, sol_swap_sy:sol_perp_sy, ada_swap_sy:ada_perp_sy\
        , fil_swap_sy:fil_perp_sy, avax_swap_sy:avax_perp_sy, bch_swap_sy:bch_perp_sy, link_swap_sy:link_perp_sy\
            , op_swap_sy:op_perp_sy, bnb_swap_sy:bnb_perp_sy, dot_swap_sy:dot_perp_sy, matic_swap_sy:matic_perp_sy\
            , doge_swao_sy:doge_perp_sy, ltc_swap_sy:ltc_perp_sy, xrp_swap_sy:xrp_perp_sy}"""
    
    dic = {"ETHUSD_PERP":eth_swap_sy, "ETHUSDT":eth_perp_sy}

    lst = []
    lst.append(eth_perp_sy)
    # lst.append(btc_perp_sy)
    # lst.append(sol_perp_sy)

    # lst.append(ada_perp_sy)
    # lst.append(fil_perp_sy)
    # lst.append(avax_perp_sy)
    # lst.append(bch_perp_sy)
    # lst.append(link_perp_sy)

    # lst.append(op_perp_sy)
    # lst.append(bnb_perp_sy)
    # lst.append(dot_perp_sy)
    # lst.append(matic_perp_sy)
    # lst.append(doge_perp_sy)
    # lst.append(ltc_perp_sy)
    # lst.append(xrp_perp_sy)

    lst.append(eth_swap_sy)
    # lst.append(btc_swap_sy)
    # lst.append(sol_swap_sy)

    # lst.append(ada_swap_sy)
    # lst.append(fil_swap_sy)
    # lst.append(avax_swap_sy)
    # lst.append(bch_swap_sy)
    # lst.append(link_swap_sy)

    # lst.append(op_swap_sy)
    # lst.append(bnb_swap_sy)
    # lst.append(dot_swap_sy)
    # lst.append(matic_swap_sy)
    # lst.append(doge_swao_sy)
    # lst.append(ltc_swap_sy)
    # lst.append(xrp_swap_sy)
    # print(lst)

    subscribeUM()
    subscribeCM()

    # scheduler = BackgroundScheduler()
    # scheduler.add_job(time_calc, 'interval', seconds=len_np)
    # scheduler.start()

    while True:  
        time.sleep(1)
    