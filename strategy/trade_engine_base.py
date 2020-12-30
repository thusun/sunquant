# encoding: UTF-8
# author email: szy@tsinghua.org.cn

import random
import time
import datetime
import pytz
import threading
from abc import abstractmethod
from utils.sq_lock import *
from utils.sq_log import *
from utils.sq_setting import *


class TradeEngineBase(object):

    def __init__(self, marketname):
        # variables which start with uppercase letter may have configuration in setting.json
        self.StockCodes = ""
        self.InvestTotal = None
        self.BalanceExtra = 0
        self.BalanceReservedMin = -1.0
        self.BalanceReservedMax = -1.0
        self.DefaultStock = None
        self.DefaultStockAutorun = False
        self.DefaultStockStartPrice = 1.0
        self.SelloutOtherStocks = 0
        self.MaxFees = 1.005
        self.SmartWaitMinutes = 5
        self.SmartAmountSegment = 10000.0
        self.MailReceivers = ""
        self.AlwaysCallAveVol = 0

        # variables which NOT start with '_' are shared with subclasses
        self.stockcode_pools = []
        self.nowbalance = 0
        self.nowpower = 0
        self.nowasserts_total = 0
        #qty, cost_price,  cost_price_valid,  today_buy_qty,  today_buy_val,  today_sell_qty,  today_sell_val, stock_name
        self.nowstocks_dict = {}
        #lot_size,  price_spread,  suspension,  last_price,  close_price,  ask_price,  bid_price,  ask_vol,  bid_vol,  stock_name
        self.quotes_dict = {}
        self.account_lock = SQLock()

        #code, isclose, isbuy, dealt_avg_price, dealt_qty, qty, price, creatime, issettled, isbalance_addback
        self.orders_dict = {}
        self.orders_dict_lock = SQLock()

        self._marketname = marketname

        self.load_setting()
        SQLog.info("__init__,marketname=", marketname, "self.__dict__=", self.__dict__)

    def set_frame(self, frame):
        self._frame = frame

    def load_setting(self):
        SQSetting.fill_dict_from_settings(self.__dict__, 'trade_engine_' + self._marketname)
        self.stockcode_pools = []
        if self.StockCodes:
            self.stockcode_pools = self.StockCodes.split(',')

    def precision(self, stockcode):
        p = 2
        if stockcode[0:3] == 'FX.':
            p = 4
        elif stockcode[0:3] == 'CC.':
            p = 2
        return p

    def spread(self, stockcode):
        spread = 0.01
        if stockcode[0:3] == 'FX.':
            spread = 0.0001
        elif stockcode[0:3] == 'CC.':
            spread = 0.000001
        return spread

    def connection_closed(self):
        if self._frame:
            self._frame.connection_closed()

    def order_handler(self, orderid, stockcode, isclose, isbuy, dealt_avg_price, dealt_qty, qty, price):
        SQLog.info("order_handler,orderid=", orderid, "code=", stockcode, "isclose=", isclose, "isbuy=", isbuy,
                   "dealt_avg_price=", dealt_avg_price, "dealt_qty=", dealt_qty, "qty=", qty, "price=", price)

        if orderid is None or orderid == 0:
            SQLog.error("order_handler,orderid is None or zero,orderid=", orderid,
                        "code=", stockcode, "isclose=", isclose, "isbuy=", isbuy,
                        "dealt_avg_price=", dealt_avg_price, "dealt_qty=", dealt_qty, "qty=", qty, "price=", price)
            return

        issettled = False
        isbalance_addback = False
        with self.orders_dict_lock:
            if orderid not in self.orders_dict:
                self.orders_dict[orderid] = {'order_id': orderid, 'creatime': round(time.time(), 3)}
            o = self.orders_dict[orderid]

            if stockcode is None:
                stockcode = o.get('code', None)
            else:
                o['code'] = stockcode

            if isclose is None:
                isclose = o.get('isclose', None)
            else:
                o['isclose'] = isclose

            if isbuy is None:
                isbuy = o.get('isbuy', None)
            else:
                o['isbuy'] = isbuy

            if price is None:
                price = o.get('price', 0)
            else:
                o['price'] = price

            if dealt_avg_price is None:
                dealt_avg_price = o.get('dealt_avg_price', price)
            else:
                o['dealt_avg_price'] = dealt_avg_price

            if dealt_qty is None:
                dealt_qty = o.get('dealt_qty', 0)
            else:
                o['dealt_qty'] = dealt_qty

            if qty is None:
                qty = o.get('qty', 0)
            else:
                o['qty'] = qty

            issettled = o.get('issettled', False)
            isbalance_addback = o.get('isbalance_addback', False)
            if isclose and not isbalance_addback:
                o['isbalance_addback'] = True

        if isclose and not isbalance_addback:
            with self.account_lock:
                self.nowpower += (qty * dealt_avg_price - dealt_qty * dealt_avg_price if isbuy else dealt_qty * dealt_avg_price)
                self.nowbalance += (- dealt_qty * dealt_avg_price if isbuy else dealt_qty * dealt_avg_price)
                if stockcode not in self.nowstocks_dict:
                    self.nowstocks_dict[stockcode] = {}
                ns = self.nowstocks_dict[stockcode]
                ns['qty'] = ns.get('qty', 0) + (dealt_qty if isbuy else - dealt_qty)

        if self._frame:
            self._frame.order_handler(orderid, stockcode, isclose, isbuy, dealt_avg_price, dealt_qty, qty, price, issettled)

    def order_settled(self, orderid):
        with self.orders_dict_lock:
            if orderid not in self.orders_dict:
                self.orders_dict[orderid] = {'order_id': orderid, 'creatime': round(time.time(), 3)}
            o = self.orders_dict[orderid]
            o['issettled'] = True
            o['isclose'] = True
            SQLog.info("order_settled,orderid=", orderid, "stockcode=", o.get('code'))

    def clear_order_cache(self):
        with self.orders_dict_lock:
            self.orders_dict.clear()

    def get_order_from_cache(self, orderid):
        order_ret = None
        if not orderid is None:
            with self.orders_dict_lock:
                order = self.orders_dict.get(orderid, None)
                if order:
                    order_ret = order.copy()
        SQLog.info("get_order_from_cache,orderid=", orderid, "order=", order_ret)
        return order_ret

    def get_order(self, orderid):
        if orderid is None:
            SQLog.info("get_order,orderid=", orderid, "order=None")
            return None
        order = self.get_order_from_cache(orderid)
        if order is None:
            order = self.call_get_order(orderid)
        return order

    def get_orders_notclose(self, stockcodes=None):
        orders_ret = {}
        with self.orders_dict_lock:
            for orderid, order in self.orders_dict.items():
                if stockcodes and order.get('code') not in stockcodes:
                    continue
                if not order.get('isclose'):
                    orders_ret[orderid] = order.copy()
        return orders_ret

    def get_orders_notsettled_idxbycode(self, stockcodes=None):
        orders_ret = {}
        with self.orders_dict_lock:
            for orderid, order in self.orders_dict.items():
                code = order.get('code')
                if code is None:
                    continue
                if stockcodes and code not in stockcodes:
                    continue
                if not order.get('issettled'):
                    if orders_ret.get(code) is None:
                        orders_ret[code] = [order.copy()]
                    else:
                        orders_ret[code].append(order.copy())
        return orders_ret

    def resolve_dealtsum(self):
        orders_temp = {}
        with self.orders_dict_lock:
            orders_temp = self.orders_dict.copy()

        with self.account_lock:
            for sc, stock in self.nowstocks_dict.items():
                stock['today_buy_qty'] = 0
                stock['today_buy_val'] = 0
                stock['today_sell_qty'] = 0
                stock['today_sell_val'] = 0

            for orderid, order in orders_temp.items():
                code = order.get('code')
                if code is None or order.get('isbuy') is None:
                    continue
                if self.nowstocks_dict.get(code) is None:
                    continue
                n = self.nowstocks_dict[code]
                if order.get('isbuy'):
                    n['today_buy_qty'] += order.get('dealt_qty', 0)
                    n['today_buy_val'] += order.get('dealt_qty', 0) * order.get('dealt_avg_price', order.get('price', 0))
                else:
                    n['today_sell_qty'] += order.get('dealt_qty', 0)
                    n['today_sell_val'] += order.get('dealt_qty', 0) * order.get('dealt_avg_price', order.get('price', 0))
        return True

    def get_stockcode_pools(self):
        return self.stockcode_pools

    def get_stockcode_pools_forquotes(self):
        c = self.stockcode_pools.copy()
        if self.DefaultStock:
            c.append(self.DefaultStock)
        if len(self.nowstocks_dict) > 0:
            c.extend(list(self.nowstocks_dict.keys()).copy())
        c = list(filter(None, list(set(c))))
        return c

    def get_invest_total(self):
        return self.InvestTotal

    def get_balance_extra(self):
        return self.BalanceExtra

    def get_balance_reserved_min(self):
        return self.BalanceReservedMin

    def get_balance_reserved_max(self):
        return self.BalanceReservedMax

    def get_default_stock(self):
        return self.DefaultStock

    def get_default_stock_autorun(self):
        return self.DefaultStockAutorun

    def get_default_stock_startprice(self):
        return self.DefaultStockStartPrice

    def get_sellout_otherstocks(self):
        return self.SelloutOtherStocks

    def get_nowstocks_dict(self):
        return self.nowstocks_dict

    def get_nowbalance(self):
        return self.nowbalance

    def get_nowassets_total(self):
        return self.nowasserts_total

    def get_quotes_dict(self):
        return self.quotes_dict

    def get_smart_amount_segment(self):
        return self.SmartAmountSegment

    def get_mail_receivers(self):
        return self.MailReceivers

    def get_always_call_avevol(self):
        return self.AlwaysCallAveVol

    @classmethod
    def is_summer_time(cls, dt):
        #从2007年开始每年3月的第二个星期日开始夏令时，结束日期为11月的第一个星期日
        tz = pytz.timezone('Etc/GMT+5')
        is_summer_time = (dt.month > 3 and dt.month < 11)
        if dt.month == 3:
            march8th = datetime.datetime(year=dt.year, month=dt.month, day=8, hour=6, tzinfo=tz)
            if dt.day >= 8 + 6 - march8th.weekday():
                is_summer_time = True
        if dt.month == 11:
            nov1st = datetime.datetime(year=dt.year, month=dt.month, day=1, hour=6, tzinfo=tz)
            if dt.day < 1 + 6 - nov1st.weekday():
                is_summer_time = True
        return is_summer_time

    @classmethod
    def secs_toopen_hk(cls):
        tz = pytz.timezone('Etc/GMT-8')
        now = datetime.datetime.now(tz)
        opentime = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=9, minute=30, second=0, tzinfo=tz)
        if now.hour >= 16:
            opentime = opentime + datetime.timedelta(days=1)

        if opentime.weekday() == 5:
            opentime = opentime + datetime.timedelta(days=2)
        elif opentime.weekday() == 6:
            opentime = opentime + datetime.timedelta(days=1)

        secs = (opentime - now).total_seconds()
        return secs if secs > 0 else 0

    @classmethod
    def secs_toclose_hk(cls):
        tz = pytz.timezone('Etc/GMT-8')
        now = datetime.datetime.now(tz)
        signtime = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=16, minute=00, second=0, tzinfo=tz)

        if signtime.weekday() == 5 or signtime.weekday() == 6:
            return 0

        secs = (signtime - now).total_seconds()
        return secs if secs > 0 else 0

    @classmethod
    def secs_toopen_fx(cls):
        tz = pytz.timezone('Etc/GMT+5')
        now = datetime.datetime.now(tz)

        is_summer_now = cls.is_summer_time(now)
        hour_begin = 14 if is_summer_now else 15
        hour_end = 14 if is_summer_now else 15

        if now.weekday() >= 0 and now.weekday() <= 3:
            return 0
        if now.weekday() == 4 and now.hour < hour_end:
            return 0
        if now.weekday() == 6 and now.hour >= hour_begin:
            return 0

        opentime = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=hour_begin, minute=0, second=0, tzinfo=tz)
        if opentime.weekday() == 4:
            opentime = opentime + datetime.timedelta(days=2)
        elif opentime.weekday() == 5:
            opentime = opentime + datetime.timedelta(days=1)

        is_summer_opentime = cls.is_summer_time(opentime)
        if is_summer_now and not is_summer_opentime:
            opentime = opentime + datetime.timedelta(hours=1)
        elif (not is_summer_now) and is_summer_opentime:
            opentime = opentime - datetime.timedelta(hours=1)

        secs = (opentime - now).total_seconds()
        return secs if secs > 0 else 0

    @classmethod
    def secs_toopen_us(cls):
        tz = pytz.timezone('Etc/GMT+5')
        now = datetime.datetime.now(tz)

        is_summer_now = cls.is_summer_time(now)
        hour_begin = 3 if is_summer_now else 4
        hour_end = 15 if is_summer_now else 16
        # if including after_hours: hour_end = 19 if is_summer_now else 20
        opentime = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=hour_begin, minute=0, second=0, tzinfo=tz)
        if (now.hour == hour_end and now.minute >= 0) or (now.hour > hour_end):
            opentime = opentime + datetime.timedelta(days=1)

        if opentime.weekday() == 5:
            opentime = opentime + datetime.timedelta(days=2)
        elif opentime.weekday() == 6:
            opentime = opentime + datetime.timedelta(days=1)

        is_summer_opentime = cls.is_summer_time(opentime)
        if is_summer_now and not is_summer_opentime:
            opentime = opentime + datetime.timedelta(hours=1)
        elif (not is_summer_now) and is_summer_opentime:
            opentime = opentime - datetime.timedelta(hours=1)

        secs = (opentime - now).total_seconds()
        return secs if secs > 0 else 0

    @classmethod
    def secs_to_preopen_end_us(cls):
        tz = pytz.timezone('Etc/GMT+5')
        now = datetime.datetime.now(tz)

        is_summer_now = cls.is_summer_time(now)
        hour_begin = 8 if is_summer_now else 9
        signtime = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=hour_begin, minute=30, second=0, tzinfo=tz)

        if signtime.weekday() == 5 or signtime.weekday() == 6:
            return 0

        secs = (signtime - now).total_seconds()
        return secs if secs > 0 else 0

    @classmethod
    def secs_to_afterhours_end_us(cls):
        tz = pytz.timezone('Etc/GMT+5')
        now = datetime.datetime.now(tz)

        is_summer_now = cls.is_summer_time(now)
        hour_end = 19 if is_summer_now else 20
        signtime = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=hour_end, minute=0, second=0, tzinfo=tz)

        if signtime.weekday() == 5 or signtime.weekday() == 6:
            return 0

        secs = (signtime - now).total_seconds()
        return secs if secs > 0 else 0

    @classmethod
    def isnow_continuous_bidding_usstk(cls):
        ret = False
        tz = pytz.timezone('Etc/GMT+5')
        now = datetime.datetime.now(tz)
        is_summer_now = cls.is_summer_time(now)
        if now.weekday() < 5:
            if is_summer_now:
                ret = (now.hour >= 9 and now.hour < 15) or (now.hour == 8 and now.minute >= 30)
            else:
                ret = (now.hour >= 10 and now.hour < 16) or (now.hour == 9 and now.minute >= 30)
        SQLog.info("isnow_continuous_bidding_usstk,ret=", ret)
        return ret

    @abstractmethod
    def isnow_can_placeorder_usstk(self):
        ret = False
        tz = pytz.timezone('Etc/GMT+5')
        now = datetime.datetime.now(tz)
        is_summer_now = self.is_summer_time(now)
        if now.weekday() < 5:
            if is_summer_now:
                ret = now.hour >= 3 and now.hour < 19
            else:
                ret = now.hour >= 4 and now.hour < 20
        SQLog.info("isnow_can_placeorder_usstk,ret=", ret)
        return ret

    @classmethod
    def isnow_can_placeorder_hkstk(cls):
        ret = False
        tz = pytz.timezone('Etc/GMT-8')
        now = datetime.datetime.now(tz)
        if now.weekday() < 5:
            ret = (now.hour == 9 and now.minute >= 30) or (now.hour > 9 and now.hour < 16)
        SQLog.info("isnow_can_placeorder_hkstk,ret=", ret)
        return ret

    @classmethod
    def isnow_can_placeorder_forex(cls):
        ret = False
        tz = pytz.timezone('Etc/GMT+5')
        now = datetime.datetime.now(tz)
        is_summer_now = cls.is_summer_time(now)
        if now.weekday() >= 0 and now.weekday() <= 3:
            ret = True
        elif now.weekday() == 4:
            if is_summer_now:
                ret = now.hour < 14
            else:
                ret = now.hour < 15
        elif now.weekday() == 5:
            ret = False
        elif now.weekday() == 6:
            if is_summer_now:
                ret = now.hour >= 14
            else:
                ret = now.hour >= 15
        SQLog.info("isnow_can_placeorder_forex,ret=", ret)
        return ret

    def round_order_param(self, stockcode, volume, price, isbuy, ismarketorder):
        lotsize = self.quotes_dict.get(stockcode, {}).get('lot_size')
        if lotsize is None or lotsize <= 0:
            lotsize = 1

        spread = self.quotes_dict.get(stockcode, {}).get('price_spread', self.spread(stockcode))
        if spread is None or spread <= 0:
            spread = 1.0
            for i in range(self.precision(stockcode)):
                spread /= 10.0

        volume_v = int(round(volume / lotsize)) * lotsize

        quote = self.quotes_dict.get(stockcode, {})
        if 0 == price:
            price = quote.get('last_price', 0)
        if ismarketorder:
            if isbuy:
                price = quote.get('ask_price', quote.get('last_price', price)) * 1.01
            else:
                price = quote.get('bid_price', quote.get('last_price', price)) * 0.99
        price_v = round(int(round(price / spread)) * spread, self.precision(stockcode))
        if price_v < spread:
            price_v = spread

        if isbuy:
            if self.MaxFees * price_v * volume_v > self.nowpower:
                volume_new = self.nowpower / (self.MaxFees * price_v)
                if volume_new > 0.2 * volume:
                    volume_v = int(round(volume_new / lotsize) - 1) * lotsize
                else:
                    volume_v = 0
                SQLog.info("round_order_param,no enough power,stockcode=", stockcode, "lotsize=", lotsize,
                           "volume=", volume, "volume_v=", volume_v, "price=", price, "price_v=", price_v,
                           "nowpower=", self.nowpower, "nowbalance=", self.nowbalance)
        else:
            if volume_v > self.nowstocks_dict.get(stockcode, {}).get('qty', 0):
                volume_v = self.nowstocks_dict.get(stockcode, {}).get('qty', 0)
                SQLog.info("round_order_param,no enough stocks,stockcode=", stockcode, "lotsize=", lotsize,
                           "volume=", volume, "volume_v=", volume_v, "price=", price, "price_v=", price_v,
                           "nowstocks=", self.nowstocks_dict.get(stockcode, {}).get('qty', 0))

        if volume_v < 0:
            volume_v = 0
        SQLog.info("round_order_param,stockcode=", stockcode, "lotsize=", lotsize, "volume=", volume,
                   "volume_v=", volume_v, "price=", price, "price_v=", price_v, "nowpower=", self.nowpower)
        return [volume_v, price_v]

    def smart_marketorder_waitfordeal(self, stockcode, volume, isbuy):
        init_stocks = self.nowstocks_dict.get(stockcode, {}).get('qty', 0)
        diffstocks = 0
        diffbalance = 0
        lastprice = self.quotes_dict.get(stockcode, {}).get('last_price', 0)
        lotsize = self.quotes_dict.get(stockcode, {}).get('lot_size', 1)

        SQLog.info("smart_marketorder_waitfordeal,stockcode=", stockcode, "volume=", volume, "isbuy=", isbuy,
                   "init_stocks=", init_stocks, "lastprice=", lastprice, "lotsize=", lotsize)
        if volume < lotsize:
            SQLog.warn("smart_marketorder_waitfordeal,volume<lotsize,stockcode=", stockcode)
            return [0, 0]

        volume = int(volume / lotsize) * lotsize

        vol_segment = lotsize
        if lastprice > 0:
            vol_segment = max(lotsize, lotsize * round(self.SmartAmountSegment / (lastprice * lotsize)))
        vol_deal_sum = 0
        times_notdeal = 0
        while vol_deal_sum < volume:
            vol_now = vol_segment
            if vol_now > volume - vol_deal_sum:
                vol_now = volume - vol_deal_sum

            orderid = self.call_place_order(stockcode, vol_now, lastprice, isbuy, True)
            if orderid is None:
                break

            if vol_deal_sum + vol_now < volume:
                waitsecs = 30 + round(60 * self.SmartWaitMinutes * (0.5 + random.random()) * vol_now / vol_segment)
            else:
                waitsecs = 10
            SQLog.info("smart_marketorder_waitfordeal,stockcode=", stockcode, "volume=", volume, "isbuy=", isbuy,
                       "vol_now=", vol_now, "vol_segment=", vol_segment, "vol_deal_sum=", vol_deal_sum,
                       "orderid=", orderid, "waitsecs=", waitsecs, "waiting......")
            time.sleep(waitsecs)

            order = self.call_get_order(orderid)
            if order is None or not order.get('isclose'):
                times_notdeal += 1
                self.call_cancel_order(orderid)
                order = self.get_order(orderid)
                SQLog.warn("smart_marketorder_waitfordeal,order not close,stockcode=", stockcode,
                            ",volume=", volume, "vol_segment=", vol_segment, "vol_deal_sum=", vol_deal_sum,
                            "orderid=", orderid, "new order=", order)
            if order and order.get('isclose'):
                vol_deal_sum += order.get('dealt_qty', 0)
                diffstocks += order.get('dealt_qty', 0)
                diffbalance += order.get('dealt_qty', 0) * order.get('dealt_avg_price', order.get('price', 0))
                if lastprice == 0:
                    lastprice = order.get('dealt_avg_price', order.get('price', 0))
                    vol_segment = max(lotsize, lotsize * round(self.SmartAmountSegment / (lastprice * lotsize)))
            else:
                raise Exception("smart_marketorder_waitfordeal failed.stockcode=" + stockcode)
            if times_notdeal >= 3:
                break

        self.call_get_account()
        now_stocks = self.nowstocks_dict.get(stockcode, {}).get('qty', 0)
        if isbuy:
            diffbalance = - diffbalance
        else:
            diffstocks = - diffstocks

        if abs((now_stocks - init_stocks) - diffstocks) > 1:
            SQLog.error("smart_marketorder_waitfordeal,diffstocks not match,stockcode=", stockcode,
                        "diffstocks=", diffstocks, "real diffstocks=", now_stocks - init_stocks)

        SQLog.info("smart_marketorder_waitfordeal,finish,stockcode=", stockcode, "volume=", volume, "isbuy=", isbuy,
                   "vol_segment=", vol_segment, "vol_deal_sum=", vol_deal_sum,
                   "init_stocks=", init_stocks, "now_stocks=", now_stocks)
        return [diffbalance, diffstocks]

    def buy(self, stockcode, volume, price):
        return self.call_place_order(stockcode, volume, price, True, False)

    def sell(self, stockcode, volume, price, leftone=True):
        if leftone:
            nowstocks = self.nowstocks_dict.get(stockcode, {}).get('qty', 0)
            lotsize = self.quotes_dict.get(stockcode, {}).get('lot_size', 1)
            if volume > nowstocks - lotsize:
                volume = nowstocks - lotsize
        return self.call_place_order(stockcode, volume, price, False, False)

    def buy_waitfordeal(self, stockcode, volume):
        return self.smart_marketorder_waitfordeal(stockcode, volume, True)

    def sell_waitfordeal(self, stockcode, volume, leftone=True):
        if leftone:
            nowstocks = self.nowstocks_dict.get(stockcode, {}).get('qty', 0)
            lotsize = self.quotes_dict.get(stockcode, {}).get('lot_size', 1)
            if volume > nowstocks - lotsize:
                volume = nowstocks - lotsize
        return self.smart_marketorder_waitfordeal(stockcode, volume, False)


    @abstractmethod
    def open_api(self):
        self.call_list_order()
        return True

    @abstractmethod
    def close_api(self):
        self.clear_order_cache()
        return True

    @abstractmethod
    def resolve_quote(self, stockcode):
        return None

    @abstractmethod
    def is_open(self):
        return True

    @abstractmethod
    def secs_toopen(self):
        ret = 86400*7
        secs_us = self.secs_toopen_us()
        secs_hk = self.secs_toopen_hk()
        secs_fx = self.secs_toopen_fx()
        codes = self.get_stockcode_pools()
        for c in codes:
            if len(c) > 3 and c[0:3] == 'US.':
                ret = min(ret, secs_us)
            elif len(c) > 3 and c[0:3] == 'HK.':
                ret = min(ret, secs_hk)
            elif len(c) > 3 and c[0:3] == 'FX.':
                ret = min(ret, secs_fx)
            elif len(c) > 3 and c[0:3] == 'CC.':
                ret = 0
        return ret

    @abstractmethod
    def secs_to_preopen_end(self):
        return 0

    @abstractmethod
    def secs_to_afterhours_end(self):
        return 0

    @abstractmethod
    def has_preopen(self):
        return False

    @abstractmethod
    def call_isnow_can_placeorder(self, stockcode=None):
        if not stockcode is None and len(stockcode) > 3:
            if stockcode[0:3] == 'US.':
                ret = self.isnow_can_placeorder_usstk()
            elif stockcode[0:3] == 'HK.':
                ret = self.isnow_can_placeorder_hkstk()
            elif stockcode[0:3] == 'FX.':
                ret = self.isnow_can_placeorder_forex()
            elif stockcode[0:3] == 'CC.':
                ret = True
            else:
                ret = True
        else:
            ret = False
            codes = self.get_stockcode_pools()
            for c in codes:
                if len(c) > 3 and c[0:3] == 'US.':
                    ret = ret or self.isnow_can_placeorder_usstk()
                elif len(c) > 3 and c[0:3] == 'HK.':
                    ret = ret or self.isnow_can_placeorder_hkstk()
                elif len(c) > 3 and c[0:3] == 'FX.':
                    ret = ret or self.isnow_can_placeorder_forex()
                elif len(c) > 3 and c[0:3] == 'CC.':
                    ret = True
        SQLog.info("call_isnow_can_placeorder,stockcode=", stockcode, "ret=", ret)
        return ret

    @abstractmethod
    def call_isnow_continuous_bidding(self, stockcode=None):
        if not stockcode is None and len(stockcode) > 3:
            if stockcode[0:3] == 'US.':
                ret = self.isnow_continuous_bidding_usstk()
            elif stockcode[0:3] == 'HK.':
                ret = self.isnow_can_placeorder_hkstk()
            elif stockcode[0:3] == 'FX.':
                ret = self.isnow_can_placeorder_forex()
            elif stockcode[0:3] == 'CC.':
                ret = True
            else:
                ret = True
        else:
            ret = True
            codes = self.get_stockcode_pools()
            for c in codes:
                if len(c) > 3 and c[0:3] == 'US.':
                    ret = ret and self.isnow_continuous_bidding_usstk()
                elif len(c) > 3 and c[0:3] == 'HK.':
                    ret = ret and self.isnow_can_placeorder_hkstk()
                elif len(c) > 3 and c[0:3] == 'FX.':
                    ret = ret and self.isnow_can_placeorder_forex()
                elif len(c) > 3 and c[0:3] == 'CC.':
                    ret = ret and True
        SQLog.info("call_isnow_continuous_bidding,stockcode=", stockcode, "ret=", ret)
        return ret

    @abstractmethod
    def call_isnow_blind(self, stockcode=None):
        return False

    @abstractmethod
    def call_get_account(self):
        return [False, self.nowbalance, self.nowstocks_dict]

    @abstractmethod
    def call_resolve_dealtsum(self):
        return True

    @abstractmethod
    def call_get_market_snapshot(self, stockcodes):
        return [False, self.quotes_dict]

    @abstractmethod
    def call_get_average_volatility(self, stockcode):
        return [0, 0]

    @abstractmethod
    def call_place_order(self, stockcode, volume, price, isbuy, ismarketorder):
        return None

    @abstractmethod
    def call_get_order(self, orderid):
        return None

    @abstractmethod
    def call_list_order(self):
        return False

    @abstractmethod
    def call_cancel_order(self, orderid):
        return False

    @abstractmethod
    def call_cancel_all_orders(self):
        return False

