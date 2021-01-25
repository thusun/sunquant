# encoding: UTF-8
# website: www.futu5.com
# author email: szy@tsinghua.org.cn

import platform
import os
import sys
import time
import futu
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy.trade_engine_base import *
from strategy.sunquant_frame import *


class TradeOrderHanbler(futu.TradeOrderHandlerBase):

    def __init__(self, engine):
        super().__init__()
        self._trade_engine = engine

    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        SQLog.debug("TradeOrderHandler,ret=", ret, "data=\n", data)

        if futu.RET_OK == ret:
            if data.size > 0 and self._trade_engine.EnvType == data['trd_env'][0]:
                orderid = data['order_id'][0]
                code = data['code'][0]
                isclose = data['order_status'][0] in TradeEngineFutu.ORDER_STATUS_CLOSE\
                          or int(data['qty'][0] + 0.5) == int(data['dealt_qty'][0] + 0.5)
                trd_side = data['trd_side'][0]
                qty = data['qty'][0]
                dealt_avg_price = data['dealt_avg_price'][0] if data['dealt_avg_price'][0] > 0 else data['price'][0]
                dealt_qty = data['dealt_qty'][0]
                price = data['price'][0]
                self._trade_engine.order_handler(orderid, code, isclose, futu.TrdSide.BUY == trd_side,
                                                 dealt_avg_price, dealt_qty, qty, price)
                SQLog.debug("TradeOrderHandler,orderid=", orderid, "code=", code, "isclose=", isclose,
                            "trd_side=", trd_side, "dealt_avg_price=", dealt_avg_price, "dealt_qty=", dealt_qty,
                            "qty=", qty, "price=", price)
        return ret, data


class TradeDealHandler(futu.TradeDealHandlerBase):
    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        SQLog.debug("TradeDealHandler,ret=", ret, "data=\n", data)
        return ret, data


class CallLimit(object):
    _placeorder = []
    _modifyorder = []
    _historykline = []

    @classmethod
    def wait_placeorder(cls):
        #REAL and SIMULATE are combine together, if no SIMULATE running, the following can be set to 5, 15
        times_1 = 2
        times_30 = 7

        now = time.time()
        gap = 0
        if len(cls._placeorder) >= times_1:
            gap = max(gap, cls._placeorder[-times_1] + 2 - now)
        if len(cls._placeorder) >= times_30:
            gap = max(gap, cls._placeorder[-times_30] + 32 - now)

        SQLog.info("wait_placeorder,gap=", gap, "_placeorder=", cls._placeorder)
        time.sleep(gap)
        cls._placeorder.append(round(time.time(), 2))
        if len(cls._placeorder) > times_30 + 5:
            cls._placeorder.pop(0)

    @classmethod
    def wait_modifyorder(cls):
        # REAL and SIMULATE are combine together, if no SIMULATE running, the following can be set to 5, 20
        times_1 = 2
        times_30 = 10

        now = time.time()
        gap = 0
        if len(cls._modifyorder) >= times_1:
            gap = max(gap, cls._modifyorder[-times_1] + 2 - now)
        if len(cls._modifyorder) >= times_30:
            gap = max(gap, cls._modifyorder[-times_30] + 32 - now)

        SQLog.info("wait_modifyorder,gap=", gap, "__modifyorder=", cls._modifyorder)
        time.sleep(gap)
        cls._modifyorder.append(round(time.time(), 2))
        while len(cls._modifyorder) > times_30 + 5:
            cls._modifyorder.pop(0)

    @classmethod
    def wait_historykline(cls):
        # REAL and SIMULATE are combine together, if no SIMULATE running, the following can be set to 1, 10
        times_1 = 1
        times_30 = 5

        now = time.time()
        gap = 0
        if len(cls._historykline) >= times_1:
            gap = max(gap, cls._historykline[-times_1] + 2 - now)
        if len(cls._historykline) >= times_30:
            gap = max(gap, cls._historykline[-times_30] + 32 - now)

        SQLog.info("wait_historykline,gap=", gap, "_historykline=", cls._historykline)
        time.sleep(gap)
        cls._historykline.append(round(time.time(), 2))
        while len(cls._historykline) > times_30 + 5:
            cls._historykline.pop(0)


