# encoding: UTF-8
# website: www.okex.me
# author email: szy@tsinghua.org.cn

import platform
import os
import sys
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy.trade_engine_base import *
from strategy.sunquant_frame import *

import okex.spot_api as spot

class TradeEngineOKEx(TradeEngineBase):

    def __init__(self, marketname):
        super(TradeEngineOKEx, self).__init__(marketname)

        # variables which start with uppercase letter may have configuration in setting.json
        self.ApiKey = ''
        self.SeceretKey = ''
        self.PassPhrase = ''
        self.LotSize = 0.001
        self.PriceSpread = 0.1
        self.VolumePrecision = 8
        self.PricePrecision = 1

        self.load_setting()

        self.spot_api = None
        self.orderid_counter = int(round(time.time() * 1000))

        SQLog.info("__init__,marketname=", marketname, "self.__dict__=", self.__dict__)

    def open_api(self):
        SQLog.info("open_api,quote already open=", self.is_open())
        self.spot_api = spot.SpotAPI(self.ApiKey, self.SeceretKey, self.PassPhrase, True)

        for stockcode in self.get_stockcode_pools():
            cc_coin = stockcode.split('.')
            instrument_id = cc_coin[1].upper() + '-USDT'
            result = self.spot_api.get_orders_pending(froms='', to='', limit='100', instrument_id=instrument_id)
            for op in result[0]:
                self.order_handler('CC.' + cc_coin[1].upper() + '.' + op.get('order_id'),
                                   'CC.' + cc_coin[1].upper(), False, 'buy' == op.get('side').lower(),
                                   float(op.get('price_avg')) if op.get('price_avg') else None,
                                   float(op.get('filled_size')), float(op.get('size')), float(op.get('price')))
        return True

    def close_api(self):
        super().close_api()
        self.spot_api = None
        SQLog.info("close_api")
        return True

    def is_open(self):
        return not self.spot_api is None

    def call_get_account(self):
        result = self.spot_api.get_account_info()
        with self.account_lock:
            self.nowstocks_dict.clear()
            self.nowasserts_total = 0
            for coin in result:
                if 'USDT' == coin.get('currency').upper():
                    self.nowbalance = float(coin.get('balance'))
                    self.nowpower = float(coin.get('available'))
                    self.nowasserts_total += self.nowbalance
                elif float(coin.get('balance')) > self.LotSize:
                    self.nowstocks_dict['CC.'+coin.get('currency').upper()] = {'qty': float(coin.get('balance'))}
                    self.nowasserts_total += self.quotes_dict.get(
                        'CC.'+coin.get('currency').upper(), {}).get('last_price', 0) * float(coin.get('balance'))
        SQLog.info("call_get_account,nowbalance=", self.nowbalance, "nowpower=", self.nowpower,
                   "nowasserts_total=", self.nowasserts_total, "nowstocks_dict=", self.nowstocks_dict)
        return [True, self.nowbalance, self.nowstocks_dict]

    def call_get_market_snapshot(self, stockcodes):
        self.nowasserts_total = self.nowbalance
        for code in stockcodes:
            if code not in self.get_stockcode_pools() and not code == self.get_default_stock():
                continue

            cc_coin = code.split('.')
            ticker = self.spot_api.get_specific_ticker(instrument_id=cc_coin[1].upper()+'-USDT')
            if code not in self.quotes_dict:
                self.quotes_dict[code] = {}
            q = self.quotes_dict[code]
            q['lot_size'] = self.LotSize
            q['price_spread'] = self.PriceSpread
            q['suspension'] = False
            q['last_price'] = float(ticker['last'])
            q['ask_price'] = float(ticker['best_ask'])
            q['bid_price'] = float(ticker['best_bid'])
            q['ask_vol'] = float(ticker['best_ask_size'])
            q['bid_vol'] = float(ticker['best_bid_size'])
            if code in self.nowstocks_dict:
                self.nowasserts_total += q['last_price'] * float(self.nowstocks_dict.get(code, {}).get('qty', 0))
        SQLog.info("call_get_market_snapshot,nowasserts_total=", self.nowasserts_total, "quotes_dict=", self.quotes_dict)
        return [True, self.quotes_dict]

    def call_get_average_volatility(self, stockcode):
        cc_coin = stockcode.split('.')
        result = self.spot_api.get_kline(instrument_id=cc_coin[1].upper()+'-USDT', start=None, end=None, granularity=86400)

        period = 30
        if len(result) >= max(period, 6):
            sumcloses = 0.0
            for j in range(period):
                sumcloses += float(result[j][4])
            average = round(sumcloses / period, self.precision(stockcode))

            sumv = 0.0
            for i in range(5):
                sumv += abs(float(result[i][2]) / float(result[i][3]) - 1) if float(result[i][3]) > 0 else 0
                sumv += abs(float(result[i][4]) / float(result[i+1][4]) - 1) if float(result[i+1][4]) > 0 else 0
            volatility = round(sumv / 10, 6)
            SQLog.info("call_get_average_volatility,stockcode=", stockcode, "average=", average, "volatility=", volatility)
            return [average, volatility]
        else:
            SQLog.warn("call_get_average_volatility,result too small,stockcode=", stockcode, "result=", result)
            return [0, 0]

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
        instrument_id = cc_coin[1].upper() + '-USDT'
        self.orderid_counter += 1
        oid = 'COID' + str(self.orderid_counter)

        result = self.spot_api.take_order(otype='limit', side='buy' if isbuy else 'sell', instrument_id=instrument_id,
                                          size=round(volume_v,self.VolumePrecision), margin_trading=1, client_oid=oid,
                                          price=round(price_v,self.PricePrecision), funds=price_v*volume_v, order_type='0')
        if True == result.get('result'):
            time.sleep(5)
            ret_oid = stockcode + '.' + result.get('order_id')
            if isbuy:
                self.nowpower -= (volume_v * price_v * self.MaxFees)
            self.order_handler(ret_oid, stockcode, None, isbuy, None, None, volume_v, price_v)
            SQLog.info("call_place_order,stockcode=", stockcode, "volume=", volume, "volume_v=", volume_v,
                       "price=", price, "price_v=", price_v,
                       "isbuy=", isbuy, "ismarketorder=", ismarketorder, "orderid=", ret_oid)
            SQLog.info("--------------------PlaceOrderOK--------------------", stockcode, "--------------------",
                       'BUY' if isbuy else 'SELL', volume_v, '@ ', price_v, "--------------------", ret_oid)
            return ret_oid
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
        result = self.spot_api.get_order_info(instrument_id=coin.upper()+'-USDT', order_id=oid)
        self.order_handler(orderid, 'CC.'+coin.upper(), result.get('state') in ['-2', '-1', '2'], None,
                           float(result.get('price_avg')) if result.get('price_avg') else None,
                           float(result.get('filled_size')), None, None)
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
            result = self.spot_api.revoke_order(oid=oid, instrument_id=coin.upper()+'-USDT')
            SQLog.info("call_cancel_order,orderid=", orderid, ",result=", result.get('result'))
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
    args = SunquantFrame.getargs('okex-sun', 'shannon')

    SQLog.setup_root_logger(args.market, args.strategy+'-debug', 'info', 'debug', 0, 1)
    SQLog.init_default(args.market, args.strategy, 'info', 'info', 1, 1)

    engine = TradeEngineOKEx(args.market)
    frame = SunquantFrame(engine, args.market, args.strategy)
    engine.set_frame(frame)
    if SunquantFrame.doargs(args, engine):
        exit(0)

    SQLog.init_default(args.market, args.strategy, 'info', 'info', 1 if platform.system() == "Windows" else 0, 1)
    frame.monitor_run()
    exit(0)
