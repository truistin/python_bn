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
            
    def calc_margin_equity_im_mm(self): #计算杠杆账户权益, im, mm
        margin_equity_im_mm = {}
        margin_equity_sum = Decimal(0)
        for symbol, val in self.marginPositions.items():
            equity_im_mm = {}
            leverage = self.margin_leverage[symbol] if symbol in self.margin_leverage.keys() else self.margin_leverage['default']
            #求净值
            equity_im_mm['equity'] = Decimal(val['crossMarginAsset']) - Decimal(val['crossMarginBorrowed'])
            equity_im_mm['im'] = Decimal(val['crossMarginBorrowed']) / Decimal(leverage - 1)    #初始保证金
            if symbol in ('USDT', 'USDC', 'BUSD'):
                equity_im_mm['mm'] = Decimal(0)
            else:
                index_price = self.get_last_price(symbol)
                equity_im_mm['mm'] = Decimal(val['crossMarginBorrowed']) * Decimal(self.margin_mmr[leverage])  * Decimal(index_price) #维持保证金
            margin_equity_im_mm[symbol] = equity_im_mm
            margin_equity_sum += equity_im_mm['equity']
        #print('margin_equity_sum', margin_equity_sum)
        return margin_equity_im_mm

    def calc_cswap_equity_im_mm(self): #计算币本位账户权益，im，mm
        cswap_equity_im_mm = {}
        cswap_equity_sum = Decimal(0)
        for symbol, val in self.cmPositions.items():
            equity_im_mm = {}
            leverage = Decimal(val['leverage'])
            markPrice = Decimal(val['markPrice'])
            symbol_base = symbol.replace('USD_PERP','')
            if symbol == 'BTCUSD_PERP':
                qty = Decimal(val['positionAmt']) * Decimal(100) / markPrice
            else:
                qty = Decimal(val['positionAmt']) * Decimal(10) / markPrice
            mmr, cum = self.get_cm_brackets(symbol, abs(qty))
            equity_im_mm['equity'] = Decimal(self.marginPositions[symbol_base]['cmWalletBalance']) + Decimal(self.marginPositions[symbol_base]['cmUnrealizedPNL'])
            equity_im_mm['im'] = abs(qty) * (Decimal(1)/leverage) / markPrice
            equity_im_mm['mm'] = (abs(qty) * mmr -cum) * markPrice
            cswap_equity_sum += equity_im_mm['equity']
            #print('aaaa', equity_im_mm['mm'])
            cswap_equity_im_mm[symbol] = equity_im_mm
        #print('cswap_equity_sum', cswap_equity_sum)
        return cswap_equity_im_mm
    
    def calc_uswap_equity_im_mm(self): #计算U本位账户权益，im，mm
        uswap_equity_im_mm = {}
        uswap_equity_sum = Decimal(0)
        for symbol, val in self.umPositions.items():
            equity_im_mm = {}
            symbol_base = symbol.replace('USDT', '')
            leverage = Decimal(val['leverage'])
            markPrice = Decimal(val['markPrice'])
            qty = Decimal(val['positionAmt'])
            mmr, cum = self.get_um_brackets(symbol, abs(qty) * markPrice)
            equity_im_mm['equity'] = Decimal(self.marginPositions[symbol_base]['umWalletBalance']) + Decimal(self.marginPositions[symbol_base]['umUnrealizedPNL'])
            equity_im_mm['im'] = abs(qty) * markPrice * (Decimal(1)/leverage) #初始保证金
            equity_im_mm['mm'] = abs(qty) * markPrice * mmr - cum#维持保证金
            #print('ssssssss', symbol, equity_im_mm['mm'], qty, markPrice, mmr, leverage)
            uswap_equity_im_mm[symbol] = equity_im_mm
            uswap_equity_sum += equity_im_mm['equity']
        #print('uswap_equity_sum', uswap_equity_sum)
        #print(self.marginPositions)
        return uswap_equity_im_mm
    
    def calc_uniMMR(self):
        uniAccount_equity = self.calc_equity()
        uniAccount_mm = self.calc_mm()
        print(uniAccount_equity, uniAccount_mm)
        return Decimal(uniAccount_equity)/Decimal(uniAccount_mm)
    
    def get_account(self):
        params = {}
        response = self.origin_api_clt._request_margin_api('get', 'account', True, data = params)
        return response

    def get_cm_account(self):
        params = {}
        response = self.origin_api_clt._request_margin_api('get', 'cm/account', True, data = params)
        return response

    def get_um_account(self):
        params = {}
        response = self.origin_api_clt._request_margin_api('get', 'um/account', True, data = params)
        return response

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

        for symbol, val in self.umPositions.items(): #u本位mm
            markPrice = Decimal(val['markPrice'])
            qty = Decimal(val['positionAmt'])
            mmr, cum = self.get_um_brackets(symbol, abs(qty) * markPrice)
            mm = abs(qty) * markPrice * mmr - cum#维持保证金
            sum_mm += mm

        for symbol, val in self.cmPositions.items(): #币本位mm
            markPrice = Decimal(val['markPrice'])
            if symbol == 'BTCUSD_PERP':
                qty = Decimal(val['positionAmt']) * Decimal(100) / markPrice
            else:
                qty = Decimal(val['positionAmt']) * Decimal(10) / markPrice
            mmr, cum = self.get_cm_brackets(symbol, abs(qty))
            mm = (abs(qty) * mmr -cum) * markPrice
            sum_mm += mm
        
        return sum_mm
            
    def calc_equity(self): #计算调整后净值 * 抵押率
        sum_equity = Decimal(0)
        for symbol, val in self.marginPositions.items():
            if Decimal(val['crossMarginAsset']) != 0 or Decimal(val['crossMarginBorrowed']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                equity = Decimal(val['crossMarginAsset']) - Decimal(val['crossMarginBorrowed'])
                price = Decimal(self.get_last_price(symbol))
                calc_equity = min(equity*price, equity*price*rate)
                sum_equity += calc_equity
                print('margin', val['asset'], '全仓资产:',val['crossMarginAsset'],'全仓杠杆借贷:',val['crossMarginBorrowed'], 'equity:', calc_equity)
            if Decimal(val['umWalletBalance']) != 0 or Decimal(val['umUnrealizedPNL']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                equity = Decimal(val['umWalletBalance']) +  Decimal(val['umUnrealizedPNL'])
                price = Decimal(1)
                calc_equity = equity * price
                sum_equity += calc_equity
                print('um', f"{val['asset']}USDT", 'U本位钱包余额:',val['umWalletBalance'],'U本位未实现盈亏:', val['umUnrealizedPNL'], 'equity:', calc_equity)
            if Decimal(val['cmWalletBalance']) != 0 or Decimal(val['cmUnrealizedPNL']) != 0:
                rate = Decimal(self.collateralRate[symbol]['collateralRate'])
                equity = Decimal(val['cmWalletBalance']) + Decimal(val['cmUnrealizedPNL'])
                price = Decimal(self.get_last_price(symbol))
                calc_equity = min(equity*price, equity*price*rate)
                sum_equity += calc_equity
                print('cm', f"{val['asset']}USD_PERP", '币本位钱包余额:',val['cmWalletBalance'],'币本位未实现盈亏:', val['cmUnrealizedPNL'], 'equity:', calc_equity)
        return sum_equity

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

if __name__ == '__main__':
    #apikey = 'qrNt0VO8sdAbeLS0bAMbtDyip67ZwVUFU6XGVtlQw1anjeiyLOwfNrcVdqIAMyMR'
    #secretkey = '8aEKZ23CEBAECqDUG7XD5hJuDAUtsUe1f8uNoh0NOAMKL12ySTDfbV5hjQzJcqrG'
    apikey = '7uky94bXR47G1ry1q7djuh6PVItKGdqKwXx4audvl5DzvR6XCMhJhCg1xECIJj7D'
    secretkey = 'T8mFrsqJylHa2spAw4FN6p0HYOCPdnsBnIhrAf5BuT628s3rjR6yjPEUYW34IFve'
    binanceMr = BinanceMR(apikey,secretkey)
    binanceMr.initialize()
    print(binanceMr.calc_uniMMR()) # 计算uniMMR
    print(binanceMr.get_uniMMR()) # 接口获取uniMMR
    print(binanceMr.calc_balance())
    
   