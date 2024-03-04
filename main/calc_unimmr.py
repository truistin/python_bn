from binance.client_pm import PortfolioClient
import asyncio
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from decimal import Decimal
import datetime
import time
import pytz
from typing import *
from binance_f.impl.restapiinvoker import call_sync
from binance_f.requestclient import RequestClient
import requests
import numpy as np

class BinanceMR(object):
    def __init__(self,apikey,apisecret):
        self.origin_api_clt = PortfolioClient(api_key=apikey,api_secret=apisecret)
        self.request_clt = RequestClient(api_key=apikey,secret_key=apisecret, url='https://api.binance.com')
        self.collateralRate = {} #抵押品率
        self.spotData = {}
        self.uswapData = {}
        self.cswapData = {}
        self.marginPositions = {}
        self.umPositions = {}
        self.cmPositions = {}
        self.margin_leverage = {'BTC':10, 'ETH':10,'ETC':10,'default':5}
        self.margin_mmr = {3:0.1, 5:0.08, 10:0.05}
        self.uswap_leverage = {'BTC':10, 'ETH':10}

    def initialize(self):
        self.get_collateral_rate()
        self.get_price()
        self.fetch_margin_position()
        self.fetch_um_position()
        self.fetch_cm_position()

    def fetch_margin_position(self): ##获取现货持仓
        assets = self.origin_api_clt.get_margin_asset()
        for asset in assets:
            symbol = asset['asset']
            self.marginPositions[symbol] = asset
        return self.marginPositions
    
    def fetch_um_position(self): ##获取U本位合约持仓
        ex_positions = self.origin_api_clt.futures_position_information()
        for ex_position in ex_positions:
            symbol = ex_position['symbol']
            self.umPositions[symbol] = ex_position
        return self.umPositions

    def fetch_cm_position(self): ##获取币本位合约持仓
        ex_positions = self.origin_api_clt.futures_coin_position_information()
        for ex_position in ex_positions:
            symbol = ex_position['symbol']
            self.cmPositions[symbol] = ex_position

    def get_priceIndex(self, symbol): ##获取指数价格
        response = self.request_clt.get_priceIndex(symbol)
        #print(response.get_string("price"))
        return response.get_string("price")

    def get_crossMarginCollateralRatio(self): ##获取质押率
        response = self.request_clt.get_crossMarginCollateralRatio()

    def get_collateral_rate(self): ##获取抵押品率
        response = requests.get('https://www.binancezh.info/bapi/margin/v1/public/margin/portfolio/collateral-rate')
        resp = response.json()
        datas = resp['data']
        for data in datas:
            symbol = data['asset']
            self.collateralRate[symbol] = data

    def get_um_brackets(self, symbol, usdtVal): ##获取U本位维持保证金率
        params = {'symbol':symbol}
        response = self.origin_api_clt.futures_leverage_bracket(**params)
        for item in response[0]['brackets']:
            notionalFloor = item['notionalFloor'] #持仓USDT最小值
            notionalCap = item['notionalCap']   # 持仓USDT最大值
            maintMarginRatio = item['maintMarginRatio'] #维持保证金率
            cum = item ['cum'] #维持保证金速算额
            if usdtVal >= notionalFloor and usdtVal <= notionalCap:
                return Decimal(maintMarginRatio), Decimal(cum)
        return None, None

    def get_cm_brackets(self, symbol, symbolVal): #获取币本位维持保证金率
        params = {'symbol':symbol}
        response = self.origin_api_clt.cmfu_leverage_bracket(**params)
        for item in response[0]['brackets']:
            qtyFloor = item['qtyFloor'] #持仓币数量最小值
            qtyCap = item['qtyCap']     #持仓币数量最大值
            maintMarginRatio = item['maintMarginRatio'] #维持保证金比率
            cum = item['cum'] #维持保证金速算额
            if symbolVal >= qtyFloor and symbolVal <= qtyCap:
                return Decimal(maintMarginRatio), Decimal(cum)
        return None, None


    def get_uniMMR(self): ##获取uniMMR
        response = self.origin_api_clt.get_margin_account()
        print('get_equity:', response['accountEquity'], 'get_mm:', response['accountMaintMargin'])
        margin_level_value = response["uniMMR"]
        #print(margin_level_value)
        return margin_level_value
    

    def get_price(self): ##获取价格
        response = requests.get("https://api.binance.com/api/v3/ticker/24hr")
        spotRet = response.json() if response.status_code == 200 else []
        response = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
        uswapRet = response.json() if response.status_code == 200 else []
        response = requests.get("https://dapi.binance.com/dapi/v1/ticker/24hr")
        cswapRet = response.json() if response.status_code == 200 else []
        self.spotData = {i["symbol"]: i for i in spotRet}
        self.uswapData = {i["symbol"]: i for i in uswapRet}
        self.cswapData = {i["symbol"]: i for i in cswapRet}

    def get_last_price(self, symbol): ##获取最新价格
        if symbol == 'USDT':
            return 1
        elif 'USD_PERP' in symbol:
            return float(self.cswapData[f"{symbol.upper()}"]["lastPrice"]) if f"{symbol.upper()}" in self.cswapData.keys() else np.nan
        elif 'USDT' in symbol:
            return float(self.uswapData[f"{symbol.upper()}"]["lastPrice"]) if f"{symbol.upper()}" in self.uswapData.keys() else np.nan
        else:
            symbol = f'{symbol}USDT'
            return float(self.spotData[f"{symbol.upper()}"]["lastPrice"]) if f"{symbol.upper()}" in self.spotData.keys() else np.nan
    
    def trade_loss(self): ##开仓亏损
        loss_sum = 0
        for symbol, val in self.marginPositions.items():
            if symbol in ('USDT', 'USDC', 'BUSD'):
                continue
            price = self.get_last_price(symbol)
            rate = self.collateralRate[symbol]['collateralRate']
            qty = val['crossMarginAsset']
            #print(symbol, price, qty, rate)
            side = 1 if Decimal(qty) < 0 else -1
            loss_sum += abs(Decimal(qty)) * Decimal(price) * min(0,side * (1 - Decimal(rate)))
        #print(loss_sum)
        return loss_sum
    
    def calc_uniMMR(self):
        uniAccount_equity = self.calc_equity()
        uniAccount_mm = self.calc_mm()
        print('equity:',uniAccount_equity, 'mm:',uniAccount_mm)
        return Decimal(uniAccount_equity)/Decimal(uniAccount_mm)

    def calc_mm(self): #维持保证金
        sum_mm = Decimal(0)
        for symbol, val in self.marginPositions.items(): #杠杆现货mm
            leverage = self.margin_leverage[symbol] if symbol in self.margin_leverage.keys() else self.margin_leverage['default']
            if symbol in ('USDT', 'USDC', 'BUSD'):
                mm = Decimal(val['crossMarginBorrowed']) * Decimal(self.margin_mmr[10])  * Decimal(1) #维持保证金
                sum_mm += mm
                #mm = Decimal(0)
            else:
                price = self.get_last_price(symbol)
                mm = Decimal(val['crossMarginBorrowed']) * Decimal(self.margin_mmr[leverage])  * Decimal(price) #维持保证金
                sum_mm += mm
            #if Decimal(val['crossMarginBorrowed']) != 0:
            #    print(symbol,val['crossMarginBorrowed'], mm)

        for symbol, val in self.umPositions.items(): #u本位mm
            markPrice = Decimal(val['markPrice'])
            qty = Decimal(val['positionAmt'])
            mmr, cum = self.get_um_brackets(symbol, abs(qty) * markPrice)
            mm = abs(qty) * markPrice * mmr - cum#维持保证金
            if symbol == 'ETHBTC':
                mm = mm * Decimal(self.get_last_price('BTC'))
            #print(f'{symbol}-USDT-SWAP', 'calc_mm:', mm, 'get_mm:')
            sum_mm += mm

        for symbol, val in self.cmPositions.items(): #币本位mm
            markPrice = Decimal(val['markPrice'])
            if symbol == 'BTCUSD_PERP':
                qty = Decimal(val['positionAmt']) * Decimal(100) / markPrice
            else:
                qty = Decimal(val['positionAmt']) * Decimal(10) / markPrice
            mmr, cum = self.get_cm_brackets(symbol, abs(qty))
            mm = (abs(qty) * mmr -cum) * markPrice
            #print(symbol, 'calc_mm:', mm, 'get_mm:')
            sum_mm += mm
        
        return sum_mm
            
    def calc_equity(self): #计算调整后净值 * 抵押率
        sum_equity = Decimal(0)
        for symbol, val in self.marginPositions.items(): #通过balance获取数据
            if Decimal(val['crossMarginAsset']) != 0 or Decimal(val['crossMarginBorrowed']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                #equity = Decimal(val['crossMarginAsset']) - Decimal(val['crossMarginBorrowed'])
                equity = Decimal(val['crossMarginFree']) + Decimal(val['crossMarginLocked']) - Decimal(val['crossMarginBorrowed']) - Decimal(val['crossMarginInterest'])
                price = Decimal(self.get_last_price(symbol))
                calc_equity = min(equity*price, equity*price*rate)
                sum_equity += calc_equity
                #print('margin', val['asset'], '全仓资产:',val['crossMarginAsset'],'全仓杠杆借贷:',val['crossMarginBorrowed'], 'equity:', calc_equity)
             
            if Decimal(val['umWalletBalance']) != 0 or Decimal(val['umUnrealizedPNL']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                equity = Decimal(val['umWalletBalance']) +  Decimal(val['umUnrealizedPNL'])
                price = Decimal(self.get_last_price(symbol))
                calc_equity = equity * price
                sum_equity += calc_equity
                #print('um', f"{val['asset']}USDT", 'U本位钱包余额:',val['umWalletBalance'],'U本位未实现盈亏:', val['umUnrealizedPNL'], 'equity:', calc_equity)
            
            if Decimal(val['cmWalletBalance']) != 0 or Decimal(val['cmUnrealizedPNL']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                equity = Decimal(val['cmWalletBalance']) + Decimal(val['cmUnrealizedPNL'])
                price = Decimal(self.get_last_price(symbol))
                calc_equity = min(equity*price, equity*price*rate)
                sum_equity += calc_equity
                #print('cm', f"{val['asset']}USD_PERP", '币本位钱包余额:',val['cmWalletBalance'],'币本位未实现盈亏:', val['cmUnrealizedPNL'], 'equity:', calc_equity)
            
        return sum_equity
    
    def get_usdt_equity(self): #获取USDT净值
        val = self.marginPositions['USDT']
        equity = Decimal(val['crossMarginFree']) + Decimal(val['crossMarginLocked']) - Decimal(val['crossMarginBorrowed']) - Decimal(val['crossMarginInterest'])
        equity += Decimal(val['umWalletBalance']) +  Decimal(val['umUnrealizedPNL'])
        equity += Decimal(val['cmWalletBalance']) + Decimal(val['cmUnrealizedPNL'])
        return equity

    def calc_predict_equity(self, order_config, pricePercent): #计算调整后净值 * 抵押率
        sum_equity = Decimal(0)
        for key ,val in order_config.items():
            qty = val['qty']
            price = self.get_last_price(key)
            rate = Decimal(self.collateralRate[key]['collateralRate'])
            if qty > 0: ##现货做多， 合约做空
                equity = Decimal(qty) * Decimal(price) * Decimal(1 + pricePercent) * rate
                borrow = val['borrow']
                uswap_unpnl = Decimal(qty) * Decimal(price) - Decimal(qty) * Decimal(price) * Decimal(1 + pricePercent)
                sum_equity += equity - borrow + uswap_unpnl
            else:
                qty = abs(qty) ##现货做空， 合约做多
                borrow = val['borrow']
                equity = Decimal(qty) * Decimal(price) - Decimal(borrow) * Decimal(1 + pricePercent) * Decimal(price)
                uswap_unpnl = Decimal(qty) * Decimal(price) * Decimal(1 + pricePercent) - Decimal(qty) * Decimal(price)
                sum_equity += equity + uswap_unpnl

        for symbol, val in self.marginPositions.items(): #通过balance获取数据
            if Decimal(val['crossMarginAsset']) != 0 or Decimal(val['crossMarginBorrowed']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                equity = Decimal(val['crossMarginFree']) + Decimal(val['crossMarginLocked']) - Decimal(val['crossMarginBorrowed']) - Decimal(val['crossMarginInterest'])
                if symbol not in ('USDT', 'USDC', 'BUSD'):
                    price = Decimal(self.get_last_price(symbol)) * Decimal(1 + pricePercent)
                else:
                    price = Decimal(self.get_last_price(symbol))
                calc_equity = min(equity*price, equity*price*rate)
                sum_equity += calc_equity
                #print('margin', val['asset'], '全仓资产:',val['crossMarginAsset'],'全仓杠杆借贷:',val['crossMarginBorrowed'], 'equity:', calc_equity)
             
            if Decimal(val['umWalletBalance']) != 0 or Decimal(val['umUnrealizedPNL']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                #equity = Decimal(val['umWalletBalance']) +  Decimal(val['umUnrealizedPNL'])
                equity = Decimal(val['umWalletBalance'])
                if symbol not in ('USDT', 'USDC', 'BUSD'):
                    price = Decimal(self.get_last_price(symbol)) * Decimal(1 + pricePercent)
                else:
                    price = Decimal(self.get_last_price(symbol))
                calc_equity = equity * price
                sum_equity += calc_equity
                #print('um', f"{val['asset']}USDT", 'U本位钱包余额:',val['umWalletBalance'],'U本位未实现盈亏:', val['umUnrealizedPNL'], 'equity:', calc_equity)
            
            if Decimal(val['cmWalletBalance']) != 0 or Decimal(val['cmUnrealizedPNL']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                #equity = Decimal(val['cmWalletBalance']) + Decimal(val['cmUnrealizedPNL'])
                equity = Decimal(val['cmWalletBalance'])
                if symbol not in ('USDT', 'USDC', 'BUSD'):
                    price = Decimal(self.get_last_price(symbol)) * Decimal(1 + pricePercent)
                else:
                    price = Decimal(self.get_last_price(symbol))
                calc_equity = min(equity*price, equity*price*rate)
                sum_equity += calc_equity
                #print('cm', f"{val['asset']}USD_PERP", '币本位钱包余额:',val['cmWalletBalance'],'币本位未实现盈亏:', val['cmUnrealizedPNL'], 'equity:', calc_equity)
        for symbol, val in self.umPositions.items():
            price = Decimal(self.get_last_price(symbol))  * Decimal(1 + pricePercent)
            avgPrice = val['entryPrice']
            qty = val['positionAmt']
            uswap_unpnl = (Decimal(price) - Decimal(avgPrice)) * Decimal(qty)
            sum_equity += uswap_unpnl
        for symbol, val in self.cmPositions.items():
            price = Decimal(self.get_last_price(symbol)) * Decimal(1 + pricePercent)
            avgPrice = val['entryPrice']
            qty = val['positionAmt']
            contract_size = Decimal(0)
            if symbol == 'BTCUSD_PERP':
                contract_size = Decimal(100)
            else:
                contract_size = Decimal(10)
            cswap_unpnl = (1/Decimal(avgPrice) - 1/Decimal(price)) * Decimal(qty) * contract_size * Decimal(price)
            sum_equity += cswap_unpnl
        return sum_equity

    def calc_predict_mm(self, order_config, pricePercent): #维持保证金
        sum_mm = Decimal(0)
        for key, val in order_config.items():
            price = self.get_last_price(key)
            qty = val['qty']
            if qty > 0:  ##现货做多， 合约做空
                borrow = val['borrow']
                sum_mm += Decimal(borrow) * Decimal(self.margin_mmr[10])
            else:  ##现货做空， 合约做多
                qty = abs(qty)
                borrow = val['borrow']
                leverage = self.margin_leverage[key]
                rate = self.margin_mmr[leverage]
                sum_mm += Decimal(borrow) * Decimal(price) * Decimal(rate)

        for symbol, val in self.marginPositions.items(): #杠杆现货mm
            leverage = self.margin_leverage[symbol] if symbol in self.margin_leverage.keys() else self.margin_leverage['default']
            if symbol in ('USDT', 'USDC', 'BUSD'):
                mm = Decimal(val['crossMarginBorrowed']) * Decimal(self.margin_mmr[10])  * Decimal(1) #维持保证金
                sum_mm += mm
                #mm = Decimal(0)
            else:
                price = self.get_last_price(symbol)
                mm = Decimal(val['crossMarginBorrowed']) * Decimal(self.margin_mmr[leverage])  * Decimal(price) #维持保证金
                sum_mm += mm

        for symbol, val in self.umPositions.items(): #u本位mm
            markPrice = Decimal(val['markPrice']) * Decimal(1 + pricePercent)
            qty = Decimal(val['positionAmt'])
            if symbol in order_config.keys():
                qty += order_config[symbol]['qty']
            mmr, cum = self.get_um_brackets(symbol, abs(qty) * markPrice)
            mm = abs(qty) * markPrice * mmr - cum#维持保证金
            if symbol == 'ETHBTC':
                mm = mm * Decimal(self.get_last_price('BTC')) * Decimal(1 + pricePercent)
            #print(f'{symbol}-USDT-SWAP', 'calc_mm:', mm, 'get_mm:')
            sum_mm += mm

        for symbol, val in self.cmPositions.items(): #币本位mm
            markPrice = Decimal(val['markPrice']) * Decimal(1 + pricePercent)
            if symbol == 'BTCUSD_PERP':
                qty = Decimal(val['positionAmt']) * Decimal(100) / Decimal(markPrice)
            else:
                qty = Decimal(val['positionAmt']) * Decimal(10) / Decimal(markPrice)
            mmr, cum = self.get_cm_brackets(symbol, abs(qty))
            mm = (abs(qty) * mmr -cum) * markPrice
            #print(symbol, 'calc_mm:', mm, 'get_mm:')
            sum_mm += mm
        
        return sum_mm
     
    def calc_balance(self): #计算资产
        #获取um_account
        sum_usdt = 0
        um_balances = []
        info = self.origin_api_clt.futures_account()
        for asset_ex in info['assets']:
            um_balance = {}
            um_balance['symbol'] = asset_ex['asset']
            um_balance['available'] = Decimal(asset_ex['crossWalletBalance'])
            um_balance['unpnl'] = Decimal(asset_ex['crossUnPnl'])
            um_balances.append(um_balance)
            #if Decimal(asset_ex['maintMargin']) != 0:
            #    print(f'{asset_ex["asset"]}-USDT-SWAP', asset_ex['maintMargin'])
            if asset_ex['asset'] in ('USDT', 'USDC', 'BUSD'):
                sum_usdt += (um_balance['available'] + um_balance['unpnl']) * Decimal(1)
            else:
                sum_usdt += (um_balance['available'] + um_balance['unpnl']) * Decimal(self.get_last_price(asset_ex['asset']))
        #获取cm_account
        cm_balances = []
        info = self.origin_api_clt.futures_coin_account()
        for asset_ex in info['assets']:
            cm_balance = {}
            cm_balance['symbol'] = asset_ex['asset']
            cm_balance['available'] = Decimal(asset_ex['crossWalletBalance'])
            cm_balance['unpnl'] = Decimal(asset_ex['crossUnPnl'])
            #if Decimal(asset_ex['maintMargin']) != 0:
            #    print(f'{asset_ex["asset"]}-USD-SWAP', asset_ex['maintMargin'])
            cm_balances.append(cm_balance)
            sum_usdt += (cm_balance['available'] + cm_balance['unpnl']) * Decimal(self.get_last_price(asset_ex['asset']))
        #获取margin_account
        margin_balances = []
        info = self.origin_api_clt.get_margin_asset()
        for asset_ex in info:
            margin_balance = {}
            margin_balance['symbol'] = asset_ex['asset']
            margin_balance['available'] = Decimal(asset_ex['crossMarginFree'])
            margin_balance['freeze'] = Decimal(asset_ex['crossMarginLocked'])
            margin_balance['debt'] = Decimal(asset_ex['crossMarginBorrowed'])
            margin_balance['interest'] = Decimal(asset_ex['crossMarginInterest'])
            margin_balances.append(margin_balance)
            if asset_ex['asset'] in ('USDT', 'USDC', 'BUSD'):
                sum_usdt += (margin_balance['available'] + margin_balance['freeze'] - margin_balance['debt'] - margin_balance['interest']) * Decimal(1)
            else:
                sum_usdt += (margin_balance['available'] + margin_balance['freeze'] - margin_balance['debt'] - margin_balance['interest']) * Decimal(self.get_last_price(asset_ex['asset']))
        return sum_usdt

    def calc_future_uniMMR(self, order_config, pricePercent):
        #order_config 下单的币种 和数量
        usdt_equity = self.get_usdt_equity()
        sum_equity = self.calc_equity()
        print(usdt_equity)
        IM = Decimal(0)
        for key, val in order_config.items():
            price = Decimal(self.get_last_price(key))
            qty = val['qty']
            if qty > 0: #借usdt
                borrow = Decimal(qty) * price #借贷
                order_config[key]['borrow'] = borrow # borrow 是美金价值
                IM += borrow/(10-1) + Decimal(qty) * price / self.uswap_leverage[key]
            else: #借现货
                borrow = -qty
                order_config[key]['borrow'] = Decimal(borrow) # borrow 是现货币数
                IM += Decimal(abs(qty)) / (self.margin_leverage[key] - 1) * price + Decimal(abs(qty)) * price / self.uswap_leverage[key]
        if IM > sum_equity:
            print('现货+合约的初始保证金 > 有效保证金，不可以下单')
            return 0
        predict_equity = self.calc_predict_equity(order_config,pricePercent)
        predict_mm = self.calc_predict_mm(order_config,pricePercent)
        predict_mmr = predict_equity / predict_mm
        print('predict_equity:', predict_equity, 'predict_mm', predict_mm)
        return predict_mmr

if __name__ == '__main__':
    #apikey = 'qrNt0VO8sdAbeLS0bAMbtDyip67ZwVUFU6XGVtlQw1anjeiyLOwfNrcVdqIAMyMR'
    #secretkey = '8aEKZ23CEBAECqDUG7XD5hJuDAUtsUe1f8uNoh0NOAMKL12ySTDfbV5hjQzJcqrG'
    apikey = '7uky94bXR47G1ry1q7djuh6PVItKGdqKwXx4audvl5DzvR6XCMhJhCg1xECIJj7D'
    secretkey = 'T8mFrsqJylHa2spAw4FN6p0HYOCPdnsBnIhrAf5BuT628s3rjR6yjPEUYW34IFve'
    binanceMr = BinanceMR(apikey,secretkey)
    binanceMr.initialize()
    print('calc_uniMMR:',binanceMr.calc_uniMMR()) # 计算uniMMR
    print('get_uniMMR:',binanceMr.get_uniMMR()) # 接口获取uniMMR
    print('calc_balance:',binanceMr.calc_balance())

    order_config = {'BTC':{'qty':0.1}, 'ETH':{'qty': -0.1}} #目前一次只传一个参数
    order_config = {'ETH':{'qty': -0.1}}
    #order_config = {}
    print('aaa:',binanceMr.calc_future_uniMMR(order_config, 0))
    
   