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

len_np = 600

dict = {"BTC":1,"ETC":1,"ADA":1,"FIL":1,"AVAX":1,"BCH":1,"LINK":1,"OP":1,"SOL":1,"ETH":1,"BNB":1,"DOT":1,"MATIC":1,"DOGE":1,"LTC":1,"XRP":1}
class symbolInfo:
    def __init__(self, symbol, op_symbol, base_symbol):
        self.base_symbol = base_symbol
        self.symbol = symbol
        self.op_symbol = op_symbol
        self.avg_price = 0
        self.mid_price = 0
        self.data = np.zeros(len_np)

        self.lock = threading.Lock()  

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
        with self.lock:
            stamp = int(stamp1)
            self.mid_price = (Decimal(ask) + Decimal(bid)) / Decimal(2)
            self.index_np = self.last_time_stamp % len_np

            if self.last_time_stamp != int(stamp / 1000):
                print("52 symbol : {}, index_np : {}, last_index_np : {}, last_time_stamp : {}, stamp : {}".format(self.symbol, self.index_np, self.last_index_np, self.last_time_stamp, stamp))

                self.last_time_stamp = int(stamp / 1000)

                self.sum_price = 0
                self.num = 0
                
                self.sum_price = self.sum_price + self.mid_price
                self.num = self.num + 1

                self.avg_price = self.sum_price / self.num

                if self.index_np == self.last_index_np:
                    self.data[self.last_index_np] = self.avg_price

                if self.index_np > self.last_index_np:
                    if self.index_np < len_np:
                        self.data[self.last_index_np:self.index_np] = self.avg_price
                    # logger.info("69 symbol : {}, index_np : {}, last_index_np : {}".format(self.symbol, self.index_np, self.last_index_np))

                if self.index_np < self.last_index_np:
                    self.data[self.last_index_np:len_np] = self.avg_price

                    # logger.info("75 symbol : {}, index_np : {}, last_index_np : {}, avg_price : {}".format(self.symbol, self.index_np, self.last_index_np, self.avg_price, ))
                    # logger.info("common symbol : {}, op symbol : {}, index_np : {}, last_index_np : {}".format(self.symbol, self.op_symbol , self.index_np, self.last_index_np))
                    # with lock:
                    #     if dict[self.base_symbol] == 0:
                    #         self.last_index_np = self.index_np
                    #         dict[self.base_symbol] = 1
                    #         return
                    self.time_calc()
                    return
                
                self.last_index_np = self.index_np            

            else:
                self.sum_price = self.sum_price + self.mid_price
                self.num = self.num + 1

                self.avg_price = self.sum_price / self.num
                
                if self.index_np == self.last_index_np:
                    self.data[self.last_index_np] = self.avg_price
                    
                # if self.index_np > self.last_index_np:
                #     self.data[(self.last_index_np+1):(self.index_np+1)] = self.avg_price


    def time_calc(self):
        value = dic[self.symbol]
        utc_now = datetime.utcnow() 

        value.data[value.last_index_np:len_np] = value.avg_price
        key_mean = np.mean(self.data)
        value_mean = np.mean(value.data)
        # value.data[(len_np + value.index_np - 1) % len_np]
        logger.info(f"self.symbol : {self.symbol}, self.index : {self.index_np}, self.lastindex : {self.last_index_np}, value.index : {value.index_np}, value.lastindex : {value.last_index_np}, self num : {self.num}, value num : {value.num}, sel mid_p : {self.mid_price}, value mid_p : {value.mid_price}, self.data : {self.data}, value.data : {value.data}")

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

        mean_thresh_value = np.mean(data) 
        len = np.size(data)
        spread_data = np.empty(len, dtype=float)
        for i in range(len):
            spread_data[i] = data[i] / mean_thresh_value
        spread_thresh = np.std(spread_data)


        """
        mean_thresh_value = np.mean(data) 
        std_thresh_value = np.std(data)

        len = np.size(data)
        spread_data = np.empty(len, dtype=float)
        
        for i in range(len):
            spread_data[i] = (data[i] - mean_thresh_value) / std_thresh_value

        spread_thresh = np.mean(spread_data)
        """

        logger.info("calc std mean : {}, data : {}, spread_data : {}, mean_thresh_value : {}, spread_thresh : {}, md_price : {}".format(self.symbol, data, spread_data, mean_thresh_value, spread_thresh, self.mid_price))
        
        logger.info(f"time_calc symbol : {self.symbol}, value symbol : {value.symbol}, key avg_price : {self.avg_price}, value avg_value : {value.avg_price} , key mean : {key_mean}, value mean : {value_mean}, mean_thresh : {mean_thresh}, mean_thresh_value : {mean_thresh_value}, std thresh : {spread_thresh}, value index data : {value.data[value.index_np]}, value lastindex data : {value.data[value.last_index_np]}, time : {utc_now}")
            
        if mean_thresh >= 0.0008 or mean_thresh <= -0.0008:
            logger.info(f"vaild symbol : {self.symbol}, value symbol : {value.symbol}, key avg_price : {self.avg_price}, value avg_value : {value.avg_price} , key mean : {key_mean}, value mean : {value_mean}, mean thresh : {mean_thresh}, std thresh : {spread_thresh}, value index data : {value.data[value.index_np]}, value lastindex data : {value.data[value.index_np]}, mean_thresh_value : {mean_thresh_value}, time : {utc_now}")
        
        # self.data.fill(self.avg_price)
        # value.data.fill(value.avg_price)
        self.last_index_np = 0
        self.index_np = 0
        value.last_index_np = 0
        value.index_np = 0

