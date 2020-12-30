# encoding: UTF-8
# sun's quant frame, 'sun' is the author's last name.
# author email: szy@tsinghua.org.cn

import os
import platform
import sys
import signal
import getopt
import argparse
import time
import datetime
import pytz
import random
import traceback
import threading
from utils.sq_log import *
from utils.sq_setting import *
import utils.sq_mail
from strategy.grid_strategy import *
from strategy.shannon_strategy import *
from strategy.trade_engine_base import *


class OrderLimit(object):
    _stock_buy_orders = {}
    _stock_sell_orders = {}

    @classmethod
    def reach_limit(cls, stockcode, isbuy, amount, max_amount_in_24hours, max_times_in_24hours=10):
        if not cls._stock_buy_orders.get(stockcode):
            cls._stock_buy_orders[stockcode] = []
        if not cls._stock_sell_orders.get(stockcode):
            cls._stock_sell_orders[stockcode] = []
        buy_orders = cls._stock_buy_orders[stockcode]
        sell_orders = cls._stock_sell_orders[stockcode]

        now = time.time()
        buy_amount_total = 0
        sell_amount_total = 0
        for i in range(len(buy_orders)-1, -1, -1):
            if now - buy_orders[i][0] > 86400:
                buy_orders.pop(i)
            else:
                buy_amount_total += buy_orders[i][1]
        for i in range(len(sell_orders)-1, -1, -1):
            if now - sell_orders[i][0] > 86400:
                sell_orders.pop(i)
            else:
                sell_amount_total += sell_orders[i][1]


        if abs(len(buy_orders) - len(sell_orders)) > max_times_in_24hours:
            SQLog.warn("OrderLimit.reach_limit,times limit,ret=True,stockcode=", stockcode,
                       "isbuy=", isbuy, "amount=", amount,
                       "max_times_in_24hours=", max_times_in_24hours,
                       "max_amount_in_24hours=", max_amount_in_24hours,
                       "buy_orders_count=", len(buy_orders), "sell_orders_count=", len(sell_orders),
                       "buy_amount_total=", buy_amount_total, "sell_amount_total=", sell_amount_total)
            return True

        if abs(buy_amount_total - sell_amount_total) > max_amount_in_24hours:
            SQLog.warn("OrderLimit.reach_limit,amount limit,ret=True,stockcode=", stockcode,
                       "isbuy=", isbuy, "amount=", amount,
                       "max_times_in_24hours=", max_times_in_24hours,
                       "max_amount_in_24hours=", max_amount_in_24hours,
                       "buy_orders_count=", len(buy_orders), "sell_orders_count=", len(sell_orders),
                       "buy_amount_total=", buy_amount_total, "sell_amount_total=", sell_amount_total)
            return True

        SQLog.info("OrderLimit.reach_limit,ret=False,stockcode=", stockcode,
                   "isbuy=", isbuy, "amount=", amount,
                   "max_times_in_24hours=", max_times_in_24hours,
                   "max_amount_in_24hours=", max_amount_in_24hours,
                   "buy_orders_count=", len(buy_orders), "sell_orders_count=", len(sell_orders),
                   "buy_amount_total=", buy_amount_total, "sell_amount_total=", sell_amount_total)
        if isbuy:
            buy_orders.append([now, amount])
        else:
            sell_orders.append([now, amount])
        return False


