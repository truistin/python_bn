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
        self.collateralRate = {}
        self.spotData = {}
        self.swapData = {}
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

    def get_um_brackets(self, symbol, leverage): ##获取U本位维持保证金率
        params = {'symbol':symbol}
        response = self.origin_api_clt.futures_leverage_bracket(**params)
        for item in response[0]['brackets']:
            if leverage == item['initialLeverage']:
                return item
        return None

    def get_cm_brackets(self, symbol, leverage): #获取币本位维持保证金率
        params = {'symbol':symbol}
        response = self.origin_api_clt.cmfu_leverage_bracket(**params)
        for item in response[0]['brackets']:
            if leverage == item['initialLeverage']:
                return item
        return None


    def get_uniMMR(self): ##获取uniMMR
        response = self.origin_api_clt.get_margin_account()
        margin_level_value = response["uniMMR"]
        #print(margin_level_value)
        return margin_level_value
    

    def get_price(self): ##获取价格
        response = requests.get("https://api.binance.com/api/v3/ticker/24hr")
        spotRet = response.json() if response.status_code == 200 else []
        response = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
        swapRet = response.json() if response.status_code == 200 else []
        self.spotData = {i["symbol"]: i for i in spotRet}
        self.swapData = {i["symbol"]: i for i in swapRet}

    def get_last_price(self, symbol): ##获取最新价格
        if 'USDT' not in symbol:
            symbol = f'{symbol}USDT'
            return float(self.spotData[f"{symbol.upper()}"]["lastPrice"]) if f"{symbol.upper()}" in self.spotData.keys() else np.nan
        else:
            return float(self.swapData[f"{symbol.upper()}"]["lastPrice"]) if f"{symbol.upper()}" in self.spotData.keys() else np.nan

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
        margin_mm_sum = Decimal(0)
        for symbol, val in self.marginPositions.items():
            equity_im_mm = {}
            leverage = self.margin_leverage[symbol] if symbol in self.margin_leverage.keys() else self.margin_leverage['default']
            #求净值
            equity_im_mm['equity'] = Decimal(val['crossMarginAsset']) - Decimal(val['crossMarginBorrowed'])
            equity_im_mm['im'] = Decimal(val['crossMarginBorrowed']) / Decimal(leverage - 1)    #初始保证金
            if symbol in ('USDT', 'USDC', 'BUSD'):
                equity_im_mm['mm'] = Decimal(0)
            else:
                equity_im_mm['mm'] = Decimal(val['crossMarginBorrowed']) * Decimal(self.margin_mmr[leverage])  * Decimal(self.get_priceIndex(f'{symbol}USDT')) #维持保证金
                margin_mm_sum += equity_im_mm['mm']
            margin_equity_im_mm[symbol] = equity_im_mm
        print('margin_mm_sum', margin_mm_sum)
        return margin_equity_im_mm

    def calc_cswap_equity_im_mm(self): #计算币本位账户权益，im，mm
        cswap_equity_im_mm = {}
        cswap_mm_sum = Decimal(0)
        for symbol, val in self.cmPositions.items():
            equity_im_mm = {}
            leverage = Decimal(val['leverage'])
            markPrice = Decimal(val['markPrice'])
            symbol_base = symbol.replace('USD_PERP','')
            if symbol == 'BTCUSD_PERP':
                qty = Decimal(val['positionAmt']) * Decimal(100)
            else:
                qty = Decimal(val['positionAmt']) * Decimal(10)
            item = self.get_cm_brackets(f'{symbol}', int(leverage))
            mmr = Decimal(item['maintMarginRatio'])
            equity_im_mm['equity'] = Decimal(self.marginPositions[symbol_base]['cmWalletBalance']) + Decimal(self.marginPositions[symbol_base]['cmUnrealizedPNL'])
            equity_im_mm['im'] = abs(qty) * (Decimal(1)/leverage) / markPrice
            equity_im_mm['mm'] = abs(qty) * mmr / Decimal(leverage)
            cswap_mm_sum += equity_im_mm['mm']
            #print('aaaa', equity_im_mm['mm'])
            cswap_equity_im_mm[symbol] = equity_im_mm
        print('cswap_mm_sum', cswap_mm_sum)
        return cswap_equity_im_mm
    
    def calc_uswap_equity_im_mm(self): #计算U本位账户权益，im，mm
        uswap_equity_im_mm = {}
        uswap_mm_sum = Decimal(0)
        for symbol, val in self.umPositions.items():
            equity_im_mm = {}
            symbol_base = symbol.replace('USDT', '')
            leverage = Decimal(val['leverage'])
            markPrice = Decimal(val['markPrice'])
            qty = Decimal(val['positionAmt'])
            item = self.get_um_brackets(symbol, int(leverage))
            mmr = Decimal(item['maintMarginRatio'])
            equity_im_mm['equity'] = Decimal(self.marginPositions[symbol_base]['umWalletBalance']) + Decimal(self.marginPositions[symbol_base]['umUnrealizedPNL'])
            equity_im_mm['im'] = abs(qty) * markPrice * (Decimal(1)/leverage) #初始保证金
            equity_im_mm['mm'] = abs(qty) * markPrice * mmr /Decimal(leverage)#维持保证金
            print('ssssssss', symbol, equity_im_mm['mm'], qty, markPrice, mmr, leverage)
            uswap_equity_im_mm[symbol] = equity_im_mm
            uswap_mm_sum += equity_im_mm['mm']
        print('uswap_mm_sum', uswap_mm_sum)
        #print(self.marginPositions)
        return uswap_equity_im_mm
    
    def calc_uniAccount_equity_im_mmr(self):
        trade_loss = self.trade_loss()
        margin_equity_im_mm = self.calc_margin_equity_im_mm()
        uswap_equity_im_mm = self.calc_uswap_equity_im_mm()
        cswap_equity_im_mm = self.calc_cswap_equity_im_mm()
        
        uniAccount_equity_sum = Decimal(0)
        uniAccount_im_sum = Decimal(0)
        uniAccount_mm_sum = Decimal(0)
        for symbol, val in margin_equity_im_mm.items():
            if symbol == 'USDT' or symbol == 'USDC' or symbol == 'BUSD':
                index_price = Decimal(1)
                uniAccount_equity_sum += val['equity'] * index_price
            else:
                index_price = Decimal(self.get_priceIndex(f'{symbol}USDT'))
                uniAccount_equity_sum += min(val['equity'] * index_price * Decimal(self.collateralRate[symbol]['collateralRate']), val['equity'] * index_price)
                uniAccount_mm_sum += Decimal(val['mm'])
            
        
        for symbol, val in uswap_equity_im_mm.items():
            index_price = Decimal(self.get_priceIndex(f'{symbol}'))
            uniAccount_equity_sum += val['equity'] * index_price
            uniAccount_mm_sum += Decimal(val['mm'])
        
        for symbol, val in cswap_equity_im_mm.items():
            symbol_base = symbol.replace('USD_PERP', '')
            index_price = Decimal(self.get_priceIndex(f'{symbol_base}USDT'))
            uniAccount_equity_sum += min(val['equity'] * index_price * Decimal(self.collateralRate[symbol_base]['collateralRate']),val['equity'] * index_price)
            uniAccount_mm_sum += Decimal(val['mm'])
        uniAccount_equity_sum += trade_loss
        print('uniAccount_equity_sum', uniAccount_equity_sum)
        print('uniAccount_mm_sum', uniAccount_mm_sum)


        '''
        uniAccount_equity_im_mm = {}
        
        
        
        um_im_sum = Decimal(0)
        um_mm_sum = Decimal(0)
        


        for symbol, val in uswap_equity_im_mm.items():
            um_im_sum += val['im']
            um_mm_sum += val['mm']
        for symbol, val in self.marginPositions.items():
            equity_im_mm = {}
            if symbol == 'USDT':
                equity_im_mm['index_price'] = Decimal(1)
                equity_im_mm['collateral_rate'] = Decimal(1)
                equity_im_mm['equity'] = Decimal(uswap_equity) + Decimal(margin_equity_im_mm[symbol]['equity'])
                equity_im_mm['trade_loss'] = Decimal(trade_loss)
                equity_im_mm['im'] = Decimal(margin_equity_im_mm[symbol]['im']) + um_im_sum
                equity_im_mm['mm'] = Decimal(margin_equity_im_mm[symbol]['mm']) + um_mm_sum
            else:
                equity_im_mm['index_price'] = Decimal(self.get_priceIndex(f'{symbol}USDT'))
                equity_im_mm['collateral_rate'] = Decimal(self.collateralRate[symbol]['collateralRate'])
                if f'{symbol}USD_PERP' in cswap_equity_im_mm.keys():
                    equity_im_mm['equity'] = Decimal(margin_equity_im_mm[symbol]['equity']) + Decimal(cswap_equity_im_mm[f'{symbol}USD_PERP']['equity'])
                    equity_im_mm['im'] = margin_equity_im_mm[symbol]['im'] + Decimal(cswap_equity_im_mm[f'{symbol}USD_PERP']['im'])
                    equity_im_mm['mm'] = margin_equity_im_mm[symbol]['mm'] + Decimal(cswap_equity_im_mm[f'{symbol}USD_PERP']['mm'])
                else:
                    equity_im_mm['equity'] = Decimal(margin_equity_im_mm[symbol]['equity'])
                    equity_im_mm['im'] = margin_equity_im_mm[symbol]['im']
                    equity_im_mm['mm'] = margin_equity_im_mm[symbol]['mm']
                equity_im_mm['trade_loss'] = Decimal(0)
            uniAccount_equity_im_mm[symbol] = equity_im_mm 
        return uniAccount_equity_im_mm
        '''
    
    def calc_uniMMR(self):
        uniAccount_equity_im_mm = self.calc_uniAccount_equity_im_mmr()
        uniAccount_equity = Decimal(0)
        uniAccount_mm = Decimal(0)
        for key, val in uniAccount_equity_im_mm.items():
            uniAccount_equity += val['equity'] * val['collateral_rate'] * val['index_price'] + val['trade_loss']
            uniAccount_mm += val['mm'] * val['index_price']
        print(uniAccount_equity, uniAccount_mm)
        return uniAccount_equity/uniAccount_mm
    
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

