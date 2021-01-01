# encoding: UTF-8
# website: www.binance.com
# author email: szy@tsinghua.org.cn

import platform
import os
import sys
import time
import traceback
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy.trade_engine_base import *
from strategy.sunquant_frame import *

from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException, BinanceRequestException, BinanceWithdrawException


class TradeEngineBinance(TradeEngineBase):

    def __init__(self, marketname):
        super(TradeEngineBinance, self).__init__(marketname)

        # variables which start with uppercase letter may have configuration in setting.json
        self.ApiKey = ''
        self.SeceretKey = ''
        self.LotSize = 0.001
        self.PriceSpread = 0.01
        self.VolumePrecision = 6
        self.PricePrecision = 2
        self.RecvWindow = 30000

        self.load_setting()

        self.client_api = None

        SQLog.info("__init__,marketname=", marketname, "self.__dict__=", self.__dict__)

    def open_api(self):
        SQLog.info("open_api,quote already open=", self.is_open())
        self.client_api = Client(self.ApiKey, self.SeceretKey)

        for stockcode in self.get_stockcode_pools():
            cc_coin = stockcode.split('.')
            instrument_id = cc_coin[1].upper() + 'USDT'
            result = self.client_api.get_open_orders(symbol=instrument_id, recvWindow=self.RecvWindow)
            for op in result:
                self.order_handler('CC.' + cc_coin[1].upper() + '.' + str(op.get('orderId')),
                                   'CC.' + cc_coin[1].upper(), False, SIDE_BUY == op.get('side').upper(),
                                   None, float(op.get('executedQty')), float(op.get('origQty')), float(op.get('price')))
        return True

    def close_api(self):
        super().close_api()
        self.client_api = None
        SQLog.info("close_api")
        return True

    def is_open(self):
        return not self.client_api is None

    def call_get_account(self):
        result = self.client_api.get_account(recvWindow=self.RecvWindow)
        with self.account_lock:
            self.nowstocks_dict.clear()
            self.nowasserts_total = 0
            if 'balances' in result:
                for coin in result['balances']:
                    if 'USDT' == coin.get('asset').upper():
                        self.nowbalance = float(coin.get('free')) + float(coin.get('locked'))
                        self.nowpower = float(coin.get('free'))
                        self.nowasserts_total += self.nowbalance
                    elif float(coin.get('free'))+float(coin.get('locked')) > self.LotSize:
                        self.nowstocks_dict['CC.'+coin.get('asset').upper()] = {'qty': float(coin.get('free'))+float(coin.get('locked'))}
                        self.nowasserts_total += self.quotes_dict.get(
                            'CC.'+coin.get('asset').upper(), {}).get('last_price', 0) * (float(coin.get('free'))+float(coin.get('locked')))
        SQLog.info("call_get_account,nowbalance=", self.nowbalance, "nowpower=", self.nowpower,
                   "nowasserts_total=", self.nowasserts_total, "nowstocks_dict=", self.nowstocks_dict)
        return [True, self.nowbalance, self.nowstocks_dict]

    def call_get_market_snapshot(self, stockcodes):
        self.nowasserts_total = self.nowbalance
        for code in stockcodes:
            if code not in self.get_stockcode_pools() and not code == self.get_default_stock():
                continue
            
            cc_coin = code.split('.')
            ticker = self.client_api.get_ticker(symbol=cc_coin[1].upper()+'USDT')
            if code not in self.quotes_dict:
                self.quotes_dict[code] = {}
            q = self.quotes_dict[code]
            q['lot_size'] = self.LotSize
            q['price_spread'] = self.PriceSpread
            q['suspension'] = False
            q['last_price'] = float(ticker['lastPrice'])
            q['ask_price'] = float(ticker['askPrice'])
            q['bid_price'] = float(ticker['bidPrice'])
            if code in self.nowstocks_dict:
                self.nowasserts_total += q['last_price'] * float(self.nowstocks_dict.get(code, {}).get('qty', 0))
        SQLog.info("call_get_market_snapshot,nowasserts_total=", self.nowasserts_total, "quotes_dict=", self.quotes_dict)
        return [True, self.quotes_dict]

    def call_get_average_volatility(self, stockcode):
        cc_coin = stockcode.split('.')
        result = self.client_api.get_klines(symbol=cc_coin[1].upper()+'USDT',
                                            interval=Client.KLINE_INTERVAL_1DAY,
                                            limit=50)
        #period = 7
        period = 3
        if len(result) >= max(period, 6):
            sumcloses = 0.0
            for j in range(-1, -1-period, -1):
                sumcloses += float(result[j][4])
            average = round(sumcloses / period, self.precision(stockcode))

            sumv = 0.0
            for i in range(-1, -6, -1):
                sumv += abs(float(result[i][2]) / float(result[i][3]) - 1) if float(result[i][3]) > 0 else 0
                sumv += abs(float(result[i][4]) / float(result[i-1][4]) - 1) if float(result[i-1][4]) > 0 else 0
            volatility = round(sumv / 10, 6)
            SQLog.info("call_get_average_volatility,stockcode=", stockcode, "average=", average, "volatility=", volatility)
            return [average, volatility]
        else:
            SQLog.warn("call_get_average_volatility,result too small,stockcode=", stockcode, "result=", result)
            raise Exception("call_get_average_volatility failed,stockcode=" + stockcode)

    def call_place_order(self, stockcode, volume, price, isbuy, ismarketorder):
        volume_v, price_v = self.round_order_param(stockcode, volume, price, isbuy, ismarketorder)
        if volume_v <= 0:
            SQLog.info("call_place_order failed,volume_v<=0,stockcode=", stockcode,
                       "volume=", volume, "volume_v=", volume_v, "price=", price, "price_v=", price_v,
                       "isbuy=", isbuy, "ismarketorder=", ismarketorder)
            return None
        if 0 == price_v and not ismarketorder:
            SQLog.info("call_place_order failed,price==0,stockcode=", stockcode, "volume=", volume, "price=", price,
                       "isbuy=", isbuy, "ismarketorder=", ismarketorder)
            return None

        cc_coin = stockcode.split('.')
        instrument_id = cc_coin[1].upper() + 'USDT'

        if isbuy:
            result = self.client_api.order_limit_buy(symbol=instrument_id, quantity=round(volume_v, self.VolumePrecision),
                                                     price=str(round(price_v, self.PricePrecision)), recvWindow=self.RecvWindow)
        else:
            result = self.client_api.order_limit_sell(symbol=instrument_id, quantity=round(volume_v, self.VolumePrecision),
                                                      price=str(round(price_v,self.PricePrecision)), recvWindow=self.RecvWindow)
        if result.get('status') in [ORDER_STATUS_NEW, ORDER_STATUS_PARTIALLY_FILLED, ORDER_STATUS_FILLED]:
            ret_oid = stockcode + '.' + str(result.get('orderId'))
            if isbuy:
                self.nowpower -= (volume_v * price_v * self.MaxFees)
            self.order_handler(ret_oid, stockcode, None, isbuy, None, None, volume_v, price_v)
            SQLog.info("call_place_order,stockcode=", stockcode,
                       "volume=", volume, "volume_v=", volume_v, "price=", price, "price_v=", price_v,
                       "isbuy=", isbuy, "ismarketorder=", ismarketorder, "orderid=", ret_oid)
            SQLog.info("--------------------PlaceOrderOK--------------------", stockcode, "--------------------",
                       'BUY' if isbuy else 'SELL', volume_v, '@ ', price_v, "--------------------", ret_oid)
            return stockcode + '.' + str(result.get('orderId'))
        else:
            raise Exception("call_place_order failed,timeout,stockcode=" + stockcode + ",volume=" + str(volume)
                            + ",price=" + str(price) + ",isbuy=" + str(isbuy) + ",ismarketorder=" + str(ismarketorder))

    def call_get_order(self, orderid):
        if orderid is None:
            SQLog.info("call_get_order,orderid=", orderid, "order=None")
            return None
        cco = orderid.split('.')
        coin = cco[1]
        oid = cco[2]
        try:
            result = self.client_api.get_order(symbol=coin.upper()+'USDT', orderId=int(oid), recvWindow=self.RecvWindow)
            self.order_handler(orderid, 'CC.'+coin.upper(),
                               result.get('status') in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED, ORDER_STATUS_REJECTED, ORDER_STATUS_EXPIRED],
                               None, None, float(result.get('executedQty')), None, None)
        except Exception as e:
            SQLog.warn("call_get_order,failed,orderid=", orderid, "Exception,e=", e)
        order = self.get_order_from_cache(orderid)
        SQLog.info("call_get_order,orderid=", orderid, "order=", order)
        return order

    def call_list_order(self):
        orders_notclose = {}
        with self.orders_dict_lock:
            for orderid, order in self.orders_dict.items():
                if not order.get('isclose'):
                    orders_notclose[orderid] = order.copy()

        SQLog.info("call_list_order,result=", orders_notclose)
        for oid, o in orders_notclose.items():
            self.call_get_order(oid)
        return True

    def call_cancel_order(self, orderid):
        if orderid is None:
            SQLog.info("call_cancel_order,orderid=", orderid, "return False")
            return False
        cco = orderid.split('.')
        coin = cco[1]
        oid = cco[2]
        try:
            result = self.client_api.cancel_order(symbol=coin.upper()+'USDT', orderId=int(oid), recvWindow=self.RecvWindow)
            SQLog.info("call_cancel_order,orderid=", orderid, ",result=", result)
            return True
        except Exception as e:
            SQLog.info("call_cancel_order,orderid=", orderid, ",result=False,e=", e)
            return False

    def call_cancel_all_orders(self):
        orders_notclose = {}
        with self.orders_dict_lock:
            for orderid, order in self.orders_dict.items():
                if not order.get('isclose'):
                    orders_notclose[orderid] = order.copy()
        for oid, o in orders_notclose.items():
            self.call_cancel_order(oid)
        SQLog.info("call_cancel_all_orders")
        return True


if __name__ == '__main__':
    args = SunquantFrame.getargs('binance-sun', 'shannon')

    SQLog.setup_root_logger(args.market, args.strategy+'-debug', 'info', 'debug', 0, 1)
    SQLog.init_default(args.market, args.strategy, 'info', 'info', 1, 1)

    engine = TradeEngineBinance(args.market)
    frame = SunquantFrame(engine, args.market, args.strategy)
    engine.set_frame(frame)
    if SunquantFrame.doargs(args, engine):
        exit(0)

    SQLog.init_default(args.market, args.strategy, 'info', 'info', 1 if platform.system() == "Windows" else 0, 1)
    frame.monitor_run()
    exit(0)