class TradeEngineFutu(TradeEngineBase):

    ORDER_STATUS_CLOSE = [futu.OrderStatus.SUBMIT_FAILED, futu.OrderStatus.FILLED_ALL, futu.OrderStatus.CANCELLED_PART,
                          futu.OrderStatus.CANCELLED_ALL, futu.OrderStatus.FAILED, futu.OrderStatus.DISABLED,
                          futu.OrderStatus.DELETED]
    ORDER_STATUS_NOTCLOSE = [futu.OrderStatus.UNSUBMITTED, futu.OrderStatus.WAITING_SUBMIT, futu.OrderStatus.SUBMITTING,
                             futu.OrderStatus.SUBMITTED, futu.OrderStatus.FILLED_PART]
    ORDER_STATUS_PLACEFAILED = [futu.OrderStatus.SUBMIT_FAILED, futu.OrderStatus.FAILED, futu.OrderStatus.DISABLED]

    def __init__(self, marketname):
        super().__init__(marketname)

        # variables which start with uppercase letter may have configuration in setting.json
        self.ApiIP = '127.0.0.1'
        self.ApiPort = None
        self.Market = None
        self.EnvType = None
        self.HasUSQuote = 0
        self.TradePassword = None
        self.TradePasswordMd5 = None
        self.AveVolaStockCodes = None

        self._quote_ctx = None
        self._trade_ctx = None

        self.load_setting()

        SQLog.info("__init__,marketname=", marketname, "self.__dict__=", self.__dict__)

    def open_api(self):
        SQLog.info("open_api,quote already open=", self.is_open())

        if self._quote_ctx is None:
            self._quote_ctx = futu.OpenQuoteContext(self.ApiIP, self.ApiPort)

        if self._trade_ctx is None:
            if self.Market == futu.Market.HK:
                self._trade_ctx = futu.OpenHKTradeContext(self.ApiIP, self.ApiPort)
            elif self.Market == futu.Market.US:
                self._trade_ctx = futu.OpenUSTradeContext(self.ApiIP, self.ApiPort)
            else:
                raise Exception("open_api failed,Market parameter wrong.")
            if self.EnvType == futu.TrdEnv.REAL:
                ret, data = self._trade_ctx.unlock_trade(self.TradePassword, self.TradePasswordMd5)
                if futu.RET_OK != ret:
                    raise Exception("open_api failed,unlock_trade failed,data=" + str(data))

            ret, data = self._trade_ctx.get_acc_list()
            SQLog.debug("open_api,get_acc_list,ret=", ret, "data=\n", data)

            self._trade_ctx.set_handler(TradeOrderHanbler(self))
            self._trade_ctx.set_handler(TradeDealHandler())
            self._trade_ctx.start()
            super().open_api()

            if self.AveVolaStockCodes and self._frame:
                self._frame.load_savequote_data(self.AveVolaStockCodes.split(','))
        return True

    def close_api(self):
        if not self._quote_ctx is None:
            self._quote_ctx.close()
            del self._quote_ctx
            self._quote_ctx = None
        if not self._trade_ctx is None:
            self._trade_ctx.close()
            del self._trade_ctx
            self._trade_ctx = None

        super().close_api()
        SQLog.info("close_api")
        return True

    def is_open(self):
        return not self._quote_ctx is None and not self._trade_ctx is None

    def resolve_quote(self, stockcode):
        if self.Market == futu.Market.HK:
            self.call_get_market_snapshot([stockcode])
        elif self.Market == futu.Market.US:
            if self.nowstocks_dict.get(stockcode, {}).get('qty', 0) == 0:
                self.buy_waitfordeal(stockcode, 1)
        return True

    def secs_toopen(self):
        if self.Market == futu.Market.HK:
            return self.secs_toopen_hk()
        elif self.Market == futu.Market.US:
            return self.secs_toopen_us()
        return super().secs_toopen()

    def secs_to_preopen_end(self):
        if self.Market == futu.Market.HK:
            return self.secs_toopen_hk()
        elif self.Market == futu.Market.US:
            return self.secs_to_preopen_end_us()
        return super().secs_to_preopen_end()

    def secs_to_afterhours_end(self):
        if self.Market == futu.Market.HK:
            return self.secs_toclose_hk()
        elif self.Market == futu.Market.US:
            return self.secs_to_afterhours_end_us()
        return super().secs_to_afterhours_end()

    def has_preopen(self):
        if self.Market == futu.Market.US:
            return True
        return False

    def call_isnow_can_placeorder(self, stockcode=None):
        if self.Market == futu.Market.US and not self.isnow_can_placeorder_usstk():
            return False
        gsret, gsdata = self._quote_ctx.get_global_state()
        SQLog.debug("call_isnow_can_placeorder,stockcode=", stockcode, "get_global_state gsret=", gsret, "gsdata=\n", gsdata)
        if gsret == futu.RET_OK:
            ret = True
            market_hk = gsdata.get('market_hk')
            market_us = gsdata.get('market_us')
            if self.Market == futu.Market.HK:
                ret = (market_hk in ['MORNING', 'AFTERNOON', 'REST'])
            elif self.Market == futu.Market.US:
                ret = market_us in ['PRE_MARKET_BEGIN', 'AFTER_HOURS_BEGIN', 'MORNING', 'AFTERNOON']
            SQLog.info("call_isnow_can_placeorder,stockcode=", stockcode, "ret=", ret, "market_hk=", market_hk, "market_us=", market_us)
            return ret
        else:
            raise Exception("call_isnow_can_placeorder failed,stockcode="+stockcode+"gsret="+str(gsret)+",gsdata="+str(gsdata))

    def call_isnow_continuous_bidding(self, stockcode=None):
        if self.Market == futu.Market.US and not self.isnow_continuous_bidding_usstk():
            return False
        gsret, gsdata = self._quote_ctx.get_global_state()
        SQLog.debug("call_isnow_continuous_bidding,get_global_state gsret=", gsret, "gsdata=\n", gsdata)
        if gsret == futu.RET_OK:
            ret = True
            market_hk = gsdata.get('market_hk')
            market_us = gsdata.get('market_us')
            if self.Market == futu.Market.HK:
                ret = (market_hk in ['MORNING', 'AFTERNOON'])
            elif self.Market == futu.Market.US:
                ret = market_us in ['MORNING', 'AFTERNOON']
            SQLog.info("call_isnow_continuous_bidding,ret=", ret, "market_hk=", market_hk, "market_us=", market_us)
            return ret
        else:
            raise Exception("call_isnow_continuous_bidding failed,gsret="+str(gsret)+",gsdata="+str(gsdata))

    @abstractmethod
    def call_isnow_blind(self, stockcode=None):
        if self.Market == futu.Market.US and self.HasUSQuote:
            return not self.call_isnow_continuous_bidding(stockcode)
        else:
            return not self.call_isnow_continuous_bidding(stockcode)

    def call_get_account(self):
        accret, accdata = self._trade_ctx.accinfo_query(trd_env=self.EnvType)
        SQLog.debug("call_get_account,accinfo_query accret=", accret, "accdata=\n", accdata)
        if accret == futu.RET_OK:
            with self.account_lock:
                self.nowbalance = accdata['cash'][0]
                self.nowpower = self.nowbalance - accdata['frozen_cash'][0]
                self.nowasserts_total = accdata['total_assets'][0]
            SQLog.info("call_get_account,nowbalance=", self.nowbalance, "nowpower=", self.nowpower, "nowasserts_total=", self.nowasserts_total)
        else:
            raise Exception("call_get_account failed,accret=" + str(accret) + ",accdata=" + str(accdata))

        posret, posdata = self._trade_ctx.position_list_query(code='', trd_env=self.EnvType)
        SQLog.info("call_get_account,position_list_query posret=", posret, "posdata=\n", posdata)
        if posret == futu.RET_OK:
            with self.account_lock:
                self.nowstocks_dict.clear()
                for _, row in posdata.iterrows():
                    if row['code'] not in self.nowstocks_dict:
                        self.nowstocks_dict[row['code']] = {}
                    n = self.nowstocks_dict[row['code']]
                    n['qty'] = row['qty']
                    n['cost_price'] = row['cost_price']
                    n['cost_price_valid'] = row['cost_price_valid']
                    n['today_buy_qty'] = row['today_buy_qty']
                    n['today_buy_val'] = row['today_buy_val']
                    n['today_sell_qty'] = row['today_sell_qty']
                    n['today_sell_val'] = row['today_sell_val']
                    n['stock_name'] = row['stock_name']

                    if row['code'] not in self.quotes_dict:
                        self.quotes_dict[row['code']] = {}
                    q = self.quotes_dict[row['code']]
                    if self.Market == futu.Market.US and not self.HasUSQuote:
                        q['last_price'] = row['nominal_price']
                    q['stock_name'] = row['stock_name']
            SQLog.info("call_get_account,nowstocks_dict=", self.nowstocks_dict)
        else:
            raise Exception("call_get_account failed,posret=" + str(posret) + ",posdata=" + str(posdata))

        return [True, self.nowbalance, self.nowstocks_dict]

    def call_get_market_snapshot(self, stockcodes):
        mktret = 0
        if self.Market == futu.Market.HK or (self.Market == futu.Market.US and self.HasUSQuote):
            for i in range(3):
                mktret, mktdata = self._quote_ctx.get_market_snapshot(stockcodes)
                SQLog.debug("call_get_market_snapshot,get_market_snapshot mktret=", mktret, "mktdata=\n", mktdata)
                time.sleep(i)
                if mktret == futu.RET_OK:
                    for _, row in mktdata.iterrows():
                        if row['code'] not in self.quotes_dict:
                            self.quotes_dict[row['code']] = {}
                        q = self.quotes_dict[row['code']]
                        q['lot_size'] = row['lot_size']
                        q['price_spread'] = row['price_spread']
                        q['suspension'] = row['suspension']
                        q['last_price'] = row['last_price']
                        q['ask_price'] = row['ask_price']
                        q['bid_price'] = row['bid_price']
                        q['ask_vol'] = row['ask_vol']
                        q['bid_vol'] = row['bid_vol']

                        bid_price = q.get('bid_price', 0)
                        ask_price = q.get('ask_price', 0)
                        last_price = q.get('last_price', 0)
                        close_price = q.get('close_price', 0)
                        if bid_price > 0.01 and ask_price > 0.01 and (not last_price or last_price < bid_price or last_price > ask_price):
                            q['last_price'] = round(0.5 * (ask_price + bid_price), self.precision(row['code']))
                        if not last_price and close_price > 0.01:
                            q['last_price'] = close_price
                    SQLog.info("call_get_market_snapshot,quotes_dict=", self.quotes_dict)
                    return [futu.RET_OK == mktret, self.quotes_dict]
            raise Exception("call_get_market_snapshot failed,try 3 times no result,stockcodes=" + str(stockcodes))
        return [futu.RET_OK == mktret, self.quotes_dict]

    def call_get_average_volatility(self, stockcode):
        if self.Market == futu.Market.US and not self.HasUSQuote:
            SQLog.info("call_get_average_volatility,no us quotes,stockcode=", stockcode, "average=0")
            return [0, 0]

        CallLimit.wait_historykline()
        ret, prices, page_req_key = self._quote_ctx.request_history_kline(stockcode,
                                                                          fields=[futu.KL_FIELD.CLOSE,futu.KL_FIELD.HIGH,futu.KL_FIELD.LOW])
        if ret != futu.RET_OK:
            SQLog.warn("call_get_average_volatility,request_history_kline fail,stockcode=", stockcode, "ret=", ret, "prices=\n", prices)
            raise Exception("call_get_average_volatility failed,stockcode="+stockcode+",ret="+str(ret))

        #period = 20
        period = 5
        if len(prices) >= max(period, 6):
            closes = prices['close'].values
            highs = prices['high'].values
            lows = prices['low'].values

            average = round(sum(closes[-period:]) / period, self.precision(stockcode))

            sumv = 0.0
            for i in range(-1, -6, -1):
                sumv += abs(highs[i] / lows[i] - 1) if lows[i] > 0 else 0
                sumv += abs(closes[i] / closes[i-1] - 1) if closes[i-1] > 0 else 0
            volatility = round(sumv / 10, 6)
            SQLog.info("call_get_average_volatility,stockcode=", stockcode, "average=", average, "volatility=", volatility)
            return [average, volatility]
        else:
            SQLog.warn("call_get_average_volatility,request_history_kline fail,stockcode=", stockcode, "ret=", ret, "prices=\n", prices)
            return [0, 0]


    def call_place_order(self, stockcode, volume, price, isbuy, ismarketorder):
        if isbuy:
            ts = futu.TrdSide.BUY
            al = -0.01
        else:
            ts = futu.TrdSide.SELL
            al = 0.01

        iscontinuousbidding = self.call_isnow_continuous_bidding(stockcode)
        ot = futu.OrderType.NORMAL
        if ismarketorder and self.Market == futu.Market.US and self.EnvType == futu.TrdEnv.REAL and iscontinuousbidding:
            ot = futu.OrderType.MARKET

        volume_v, price_v = self.round_order_param(stockcode, volume, price, isbuy, ismarketorder)
        if volume_v <= 0:
            SQLog.info("call_place_order failed,volume_v<=0,stockcode=", stockcode, "volume=", volume, "volume_v=", volume_v,
                       "price=", price, "price_v=", price_v, "isbuy=", isbuy, "ismarketorder=", ismarketorder)
            return None
        if 0 == price_v and ismarketorder and self.Market == futu.Market.US\
                and self.EnvType == futu.TrdEnv.SIMULATE and iscontinuousbidding:
            price_v = 3000 if isbuy else 0.01
        if 0 == price_v and not futu.OrderType.MARKET == ot:
            SQLog.info("call_place_order failed,price==0,stockcode=", stockcode, "volume=", volume, "price=", price,
                       "isbuy=", isbuy, "ismarketorder=", ismarketorder)
            return None

        if self.EnvType == futu.TrdEnv.SIMULATE and self.Market == futu.Market.US and not self.isnow_continuous_bidding_usstk():
            return None
        
        CallLimit.wait_placeorder()
        ret, data = self._trade_ctx.place_order(price=price_v, qty=volume_v, code=stockcode, trd_side=ts,
                                                order_type=ot, adjust_limit=al, trd_env=self.EnvType,
                                                time_in_force=futu.TimeInForce.DAY,
                                                fill_outside_rth=not ot == futu.OrderType.MARKET)
        SQLog.debug("call_place_order,place_order ret=", ret, "data=\n", data)
        if futu.RET_OK == ret:
            orderid = data['order_id'][0]
            orderstatus = data['order_status'][0]
            SQLog.info("call_place_order,stockcode=", stockcode, "volume=", volume, "volume_v=", volume_v,
                       "price=", price, "price_v=", price_v, "isbuy=", isbuy, "ismarketorder=", ismarketorder,
                       "ordertype=", ot, "orderid=", orderid, "orderstatus=", orderstatus)
            if orderstatus in self.ORDER_STATUS_PLACEFAILED:
                raise Exception("call_place_order failed,stockcode="+stockcode+",ret="+str(ret)+",data="+str(data))
            if isbuy:
                self.nowpower -= (volume_v * price_v * self.MaxFees)
            SQLog.info("--------------------PlaceOrderOK--------------------", stockcode, "--------------------",
                       'BUY' if isbuy else 'SELL', volume_v, '@ ', 'MKT' if ot == futu.OrderType.MARKET else price_v,
                       "--------------------", orderid)
            return orderid
        else:
            raise Exception("call_place_order failed,stockcode="+stockcode+",ret="+str(ret)+",data="+str(data))

    def call_get_order(self, orderid):
        if orderid is None:
            SQLog.info("call_get_order,orderid=", orderid, "order=None")
            return None
        for i in range(3):
            ret, data = self._trade_ctx.order_list_query(order_id=orderid, trd_env=self.EnvType)
            SQLog.debug("call_get_order,order_list_query orderid=", orderid, "ret=", ret, "data=\n", data)
            time.sleep(i)
            if futu.RET_OK == ret:
                if data.size > 0 and orderid == data['order_id'][0]:
                    orderid = data['order_id'][0]
                    code = data['code'][0]
                    isclose = data['order_status'][0] in self.ORDER_STATUS_CLOSE\
                              or int(data['qty'][0] + 0.5) == int(data['dealt_qty'][0] + 0.5)
                    trd_side = data['trd_side'][0]
                    qty = data['qty'][0]
                    dealt_avg_price = data['dealt_avg_price'][0] if data['dealt_avg_price'][0] > 0 else \
                    data['price'][0]
                    dealt_qty = data['dealt_qty'][0]
                    price = data['price'][0]
                    self.order_handler(orderid, code, isclose, futu.TrdSide.BUY == trd_side, dealt_avg_price, dealt_qty, qty, price)
                    order = self.get_order_from_cache(orderid)
                    SQLog.info("call_get_order,orderid=", orderid, "order=", order, "order_status=", data['order_status'][0])
                    return order
        raise Exception("call_get_order failed,try 3 times no result,orderid=" + str(orderid))

    def call_list_order(self):
        ret, data = self._trade_ctx.order_list_query(status_filter_list=self.ORDER_STATUS_NOTCLOSE, trd_env=self.EnvType)
        if futu.RET_OK == ret:
            for _, row in data.iterrows():
                orderid = row['order_id']
                code = row['code']
                isclose = row['order_status'] in self.ORDER_STATUS_CLOSE\
                          or int(row['qty'] + 0.5) == int(row['dealt_qty'] + 0.5)
                trd_side = row['trd_side']
                qty = row['qty']
                dealt_avg_price = row['dealt_avg_price'] if row['dealt_avg_price'] > 0 else row['price']
                dealt_qty = row['dealt_qty']
                price = row['price']
                self.order_handler(orderid, code, isclose, futu.TrdSide.BUY == trd_side, dealt_avg_price, dealt_qty, qty, price)
        SQLog.info("call_list_order,order_list_query,ret=", ret, "data=\n", data)
        return True

    def call_cancel_order(self, orderid):
        if orderid is None:
            SQLog.info("call_cancel_order,orderid=", orderid, "return False")
            return False
        for i in range(3):
            CallLimit.wait_modifyorder()
            time.sleep(i)
            modret, moddata = self._trade_ctx.modify_order(modify_order_op=futu.ModifyOrderOp.CANCEL,
                                                           order_id=orderid, qty=0, price=0, trd_env=self.EnvType)
            SQLog.debug("call_cancel_order,modify_order orderid=", orderid, "ret=", modret, "data=\n", moddata)
            if futu.RET_OK == modret:
                SQLog.info("call_cancel_order,orderid=", orderid, "result=True")
                return True
            else:
                getret, getdata = self._trade_ctx.order_list_query(order_id=orderid, trd_env=self.EnvType)
                SQLog.debug("call_cancel_order,order_list_query orderid=", orderid, "ret=", getret, "data=\n", getdata)
                if futu.RET_OK == getret:
                    if getdata.size > 0 and orderid == getdata['order_id'][0]:
                        isclose = getdata['order_status'][0] in self.ORDER_STATUS_CLOSE\
                                  or int(getdata['qty'][0] + 0.5) == int(getdata['dealt_qty'][0] + 0.5)
                        SQLog.info("call_cancel_order,orderid=", orderid, "isclose=", isclose,
                                   "order_status=", getdata['order_status'][0])
                        if isclose:
                            return True

        raise Exception("call_cancel_order failed,try 3 times no result,orderid=" + str(orderid))

    def call_cancel_all_orders(self):
        if futu.TrdEnv.REAL == self.EnvType:
            ret, data = self._trade_ctx.cancel_all_order(trd_env=self.EnvType)
            SQLog.debug("call_cancel_all_orders,cancel_all_order,ret=", ret, "data=\n", data)
            SQLog.info("call_cancel_all_orders")
            return futu.RET_OK == ret
        else:
            ret, data = self._trade_ctx.order_list_query(status_filter_list=self.ORDER_STATUS_NOTCLOSE, trd_env=self.EnvType)
            SQLog.debug("call_cancel_all_orders,order_list_query,ret=", ret, "data=\n", data)
            if futu.RET_OK == ret:
                for _, row in data.iterrows():
                    if row['order_status'] in self.ORDER_STATUS_NOTCLOSE:
                        self.call_cancel_order(row['order_id'])
            SQLog.info("call_cancel_all_orders")
            return True


if __name__ == '__main__':
    args = SunquantFrame.getargs('futuhk-sunsimu', 'shannon')

    SQLog.setup_root_logger(args.market, args.strategy+'-debug', 'info', 'debug', 0, 1)
    SQLog.init_default(args.market, args.strategy, 'info', 'info', 1, 1)

    engine = TradeEngineFutu(args.market)
    frame = SunquantFrame(engine, args.market, args.strategy)
    engine.set_frame(frame)
    if SunquantFrame.doargs(args, engine):
        exit(0)

    SQLog.init_default(args.market, args.strategy, 'info', 'info', 1 if platform.system() == "Windows" else 0, 1)
    frame.monitor_run()
    exit(0)