def message_handler(_, message):
    # print(message)
    obj = json.loads(message)
    for it in lst:
        if it.symbol == obj["s"]:
            it.calc(obj["a"], obj["b"], obj["T"])

def subscribeUM():
    my_client = UMFuturesWebsocketClient(on_message=message_handler)
    my_client1 = UMFuturesWebsocketClient(on_message=message_handler)
    my_client.book_ticker(symbol="ethusdt")
    my_client.book_ticker(symbol="btcusdt")
    my_client.book_ticker(symbol="solusdt")

    my_client.book_ticker(symbol="adausdt")
    my_client.book_ticker(symbol="filusdt")
    my_client.book_ticker(symbol="avaxusdt")
    my_client.book_ticker(symbol="bchusdt")
    my_client.book_ticker(symbol="linkusdt")

    my_client1.book_ticker(symbol="opusdt")
    my_client1.book_ticker(symbol="bnbusdt")
    my_client1.book_ticker(symbol="dotusdt")
    my_client1.book_ticker(symbol="maticusdt")
    my_client1.book_ticker(symbol="dogeusdt")
    my_client1.book_ticker(symbol="ltcusdt")
    my_client1.book_ticker(symbol="xrpusdt")

def subscribeCM():
    my_client = CMFuturesWebsocketClient(on_message=message_handler)
    my_client1 = CMFuturesWebsocketClient(on_message=message_handler)

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="ethusd_perp",
    )

    my_client.book_ticker(
        id=13,
        callback=message_handler,
        symbol="btcusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="bnbusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="dogeusd_perp",
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
    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="maticusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="ltcusd_perp",
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
        symbol="dotusd_perp",
    )

    my_client1.book_ticker(
        id=13,
        callback=message_handler,
        symbol="xrpusd_perp",
    )

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
    doge_swap_sy = symbolInfo("DOGEUSDT", "DOGEUSD_PERP", "DOGE")
    ltc_swap_sy = symbolInfo("LTCUSDT", "LTCUSD_PERP", "LTC")
    xrp_swap_sy = symbolInfo("XRPUSDT", "XRPUSD_PERP", "XRP")
    """
    dic = {eth_swap_sy:eth_perp_sy, btc_swap_sy:btc_perp_sy, sol_swap_sy:sol_perp_sy, ada_swap_sy:ada_perp_sy\
        , fil_swap_sy:fil_perp_sy, avax_swap_sy:avax_perp_sy, bch_swap_sy:bch_perp_sy, link_swap_sy:link_perp_sy\
            , op_swap_sy:op_perp_sy, bnb_swap_sy:bnb_perp_sy, dot_swap_sy:dot_perp_sy, matic_swap_sy:matic_perp_sy\
            , doge_swap_sy:doge_perp_sy, ltc_swap_sy:ltc_perp_sy, xrp_swap_sy:xrp_perp_sy}"""
    
    dic = {"ETHUSD_PERP":eth_swap_sy, "ETHUSDT":eth_perp_sy, "BTCUSD_PERP":btc_swap_sy, "BTCUSDT":btc_perp_sy,
            "BNBUSD_PERP":bnb_swap_sy, "BNBUSDT":bnb_perp_sy, "DOGEUSD_PERP":doge_swap_sy, "DOGEUSDT":doge_perp_sy,
            "SOLUSD_PERP":sol_swap_sy, "SOLUSDT": sol_perp_sy, "ADAUSD_PERP":ada_swap_sy, "ADAUSDT":ada_perp_sy,
            "MATICUSD_PERP":matic_swap_sy, "MATICUSDT": matic_perp_sy, "LTCUSD_PERP":ltc_swap_sy, "LTCUSDT":ltc_perp_sy,
            "FILUSD_PERP":fil_swap_sy, "FILUSDT": fil_perp_sy, "AVAXUSD_PERP":avax_swap_sy, "AVAXUSDT":avax_perp_sy,
            "BCHUSD_PERP":bch_swap_sy, "BCHUSDT": bch_perp_sy, "LINKUSD_PERP":link_swap_sy, "LINKUSDT":link_perp_sy,
            "OPUSD_PERP":op_swap_sy, "OPUSDT": op_perp_sy, "DOTUSD_PERP":dot_swap_sy, "DOTUSDT":dot_perp_sy,
            "XRPUSD_PERP":xrp_swap_sy, "XRPUSDT": xrp_perp_sy}
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
    lst.append(bnb_swap_sy)
    lst.append(dot_swap_sy)
    lst.append(matic_swap_sy)
    lst.append(doge_swap_sy)
    lst.append(ltc_swap_sy)
    lst.append(xrp_swap_sy)
    # print(lst)

    subscribeUM()
    subscribeCM()

    # scheduler = BackgroundScheduler()
    # scheduler.add_job(time_calc, 'interval', seconds=len_np)
    # scheduler.start()

    while True:  
        time.sleep(1)
    