if __name__ == '__main__':
    #apikey = 'qrNt0VO8sdAbeLS0bAMbtDyip67ZwVUFU6XGVtlQw1anjeiyLOwfNrcVdqIAMyMR'
    #secretkey = '8aEKZ23CEBAECqDUG7XD5hJuDAUtsUe1f8uNoh0NOAMKL12ySTDfbV5hjQzJcqrG'
    apikey = '7uky94bXR47G1ry1q7djuh6PVItKGdqKwXx4audvl5DzvR6XCMhJhCg1xECIJj7D'
    secretkey = 'T8mFrsqJylHa2spAw4FN6p0HYOCPdnsBnIhrAf5BuT628s3rjR6yjPEUYW34IFve'
    binanceMr = BinanceMR(apikey,secretkey)
    binanceMr.initialize()
    binanceMr.calc_uniAccount_equity_im_mmr()
    #print('calc_uniMMR:',binanceMr.calc_uniMMR())
    #print('uniMMR:',binanceMr.get_uniMMR())
    
    print('111',binanceMr.get_account())
    #print(binanceMr.marginPositions['BTC'])
    
    resp = binanceMr.get_um_account()
    for item in resp['assets']:
        print(item['asset'], item['maintMargin'])
    for item in resp['positions']:
        print(item['symbol'], item['maintMargin'], item['positionAmt'], item['leverage'])
    print('1111111')
    resp = binanceMr.get_cm_account()
    for item in resp['assets']:
        print(item['asset'], item['maintMargin'])
    
    #print(binanceMr.marginPositions)
    