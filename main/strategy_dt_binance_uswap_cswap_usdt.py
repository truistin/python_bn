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

def logs_init_std(file_name):
    file_name = file_name.replace(':', '_')
    base_path = 'logs'
    log_file_name = os.path.join(base_path, file_name) + '.log'
    log_dir_name = os.path.dirname(log_file_name)

    if not os.path.exists(log_dir_name):
        os.makedirs(log_dir_name)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    log_formatter = logging.Formatter(
        '%(asctime)s@%(filename)s/%(funcName)s %(message)s')
    file_handler = TimedRotatingFileHandler(log_file_name,
                                            when="midnight",
                                            backupCount=3)
    file_handler.setFormatter(log_formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

def time_iso_utc_to_milli(iso):
    try:
        time_milli = int(pytz.utc.localize(datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%f")).timestamp() * 1000)
    except ValueError:
        try:
            time_milli = int(pytz.utc.localize(datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ")).timestamp() * 1000)
        except ValueError:
            try:
                time_milli = int(pytz.utc.localize(datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")).timestamp() * 1000)
            except ValueError:
                time_milli = int(pytz.utc.localize(datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S")).timestamp() * 1000)
    return time_milli


def time_milli_to_iso_utc(milli):
    return datetime.datetime.utcfromtimestamp(int(milli / 1000)).isoformat() + 'Z'


class DtBinanceUSwapBinanceCSwapUSDT():
    def __init__(self,apikey,apisecret):
        self.principal = 'USDT'
        self.logger = logging.getLogger('strategy-dt-binance-uswap-cswap')
        self.origin_api_clt = PortfolioClient(api_key=apikey,api_secret=apisecret)
        self.exchange_info = self.origin_api_clt.get_exchange_info()
        self.pair_info = {}
        for ex_pair_info in self.exchange_info['symbols']:
            for filter_item in ex_pair_info['filters']:
                if ex_pair_info['quoteAsset'] != 'USDT':
                    continue
                if 'LOT_SIZE' in filter_item.values(): #获取最小下单单位
                    self.pair_info[ex_pair_info['symbol']] = filter_item['minQty']

    async def calculate_hedge_deltas(self) -> List[Dict[str, Decimal]]:
        """
        binance 完全依赖新版统一账户特性
        """
        hedge_deltas = []
        assets = self.origin_api_clt.get_margin_asset()
        for asset in assets:
            if asset["asset"].upper() == self.principal:
                continue

            cash_bal = (
                Decimal(asset["totalWalletBalance"])
                - Decimal(asset["crossMarginBorrowed"])
                - Decimal(asset["crossMarginInterest"])
            )
            if abs(cash_bal) == 0:
                continue
            if asset["asset"].lower() == "usdt":  # usdt放在最后对冲
                hedge_deltas.insert(0, {asset["asset"].lower(): Decimal(cash_bal)})
            else:
                hedge_deltas.append({asset["asset"].lower(): cash_bal})

        self.logger.info(f"b_portfolio:{hedge_deltas}")
        hedge_deltas.reverse()
        return hedge_deltas

    async def hedge_once(self):
        # 结算期间不进行对冲
        utc_now = datetime.datetime.utcnow().timestamp() * 1000
        utc_now_str = time_milli_to_iso_utc(utc_now)
        settle_time_str1 = utc_now_str[0:10] + "T00:00:00Z"
        settle_time_str2 = utc_now_str[0:10] + "T08:00:00Z"
        settle_time_str3 = utc_now_str[0:10] + "T16:00:00Z"
        settle_time1 = time_iso_utc_to_milli(settle_time_str1)
        settle_time2 = time_iso_utc_to_milli(settle_time_str2)
        settle_time3 = time_iso_utc_to_milli(settle_time_str3)
        print(settle_time_str1, settle_time1, settle_time2, settle_time3)
        if (
            abs(utc_now - settle_time1) < 2 * 60 * 1000
            or abs(utc_now - settle_time2) < 2 * 60 * 1000
            or abs(utc_now - settle_time3) < 2 * 60 * 1000
        ):
            logging.warning("[clear-rpnl] it's settlement time now")
            return
        
        hedge_deltas = await self.calculate_hedge_deltas()
        for hedge_delta in hedge_deltas:
            for symbol, delta in hedge_delta.items():
                try:
                    self.logger.info(
                        f"[binance-portfolio] symbol({symbol}), delta: {delta}"
                    )
                    if Decimal(self.pair_info[f'{symbol.upper()}USDT']) > abs(delta):
                        continue
                    data={}
                    data['symbol'] = f'{symbol.upper()}USDT'
                    response = self.origin_api_clt.get_avg_price(**data)
                    price = response['price']
                    if Decimal(price) * abs(delta) < 10:
                        self.logger.info(f'[binance-portfolio] symbol({symbol}), usdt-delta:{Decimal(price) * abs(delta)}')
                        continue
                    request_params = {}
                    step_size_base = Decimal(self.pair_info[f'{symbol.upper()}USDT'])
                    clientId = str(int(time.time() * 1000))
                    request_params['newClientOrderId'] = clientId
                    request_params['symbol'] = f'{symbol.upper()}USDT'
                    request_params['sideEffectType'] = 'MARGIN_BUY'
                    request_params['quantity'] = int(abs(delta) / step_size_base) * step_size_base
                    request_params['type'] = 'MARKET'
                    request_params['newOrderRespType'] = 'RESULT'
                    request_params['side'] = 'SELL' if delta > 0 else 'BUY'
                    self.logger.info(f'request_params:{request_params}')
                    resp = self.origin_api_clt._request_margin_api('post', 'margin/order', signed=True, data=request_params)
                    self.logger.info(f'resp({clientId}): {resp}')
                except Exception as e:
                    import traceback

                    logging.info(traceback.format_exc())
                    
                    

    async def period_pnl_hedge(self):
        await asyncio.sleep(60)
        while True:
            self.logger.info("...check pnl hedge...")
            try:
                await self.hedge_once()
            except Exception as e:
                import traceback

                logging.exception(traceback.format_exc())
            await asyncio.sleep(20)

    async def run(self):
        asyncio.get_event_loop().create_task(
            self.period_auto_collection(), name="auto-collection"
        )
        asyncio.get_event_loop().create_task(self.period_repay(), name="repay")
        asyncio.get_event_loop().create_task(self.period_pnl_hedge(), name="pnl-hedge")

    async def period_auto_collection(self):
        """
        将合约账户的资产划转至杠杆账户
        """
        await asyncio.sleep(60)
        while True:
            await asyncio.sleep(15)
            try:
                resp = self.origin_api_clt.auto_collection()
                self.logger.info(f"[auto-collection], resp:{resp}")

            except Exception as e:
                import traceback
                self.logger.info(traceback.format_exc())

    async def period_repay(self):
        """
        清偿杠杆账户中的负债
        """
        while True:
            try:
                await asyncio.sleep(5 * 60)
                assets = self.origin_api_clt.get_margin_asset()
                for asset in assets:
                    print(asset)
                    symbol = asset["asset"]
                    margin_asset = Decimal(asset["crossMarginAsset"])
                    margin_borrowed = Decimal(asset["crossMarginBorrowed"])
                    margin_interest = Decimal(asset["crossMarginInterest"])
                    debit = margin_borrowed + margin_interest
                    if margin_asset > 0 and debit > 0:
                        repay_amout = min(margin_asset, debit)
                        params = {
                            "asset": asset["asset"].upper(),
                            "amount": str(repay_amout).rstrip("0"),
                        }
                        self.logger.info(f"{symbol} repay loan:{params}")
                        resp = self.origin_api_clt.repay_margin_loan(**params)
                        self.logger.info(f"repay resp:{resp}")
            except Exception as e:
                import traceback
                self.logger.info(traceback.format_exc())


if __name__ == '__main__':
    logs_init_std('strategy_dt_binance_uswap_cswap')
    strategy_inst = DtBinanceUSwapBinanceCSwapUSDT(apikey='3IepehoMkZWXPq7vnZmpPHVitb3YXrw35SCuIHjui1AFAuqJeF879Sw8hzbLDRXx', apisecret='ssFbZD2aiBnN6INEGtreutHGdvNZIMxbj1SpyFvk2VdolwijcWZ9C5bpyfNuw1iX')
    asyncio.get_event_loop().run_until_complete(strategy_inst.run())
    asyncio.get_event_loop().run_forever()


    