class SunquantFrame(object):

    def __init__(self, trade_engine, marketname, strategyname):
        # variables which start with uppercase letter may have configuration in setting.json
        self.LoopInterval = 60
        self.DefaultOtherHandlePeriod = 30
        self.MaxWaitsecsForDeal = 18000
        self.MailServer = None
        self.MailSender = None
        self.MailPassword = None
        self.MaxAmountMultiplier = 10

        self._trade_engine = trade_engine
        self.PricePrecision = 2
        self._marketname = marketname
        self._strategyname = strategyname
        self._isinit = False
        self._lasttime_sendmail = 0

        self._strategies = {}

        self._orders_event = threading.Event()

        SQSetting.fill_dict_from_settings(self.__dict__, 'sunquant_frame')
        SQLog.info("__init__,marketname=", marketname, "strategyname=", strategyname, "self.__dict__=", self.__dict__)
        if self._strategyname not in ['grid', 'shannon']:
            raise Exception("SunquantFrame,failed, this strategyname not supportted, strategyname=", strategyname)

    def connection_closed(self):
        self._orders_event.set()

    def order_handler(self, orderid, stockcode, isclose, isbuy, dealt_avg_price, dealt_qty, qty, price, issettled):
        if isclose and not issettled:
            SQLog.info("order_handler,order closed and not settled,stockcode=", stockcode, "orderid=", orderid)
            self._orders_event.set()

    def __load_strategy_assets(self):
        quotes_dict = self._trade_engine.get_quotes_dict()
        nowstocks_dict = self._trade_engine.get_nowstocks_dict()
        invest_total = self._trade_engine.get_invest_total()

        nowstocks_nowvalue = 0
        for sc in self._trade_engine.get_stockcode_pools():
            nowstocks_nowvalue += nowstocks_dict.get(sc, {}).get('qty', 0) * quotes_dict.get(sc, {}).get('last_price', 0)

        invest_total_nowvalue = invest_total
        invest_dict = {}
        invest_nowbalances_dict = {}
        invest_nowstocks_dict = {}
        invest_sdlastprices_dict = {}
        if self._isinit:
            for stockcode in self._trade_engine.get_stockcode_pools():
                stg = self._strategies.get(stockcode)
                if stg.is_halfopen() or stg.is_open():
                    lastprice = quotes_dict.get(stockcode, {}).get('last_price', 0)
                    invest_dict[stockcode] = stg.get_invest()
                    invest_nowbalances_dict[stockcode] = stg.get_nowbalance()
                    invest_nowstocks_dict[stockcode] = stg.get_nowstocks()
                    invest_nowvalue = stg.get_nowbalance() + stg.get_nowstocks() * lastprice
                    invest_sdlastprices_dict[stockcode] = lastprice
                    invest_total_nowvalue += invest_nowvalue - stg.get_invest()
        else:
            savedata = SQSaveData.load_data(self._marketname, self._strategyname)
            for stockcode in self._trade_engine.get_stockcode_pools():
                sd_stock = savedata.get(stockcode)
                if sd_stock:
                    lastprice = sd_stock.get('last_price', quotes_dict.get(stockcode, {}).get('last_price', 0))
                    balance = sd_stock.get('balance', 0)
                    stocks = sd_stock.get('stocks', 0)
                    invest_dict[stockcode] = sd_stock.get('invest', 1)
                    invest_nowbalances_dict[stockcode] = balance
                    invest_nowstocks_dict[stockcode] = stocks
                    invest_nowvalue = balance + stocks * lastprice
                    invest_sdlastprices_dict[stockcode] = lastprice
                    invest_total_nowvalue += invest_nowvalue - sd_stock.get('invest', 1)

        return nowstocks_nowvalue, invest_total_nowvalue, invest_dict, invest_nowbalances_dict, invest_nowstocks_dict, invest_sdlastprices_dict

    def __save_strategy_assets(self):
        if not self._isinit:
            SQLog.info("__save_strategy_assets,not init")
            return False

        quotes_dict = self._trade_engine.get_quotes_dict()
        invest_total = self._trade_engine.get_invest_total()
        balance_total = self._trade_engine.get_nowbalance()
        nowstocks_dict = self._trade_engine.get_nowstocks_dict()

        nowstocks_nowvalue = 0
        for sc in self._trade_engine.get_stockcode_pools():
            nowstocks_nowvalue += nowstocks_dict.get(sc, {}).get('qty', 0) * quotes_dict.get(sc, {}).get('last_price', 0)

        invest_total_nowvalue = invest_total
        save_dict = {}
        for stockcode in self._trade_engine.get_stockcode_pools():
            stg = self._strategies.get(stockcode)
            if stg.is_halfopen() or stg.is_open():
                lastprice = stg.get_nowprice()
                costprice = 0
                if nowstocks_dict.get(stockcode, {}).get('cost_price_valid', False):
                    costprice = nowstocks_dict.get(stockcode, {}).get('cost_price', 0)
                invest_nowvalue = stg.get_nowbalance() + stg.get_nowstocks() * lastprice
                invest_total_nowvalue += invest_nowvalue - stg.get_invest()
                stg_profit = invest_nowvalue / stg.get_invest()
                stg_profit_benchmark = (lastprice/stg.get_startprice() - 1.0) * 0.5 + 1.0
                save_dict[stockcode] = {'stocks_nowvalue': round(stg.get_nowstocks() * lastprice, self.PricePrecision),
                                        'balance': round(stg.get_nowbalance(), self.PricePrecision),
                                        'stocks': stg.get_nowstocks(),
                                        'last_price': lastprice,
                                        'cost_price': round(costprice, self.PricePrecision),
                                        'start_price': stg.get_startprice(),
                                        'invest_ratio': stg.get_investratio(),
                                        'invest': round(stg.get_invest(), self.PricePrecision),
                                        'invest_nowvalue': round(invest_nowvalue, self.PricePrecision),
                                        'profit': round(stg_profit, 4),
                                        'profit_benchmark': round(stg_profit_benchmark, 4)}

        if len(save_dict) == len(self._trade_engine.get_stockcode_pools()):
            ds_code = self._trade_engine.get_default_stock()
            ds_autorun = self._trade_engine.get_default_stock_autorun()
            ds_startprice = self._trade_engine.get_default_stock_startprice()
            ds_now = nowstocks_dict.get(ds_code, {})
            ds_qty = ds_now.get('qty', 0)
            ds_costprice = ds_now.get('cost_price', 0) if ds_now.get('cost_price_valid', False) else 0
            ds_cost = ds_costprice * ds_qty
            ds_lastprice = quotes_dict.get(ds_code, {}).get('last_price', 0)
            ds_nowvalue = ds_qty * ds_lastprice
            ds_profit = ds_nowvalue - ds_cost
            nowasserts_total = self._trade_engine.get_nowassets_total()
            nowasserts_total_minus_extra = nowasserts_total - self._trade_engine.get_balance_extra()
            others_profit = nowasserts_total_minus_extra - invest_total_nowvalue
            profit_total = nowasserts_total_minus_extra / invest_total
            profit_benchmark = ds_lastprice / ds_startprice

            save_dict['TOTAL'] = {'profit_total': round(profit_total, 4),
                                  'profit_benchmark': round(profit_benchmark, 4),
                                  'invest_total': invest_total,
                                  'nowasserts_total_minus_extra': round(nowasserts_total_minus_extra, self.PricePrecision),
                                  'nowasserts_total_from_engine': round(nowasserts_total, self.PricePrecision),
                                  'balance_total-nowpower': round(balance_total, self.PricePrecision),
                                  'nowstocks_nowvalue': round(nowstocks_nowvalue, self.PricePrecision),
                                  'invest_total_nowvalue': round(invest_total_nowvalue, self.PricePrecision),
                                  'strategy_stocks_profit': round(invest_total_nowvalue / invest_total, 4),
                                  'balance_extra': round(self._trade_engine.get_balance_extra()),
                                  'others_profit': round(others_profit, self.PricePrecision),
                                  'default_stock_code': ds_code,
                                  'default_stock_autorun': ds_autorun,
                                  'default_stock_qty': ds_qty,
                                  'default_stock_lastprice': ds_lastprice,
                                  'default_stock_costprice': round(ds_costprice, self.PricePrecision),
                                  'default_stock_startprice': ds_startprice,
                                  'default_stock_nowvalue': round(ds_nowvalue, self.PricePrecision),
                                  'default_stock_profit': round(ds_profit, self.PricePrecision)}

            SQSaveData.save_data(self._marketname, self._strategyname, save_dict)
            SQLog.info("__save_strategy_assets:save_dict=", save_dict)
            return True
        else:
            SQLog.warn("__save_strategy_assets:save_dict and stockcode_pools not match,maybe halfopen,stockcode_pools=",
                       self._trade_engine.get_stockcode_pools(), "save_dict=", save_dict)
            return False

    def load_savequote_data(self, stockcodes):
        savequote_data = SQSaveData.load_quote_data()
        always_call = self._trade_engine.get_always_call_avevol()
        SQLog.info("load_savequote_data,stockcodes=", stockcodes, "loadQuoteData:savequote_data=", savequote_data,
                   "AlwaysCallAveVol=", always_call)

        now = round(time.time(), 0)
        for stockcode in stockcodes:
            SQLog.info("load_savequote_data,stockcode=", stockcode, "now=", now,
                       "timestamp=", savequote_data.get(stockcode, {}).get('timestamp', 0))
            if always_call or now - savequote_data.get(stockcode, {}).get('timestamp', 0) > 3600 * 12:
                average, volatility = self._trade_engine.call_get_average_volatility(stockcode)
                if not savequote_data.get(stockcode):
                    savequote_data[stockcode] = {}
                if average:
                    savequote_data[stockcode]['average'] = average
                    savequote_data[stockcode]['timestamp'] = now
                if volatility:
                    savequote_data[stockcode]['volatility'] = volatility
        SQSaveData.save_quote_data(savequote_data)
        SQLog.info("load_savequote_data,saveQuoteData:savequote_data=", savequote_data)

        return savequote_data

    def init(self):
        if self._isinit:
            SQLog.info("init,already init")
            return False

        accret, balance_total, nowstocks_dict = self._trade_engine.call_get_account()
        mktret, quotes_dict = self._trade_engine.call_get_market_snapshot(self._trade_engine.get_stockcode_pools_forquotes())
        if (not accret) or (not mktret):
            raise Exception("init,call_get_account or call_get_market_snapshot failed!")

        nowstocks_nowvalue, invest_total_nowvalue, invest_dict, invest_nowbalances_dict, invest_nowstocks_dict, invest_sdlastprices_dict = self.__load_strategy_assets()
        changed = False

        savequote_data = self.load_savequote_data(self._trade_engine.get_stockcode_pools())

        for stockcode in self._trade_engine.get_stockcode_pools():
            issuspension = quotes_dict.get(stockcode, {}).get('suspension', False)
            lastprice = quotes_dict.get(stockcode, {}).get('last_price', 0)

            average = savequote_data.get(stockcode, {}).get('average', 0)
            volatility = savequote_data.get(stockcode, {}).get('volatility', 0)

            if self._strategyname == 'grid':
                self._strategies[stockcode] = GridStrategy(stockcode, self._marketname, self._strategyname,
                                                           self._trade_engine.get_invest_total(), average, volatility)
            elif self._strategyname == 'shannon':
                self._strategies[stockcode] = ShannonStrategy(stockcode, self._marketname, self._strategyname,
                                                              self._trade_engine.get_invest_total(), average, volatility)
            stg = self._strategies.get(stockcode)

            invest_nowstocks = invest_nowstocks_dict.get(stockcode, 0)
            invest_nowbalance = invest_nowbalances_dict.get(stockcode, 0)
            invest_sdlastprice = invest_sdlastprices_dict.get(stockcode, lastprice)
            invest_nowvalue = invest_nowbalance + invest_nowstocks * invest_sdlastprice
            if abs(stg.get_invest() - invest_dict.get(stockcode, 0)) > 1:
                invest_nowbalance += (stg.get_invest() - invest_dict.get(stockcode, 0))
                invest_nowvalue += (stg.get_invest() - invest_dict.get(stockcode, 0))
                changed = True
                SQLog.warn("init,invest changed,stockcode=", stockcode, "prev invest=", invest_dict.get(stockcode, 0),
                           "now invest=", stg.get_invest())

            SQLog.info("--------------------init ", stockcode, "lastprice=", lastprice, "invest_nowstocks=", invest_nowstocks,
                       "invest_nowbalance=", invest_nowbalance, "--------------------")

            wantBalance = stg.open(invest_sdlastprice, invest_nowbalance, invest_nowstocks)
            SQLog.info("init,stockcode=", stockcode, "halfopen=", stg.is_halfopen(),
                       "invest_nowvalue=", invest_nowvalue, "invest_nowstocks=", invest_nowstocks,
                       "invest_nowbalance=", invest_nowbalance,
                       "wantBalance=", wantBalance, "issuspension=", issuspension)

        SQLog.info("init,_strategies.len=", len(self._strategies))
        if changed:
            self.__save_strategy_assets()
        self._isinit = True
        return True

    def close(self, cancelallorder=False):
        try:
            if cancelallorder and self._trade_engine.is_open():
                self._trade_engine.call_cancel_all_orders()
            self.__deal_handle(None)
            self.__save_strategy_assets()
        except Exception as e:
            SQLog.error("close, Exception,e=", e, "traceback=\n", traceback.format_exc())

        for stockcode in self._trade_engine.get_stockcode_pools():
            stg = self._strategies.get(stockcode)
            if stg and stg.is_open():
                stg.close()
        self._strategies.clear()
        self._isinit = False

        SQLog.info("close:marketname=", self._marketname, "strategyname=", self._strategyname)
        return True

    def __cancel_overtime_orders(self, overtime_secs):
        SQLog.info("__cancel_overtime_orders,overtime_secs=", overtime_secs)
        canceling = False
        now = time.time()
        orders = self._trade_engine.get_orders_notclose(self._trade_engine.get_stockcode_pools())
        for orderid, order in orders.items():
            creatime = order.get('creatime')
            if now - creatime > overtime_secs:
                SQLog.info("__cancel_overtime_orders,timepast=", now-creatime, "order=", order)
                self._trade_engine.call_cancel_order(orderid)
                canceling = True
        return canceling

    def __settle_order(self, order):
        stockcode = order.get('code')
        lotsize = self._trade_engine.get_quotes_dict().get(stockcode, {}).get('lot_size', 1)
        orderid = order.get('order_id')
        dealt_qty = order.get('dealt_qty', 0)
        dealt_avg_price = order.get('dealt_avg_price', order.get('price', 0))
        lastprice = dealt_avg_price
        if order.get('isbuy') is None or orderid is None or orderid == 0:
            SQLog.error("__settle_order,isbuy or order_id is None,order=", order)
            return False

        SQLog.info("__settle_order,stockcode=", stockcode, ",orderid=", orderid)

        dealt = False
        if order.get('isbuy'):
            diffstocks = dealt_qty
            diffbalance = - dealt_qty * dealt_avg_price
            if dealt_qty > 0.00000001:
                SQLog.info("__settle_order,----------BuySuccess----------:", stockcode,
                           "dealt_avg_price=", dealt_avg_price, "dealt_qty=", dealt_qty, "orderid=", orderid)
                stg = self._strategies.get(stockcode)
                if stg:
                    stg.end_transact(lastprice, diffbalance, diffstocks, -1, dealt_avg_price, lotsize)
                dealt = True
        else:
            diffstocks = - dealt_qty
            diffbalance = dealt_qty * dealt_avg_price
            lastprice = dealt_avg_price
            if dealt_qty > 0.00000001:
                SQLog.info("__settle_order,----------SellSuccess----------:", stockcode,
                           "dealt_avg_price=", dealt_avg_price, "dealt_qty=", dealt_qty, "orderid=", orderid)
                stg = self._strategies.get(stockcode)
                if stg:
                    stg.end_transact(lastprice, diffbalance, diffstocks, 1, dealt_avg_price, lotsize)
                dealt = True

        self._trade_engine.order_settled(orderid)
        return dealt

    def __deal_handle(self, orders_notsettled):
        if orders_notsettled is None:
            orders_notsettled = self._trade_engine.get_orders_notsettled_idxbycode(self._trade_engine.get_stockcode_pools())

        dealt = False
        for stockcode in self._trade_engine.get_stockcode_pools():
            SQLog.info("--------------------__deal_handle--------------------", stockcode, "--------------------")
            orderlist = orders_notsettled.get(stockcode)
            if orderlist is None:
                continue

            settled = False
            for order in orderlist:
                if order.get('isclose'):
                    settled = True
                    if self.__settle_order(order):
                        dealt = True

            if settled:
                for orderother in orderlist:
                    if not orderother.get('isclose'):
                        if self.__settle_order(orderother):
                            dealt = True
                        self._trade_engine.call_cancel_order(orderother.get('order_id'))
        return dealt

    def __waitfor_deal(self, orders_notsettled, forcelurker):
        if orders_notsettled is None:
            orders_notsettled = self._trade_engine.get_orders_notsettled_idxbycode(self._trade_engine.get_stockcode_pools())

        if len(orders_notsettled) == 0:
            SQLog.info("__waitfor_deal,notsettled orders is empty,return continue......")
            return False

        maxwaitsecs = self.MaxWaitsecsForDeal
        if self._strategyname == 'shannon':
            maxwaitsecs = ShannonStrategy.MaxWaitsecsTaker
            if forcelurker or ShannonStrategy.BeLurker:
                maxwaitsecs = ShannonStrategy.MaxWaitsecsLurker
            elif ShannonStrategy.BeMaker:
                maxwaitsecs = ShannonStrategy.MaxWaitsecsMaker

        self.__cancel_overtime_orders(maxwaitsecs)

        self._trade_engine.call_list_order()

        if forcelurker:
            waitsecs = maxwaitsecs
            preopen_afterhours_end = self._trade_engine.secs_to_preopen_end()
            if preopen_afterhours_end == 0:
                preopen_afterhours_end = self._trade_engine.secs_to_afterhours_end()
            waitsecs = min(waitsecs, preopen_afterhours_end + 30*random.random())
            waitsecs = max(waitsecs, 60)
        elif ShannonStrategy.BeLurker:
            waitsecs = maxwaitsecs
        else:
            waitsecs = min(self.LoopInterval, maxwaitsecs)
        SQLog.info("__waitfor_deal,orders=", len(orders_notsettled), "forcelurker=", forcelurker,
                   "maxwaitsecs=", maxwaitsecs, "waitsecs=", waitsecs, "begin waiting until event set......")
        self._orders_event.wait(waitsecs)
        self._orders_event.clear()
        return self.__deal_handle(None)

    def __run_sellout_otherstocks(self):
        SQLog.info("__run_sellout_otherstocks,sellout_otherstocks=", self._trade_engine.get_sellout_otherstocks())
        quotes_dict = self._trade_engine.get_quotes_dict()
        nowstocks_dict = self._trade_engine.get_nowstocks_dict()
        did = False
        if self._trade_engine.get_sellout_otherstocks():
            ns_keys = list(nowstocks_dict.keys()).copy()
            for stockcode in ns_keys:
                if nowstocks_dict.get(stockcode, {}).get('qty', 0) > 0\
                        and not stockcode == self._trade_engine.get_default_stock()\
                        and stockcode not in self._trade_engine.get_stockcode_pools():

                    orders = self._trade_engine.get_orders_notclose([stockcode])
                    for orderid in orders.keys():
                        self._trade_engine.call_cancel_order(orderid)

                    if self._trade_engine.call_isnow_continuous_bidding(stockcode):
                        qty = nowstocks_dict.get(stockcode, {}).get('qty', 0)
                        lastprice = quotes_dict.get(stockcode, {}).get('last_price', 0)
                        sell_qty = min(0.99*self._trade_engine.get_smart_amount_segment()/lastprice if lastprice > 0 else qty, qty)
                        max_amount_in_24hours = self._trade_engine.get_smart_amount_segment() * self.MaxAmountMultiplier
                        if not OrderLimit.reach_limit(stockcode, False, sell_qty*lastprice, max_amount_in_24hours):
                            self._trade_engine.sell_waitfordeal(stockcode, sell_qty, False)
                        did = True
        return did

    def __run_defaultstock(self):
        if not self._trade_engine.get_default_stock_autorun():
            return False
        quotes_dict = self._trade_engine.get_quotes_dict()
        default_stock = self._trade_engine.get_default_stock()
        rb_min = self._trade_engine.get_balance_reserved_min()
        rb_max = self._trade_engine.get_balance_reserved_max()
        rb_mid = (rb_min + rb_max) / 2
        lastprice = quotes_dict.get(default_stock, {}).get('last_price', 0)
        SQLog.info("__run_defaultstock,default_stock=", default_stock)
        if default_stock and rb_min > 0 and rb_max > 0:
            if self._trade_engine.call_isnow_continuous_bidding(default_stock):
                accret, balance_total, nowstocks_dict = self._trade_engine.call_get_account()
                if accret:
                    diffbalance = 0
                    diffstocks = 0
                    max_amount_in_24hours = self._trade_engine.get_smart_amount_segment() * self.MaxAmountMultiplier
                    if balance_total > rb_max:
                        amount = min(self._trade_engine.get_smart_amount_segment(), balance_total - rb_mid)
                        if not OrderLimit.reach_limit(default_stock, True, amount, max_amount_in_24hours):
                            diffbalance, diffstocks = self._trade_engine.buy_waitfordeal(default_stock,
                                                                         amount / lastprice if lastprice > 0 else 1)
                    elif balance_total < rb_min:
                        amount = min(self._trade_engine.get_smart_amount_segment(), rb_mid - balance_total)
                        if not OrderLimit.reach_limit(default_stock, False, amount, max_amount_in_24hours):
                            diffbalance, diffstocks = self._trade_engine.sell_waitfordeal(default_stock,
                                                                          amount / lastprice if lastprice > 0 else 1)
                    SQLog.info("__run_defaultstock,default_stock=", default_stock, "lastprice=", lastprice,
                               "balance_reserved_min=", rb_min, "balance_reserved_max=", rb_max,
                               "balance_total=", balance_total, "diffbalance=", diffbalance, "diffstocks=", diffstocks)
                    return diffbalance > 0
        return False

    def run(self):
        if not self._isinit:
            raise Exception("run,but not init!")

        runcounter = 0
        while True:
            if not self._trade_engine.call_isnow_can_placeorder():
                SQLog.info("run: not in deal time, return.")
                return True
            now = datetime.datetime.now(pytz.timezone('Etc/GMT+5'))
            if (now.hour == 23 and not self._trade_engine.is_summer_time(now))\
                    or (now.hour == 22 and self._trade_engine.is_summer_time(now)):
                SQLog.info("run: mid night, need re init.now=", now)
                return True

            forcelurked = False
            accret, balance_total, nowstocks_dict = self._trade_engine.call_get_account()
            mktret, quotes_dict = self._trade_engine.call_get_market_snapshot(self._trade_engine.get_stockcode_pools_forquotes())
            if (not accret) or (not mktret):
                raise Exception("run,call_get_account or call_get_market_snapshot failed!")

            nowstocks_nowvalue, invest_total_nowvalue, invest_dict, invest_nowbalances_dict, invest_nowstocks_dict, invest_sdlastprices_dict = self.__load_strategy_assets()

            orders_notsettled = self._trade_engine.get_orders_notsettled_idxbycode(self._trade_engine.get_stockcode_pools())

            for stockcode in self._trade_engine.get_stockcode_pools():
                issuspension = quotes_dict.get(stockcode, {}).get('suspension', False)
                lastprice = quotes_dict.get(stockcode, {}).get('last_price', 0)
                invest_sdlastprice = invest_sdlastprices_dict.get(stockcode, lastprice)
                stg = self._strategies.get(stockcode)
                SQLog.info("--------------------run ", stockcode, "lastprice=", lastprice, "suspension=", issuspension,
                           "halfopen=", stg.is_halfopen(), "--------------------")

                if issuspension or not self._trade_engine.call_isnow_can_placeorder(stockcode):
                    continue
                iscontinousbidding = self._trade_engine.call_isnow_continuous_bidding(stockcode)
                isblind = self._trade_engine.call_isnow_blind(stockcode)
                forcelurked = forcelurked or not iscontinousbidding

                if orders_notsettled.get(stockcode):
                    SQLog.info("run,order already exits.stockcode=", stockcode, "orders=", orders_notsettled.get(stockcode))
                    continue

                if lastprice == 0 and iscontinousbidding:
                    self._trade_engine.resolve_quote(stockcode)

                if lastprice > 0:
                    if stg.is_halfopen() and iscontinousbidding:
                        stg.close()
                        wantBalance = stg.open(invest_sdlastprice, stg.get_nowbalance(), stg.get_nowstocks())
                        SQLog.info("run,halfopen,reopen,stockcode=", stockcode, "nowstocks=", stg.get_nowstocks(),
                                   "nowbalance=", stg.get_nowbalance(), "wantBalance=", wantBalance,
                                   "balance_total=", balance_total, "issuspension=", issuspension)

                    if not stg.is_halfopen():
                        nowstocks = nowstocks_dict.get(stockcode, {}).get('qty', 0)
                        invest_nowvalue = stg.get_nowbalance() + stg.get_nowstocks() * stg.get_nowprice()
                        assign_balance = stg.get_nowbalance()
                        if abs(nowstocks - stg.get_nowstocks()) > 0.5 and abs(1 - stg.get_nowprice()/lastprice) < 0.20:
                            assign_balance = invest_nowvalue - nowstocks * lastprice

                        lotsize = quotes_dict.get(stockcode, {}).get('lot_size', 1)
                        spread = quotes_dict.get(stockcode, {}).get('price_spread', self._trade_engine.spread(stockcode))
                        bidprice = quotes_dict.get(stockcode, {}).get('bid_price', lastprice - spread)
                        askprice = quotes_dict.get(stockcode, {}).get('ask_price', lastprice + spread)

                        needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume = \
                            stg.begin_transact(lastprice, assign_balance, nowstocks, bidprice, askprice,
                                               spread, lotsize, not iscontinousbidding, isblind)
                        if needbuy:
                            volume_v, price_v = self._trade_engine.round_order_param(stockcode, buyvolume, buyprice, True, False)
                            if volume_v > 0 and price_v > 0 and not OrderLimit.reach_limit(stockcode, True, buyprice*buyvolume, invest_nowvalue/2):
                                self._trade_engine.buy(stockcode, buyvolume, buyprice)
                        if needsell:
                            volume_v, price_v = self._trade_engine.round_order_param(stockcode, sellvolume, sellprice, False, False)
                            if volume_v > 0 and price_v > 0 and not OrderLimit.reach_limit(stockcode, False, sellprice*sellvolume, invest_nowvalue/2):
                                self._trade_engine.sell(stockcode, sellvolume, sellprice)

            runcounter += 1
            SQLog.info("run,runcounter=", runcounter, "profit=", invest_total_nowvalue/self._trade_engine.get_invest_total(),
                       "=", invest_total_nowvalue, "/", self._trade_engine.get_invest_total(),
                       "balance_total=", balance_total)

            if runcounter % self.DefaultOtherHandlePeriod == min(2, self.DefaultOtherHandlePeriod-1):
                did1 = self.__run_sellout_otherstocks()
                did2 = self.__run_defaultstock()
                if did1 or did2:
                    self.__save_strategy_assets()

            if not forcelurked:
                secs_to_wait = round(self.LoopInterval * (0.8 + 0.4*random.random()))
                SQLog.info("run,not forcelurked,waiting ", secs_to_wait, " seconds......")
                time.sleep(secs_to_wait)

            if self.__waitfor_deal(None, forcelurked):
                self.__save_strategy_assets()
            SQLog.info("run,waiting ", 60, " seconds......")
            time.sleep(60)


    def send_notice_mail(self):
        try:
            if time.time() - self._lasttime_sendmail < 3600*17:
                SQLog.info("send_notice_mail,too frequently,now=", time.time(), "lasttime=", self._lasttime_sendmail)
                return
            self._lasttime_sendmail = time.time()

            if self._trade_engine.is_open():
                self._trade_engine.call_resolve_dealtsum()

            nowstocks_nowvalue, invest_total_nowvalue, invest_dict, invest_nowbalances_dict, invest_nowstocks_dict, invest_sdlastprices_dict = self.__load_strategy_assets()

            quotes_dict = self._trade_engine.get_quotes_dict()
            nowstocks_dict = self._trade_engine.get_nowstocks_dict()
            invest_total = self._trade_engine.get_invest_total()
            balance_total = self._trade_engine.get_nowbalance()

            ds_code = self._trade_engine.get_default_stock()
            ds_autorun = self._trade_engine.get_default_stock_autorun()
            ds_startprice = self._trade_engine.get_default_stock_startprice()
            ds_now = nowstocks_dict.get(ds_code, {})
            ds_qty = ds_now.get('qty', 0)
            ds_costprice = ds_now.get('cost_price', 0) if ds_now.get('cost_price_valid', False) else 0
            ds_cost = ds_costprice * ds_qty
            ds_lastprice = quotes_dict.get(ds_code, {}).get('last_price', 0)
            ds_nowvalue = ds_qty * ds_lastprice
            ds_profit = ds_nowvalue - ds_cost
            nowasserts_total = self._trade_engine.get_nowassets_total()
            nowasserts_total_minus_extra = nowasserts_total - self._trade_engine.get_balance_extra()
            others_profit = nowasserts_total_minus_extra - invest_total_nowvalue
            profit_total = nowasserts_total_minus_extra / invest_total
            profit_benchmark = ds_lastprice / ds_startprice

            content = "\r\n一。最新情况:\r\n"
            if not self._trade_engine.is_open():
                content += "\tWARNING:trade_engine not connected.\r\n"
            content += "\t累计净值:\t" + str(round(profit_total, 4)) + "\r\n"
            content += "\t基准收益净值（假设满仓默认股票）:\t" + str(round(profit_benchmark, 4)) + "\r\n"
            content += "\t总投入:\t" + str(invest_total) + "\r\n"
            content += "\t总投入现值(不计外援):\t" + str(round(nowasserts_total_minus_extra, self.PricePrecision)) + "\r\n"
            content += "\t账户总资产:\t" + str(round(nowasserts_total, self.PricePrecision)) + "\r\n"
            content += "\t可用现金-购买力:\t" + str(round(balance_total, self.PricePrecision)) + "\r\n"
            content += "\t全部运行策略股票总市值:\t" + str(round(nowstocks_nowvalue, self.PricePrecision)) + "\r\n"
            content += "\t全部运行策略总值:\t" + str(round(invest_total_nowvalue, self.PricePrecision)) + "\r\n"
            content += "\t全部运行策略收益净值:\t" + str(round(invest_total_nowvalue / invest_total, 4)) + "\r\n"
            content += "\t外援资产:\t" + str(self._trade_engine.get_balance_extra()) + "\r\n"
            content += "\t其他盈亏(默认股票、手续费差额等)合计:\t" + str(round(others_profit, self.PricePrecision)) + "\r\n"
            content += "\t默认股票代码:\t" + str(ds_code) + "\r\n"
            content += "\t默认股票自动买卖:\t" + str(ds_autorun) + "\r\n"
            content += "\t默认股票数量:\t" + str(ds_qty) + "\r\n"
            content += "\t默认股票最新价:\t" + str(ds_lastprice) + "\r\n"
            content += "\t默认股票成本价:\t" + str(round(ds_costprice, self.PricePrecision)) + "\r\n"
            content += "\t默认股票起始价:\t" + str(round(ds_startprice, self.PricePrecision)) + "\r\n"
            content += "\t默认股票最新市值:\t" + str(round(ds_nowvalue, self.PricePrecision)) + "\r\n"
            content += "\t默认股票收益:\t" + str(round(ds_profit, self.PricePrecision)) + "\r\n\r\n"

            content += "\r\n二。今日持仓及个股成交汇总:\r\n"
            quotes_dict = self._trade_engine.get_quotes_dict()
            total_buy_value = 0
            total_sell_value = 0
            for stockcode in self._trade_engine.get_stockcode_pools():
                q = quotes_dict.get(stockcode, {})
                n = nowstocks_dict.get(stockcode, {})
                stg = self._strategies.get(stockcode)
                if stg.is_halfopen() or stg.is_open():
                    invest_nowvalue = stg.get_nowbalance() + stg.get_nowstocks() * q.get('last_price', 0)
                    stg_profit = invest_nowvalue / stg.get_invest()
                    stg_profit_benchmark = (q.get('last_price', 0) / stg.get_startprice() - 1.0) * 0.5 + 1.0
                    total_buy_value += n.get('today_buy_val', 0)
                    total_sell_value += n.get('today_sell_val', 0)
                    content += "\t" + stockcode + " " + q.get('stock_name', '') + " 股数:" + str(round(stg.get_nowstocks(), 0))\
                               + "\t市值:" + str(round(stg.get_nowstocks() * q.get('last_price', 0), self.PricePrecision))\
                               + "\t最新价:" + str(q.get('last_price', '-'))\
                               + "\t成本价:" + (str(round(n.get('cost_price', 0), self.PricePrecision)) if n.get('cost_price_valid', False) else '-')\
                               + "\t起始价:" + str(round(stg.get_startprice(), self.PricePrecision))\
                               + "\t限制投入仓位比例:" + str(stg.get_investratio())\
                               + "\t限制投入仓位市值:" + str(round(stg.get_invest(), self.PricePrecision)) \
                               + "\t虚拟资产:" + str(round(invest_nowvalue, self.PricePrecision)) \
                               + "\t虚拟收益:" + str(round(stg_profit, 4)) \
                               + "\t虚拟基准收益:" + str(round(stg_profit_benchmark, 4)) \
                               + "\t今日买入总量:" + str(n.get('today_buy_qty', 0))\
                               + "\t今日买入总额:" + str(round(n.get('today_buy_val', 0), self.PricePrecision))\
                               + "\t今日卖出总量:" + str(n.get('today_sell_qty', 0))\
                               + "\t今日卖出总额:" + str(round(n.get('today_sell_val', 0), self.PricePrecision)) + "\r\n\r\n"
            content += "\t合计买入总额:" + str(round(total_buy_value, self.PricePrecision))\
                       + "\t合计卖出总额:" + str(round(total_sell_value, self.PricePrecision)) + "\r\n\r\n"

            if platform.system() == "Linux":
                content += "\r\n三。本周成交分析（从周一到目前）:\r\n"
                content += "按股票汇总：\r\n"
                report1 = os.popen("grep Success " + SQLog.instance().get_logfilepath()
                                   + " | awk -F '  |-:|=' '{print $4}' | sort | uniq -c")
                content += report1.read()
                content += "按日期汇总：\r\n"
                report2 = os.popen("grep Success " + SQLog.instance().get_logfilepath()
                                   + " | awk -F ' ' '{print $1}' | sort | uniq -c")
                content += report2.read()
                content += "成交总笔数：\r\n"
                report3 = os.popen("grep Success " + SQLog.instance().get_logfilepath()
                                   + " | wc -l")
                content += report3.read()
                content += "成交明细：\r\n"
                report4 = os.popen("grep Success " + SQLog.instance().get_logfilepath()
                                   + " | awk -F '  |-:|=|,----------|Success---------' '{print $1,\" \",$4,\" \",$6,\" \",$10,\"@\",$8}'")
                content += report4.read()

            SQLog.info("send_notice_mail,receivers=", self._trade_engine.get_mail_receivers(), "content=", content)
            if self._trade_engine.get_mail_receivers():
                time.sleep(round(60 * random.random()))
                receivers = self._trade_engine.get_mail_receivers().split(',')
                subject = "Sunquant 日报 " + self._marketname
                SQLog.info("sending mail,receivers=", receivers, ",subject=", subject)
                if utils.sq_mail.sendmail(self.MailServer, self.MailSender, self.MailPassword, receivers, subject, content):
                    SQLog.info("send_notice_mail,success,receivers=", receivers, ",subject=", subject)
                else:
                    SQLog.info("send_notice_mail,failed,receivers=", receivers, ",subject=", subject)
        except Exception as e:
            SQLog.error("send_notice_mail, Exception,e=", e, "traceback=\n", traceback.format_exc())

    def monitor_run(self):
        # SIGINT=2  SIGTERM=15
        signal.signal(signal.SIGINT, term_sig_handler)
        signal.signal(signal.SIGTERM, term_sig_handler)

        hasException = False
        while True:
            try:
                if hasException:
                    hasException = False
                    SQLog.info("monitor_run, exception, waiting 900 seconds......")
                    time.sleep(900)
                    if self._trade_engine.secs_toopen() > 0:
                        self.send_notice_mail()
                    self.close()
                    self._trade_engine.close_api()

                waitsecs = self._trade_engine.secs_toopen()
                if self._trade_engine.has_preopen():
                    waitsecs = waitsecs + 1800*(1.0 + random.random()) if waitsecs > 0 else 3 * random.random()
                else:
                    waitsecs = waitsecs + 1 if waitsecs > 0 else 3 * random.random()
                SQLog.info("monitor_run, waiting for open, sleeping for ", waitsecs, " seconds......")
                time.sleep(waitsecs)

                self._trade_engine.open_api()
                if self._trade_engine.call_isnow_can_placeorder():
                    self.init()
                    self.run()
                    self.send_notice_mail()
                    self.close(True)
                self._trade_engine.close_api()
                SQLog.info("monitor_run, day closed, waiting 1800 seconds......")
                time.sleep(1800)
            except SystemExit:
                self.close()
                self._trade_engine.close_api()
                os._exit(0)
            except Exception as e:
                SQLog.error("monitor_run, Exception,e=", e, "traceback=\n", traceback.format_exc())
                hasException = True

    @classmethod
    def getargs(cls, market_default, strategy_default):
        cmdLineParser = argparse.ArgumentParser("sunquant_frame")
        cmdLineParser.description = "configuration file - setting.json, searching sequence: current path;  module path;  ~/sunquant/<marketname>/"
        cmdLineParser.add_argument("-m", "--market", type=str, default=market_default,
                                   help="marketname, used as log_dirname, savedata_dirname, setting section name, default is "+market_default)
        cmdLineParser.add_argument("-s", "--strategy", type=str, default=strategy_default,
                                   help="strategyname, used as log_fiename, savedata_filename, setting section name, strategy name, default is "+strategy_default)
        cmdLineParser.add_argument("-b", "--buycode", type=str, default=None, help="buycode")
        cmdLineParser.add_argument("-v", "--buyvolume", type=float, default=0, help="buyvolume")
        cmdLineParser.add_argument("-e", "--sellcode", type=str, default=None, help="sellcode")
        cmdLineParser.add_argument("-l", "--sellvolume", type=float, default=0, help="sellvolume")
        cmdLineParser.add_argument("-p", "--poslist", action="store_true", default=False, help="position list")
        cmdLineParser.add_argument("-o", "--orderlist", action="store_true", default=False, help="orders list")
        cmdLineParser.add_argument("-c", "--cancelallorders", action="store_true", default=False, help="cancel all orders")
        args = cmdLineParser.parse_args()
        print("sunquant_frame,using args", args)
        return args

    @classmethod
    def doargs(cls, args, engine):
        if args.buycode:
            engine.open_api()
            engine.buy_waitfordeal(args.buycode, float(args.buyvolume))
            engine.close_api()
            return True
        if args.sellcode:
            engine.open_api()
            engine.sell_waitfordeal(args.sellcode, float(args.sellvolume), False)
            engine.close_api()
            return True
        if args.poslist:
            engine.open_api()
            engine.call_get_account()
            engine.close_api()
            return True
        if args.orderlist:
            engine.open_api()
            engine.call_list_order()
            engine.close_api()
            return True
        if args.cancelallorders:
            engine.open_api()
            engine.call_cancel_all_orders()
            engine.close_api()
            return True
        return False


def term_sig_handler(signum, frame):
    print('term_sig_handler: singal: %d' % signum, flush=True)
    sys.exit()
