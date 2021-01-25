# encoding: UTF-8
# website: www.interactivebrokers.com
# author email: szy@tsinghua.org.cn

import argparse
import platform
import os
import sys
import threading
import time
import datetime
import pytz
import collections
import inspect

import futu
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy.trade_engine_base import *
from strategy.sunquant_frame import *

from ibapi import wrapper
from ibapi import utils
from ibapi.client import EClient
from ibapi.utils import iswrapper

from ibapi import (decoder, reader, comm)
from ibapi.common import * # @UnusedWildImport
from ibapi.contract import * # @UnusedWildImport
from ibapi.order import * # @UnusedWildImport
from ibapi.order_state import * # @UnusedWildImport
from ibapi.ticktype import * # @UnusedWildImport
from ibapi.account_summary_tags import *


class IBClient(EClient):
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)

        # how many times a method is called to see test coverage
        self.clntMeth2callCount = collections.defaultdict(int)
        self.clntMeth2reqIdIdx = collections.defaultdict(lambda: -1)
        self.reqId2nReq = collections.defaultdict(int)
        self.setupDetectReqId()

    def countReqId(self, methName, fn):
        def countReqId_(*args, **kwargs):
            self.clntMeth2callCount[methName] += 1
            idx = self.clntMeth2reqIdIdx[methName]
            if idx >= 0:
                sign = -1 if 'cancel' in methName else 1
                self.reqId2nReq[sign * args[idx]] += 1
            return fn(*args, **kwargs)

        return countReqId_

    def setupDetectReqId(self):
        methods = inspect.getmembers(EClient, inspect.isfunction)
        for (methName, meth) in methods:
            if methName != "send_msg":
                # don't screw up the nice automated logging in the send_msg()
                self.clntMeth2callCount[methName] = 0
                # logging.debug("meth %s", name)
                sig = inspect.signature(meth)
                for (idx, pnameNparam) in enumerate(sig.parameters.items()):
                    (paramName, param) = pnameNparam # @UnusedVariable
                    if paramName == "reqId":
                        self.clntMeth2reqIdIdx[methName] = idx

                setattr(IBClient, methName, self.countReqId(methName, meth))
                # print("IBClient.clntMeth2reqIdIdx", self.clntMeth2reqIdIdx)


class IBWrapper(wrapper.EWrapper):
    def __init__(self):
        wrapper.EWrapper.__init__(self)

        self.wrapMeth2callCount = collections.defaultdict(int)
        self.wrapMeth2reqIdIdx = collections.defaultdict(lambda: -1)
        self.reqId2nAns = collections.defaultdict(int)
        self.setupDetectWrapperReqId()

    def countWrapReqId(self, methName, fn):
        def countWrapReqId_(*args, **kwargs):
            self.wrapMeth2callCount[methName] += 1
            idx = self.wrapMeth2reqIdIdx[methName]
            if idx >= 0:
                self.reqId2nAns[args[idx]] += 1
            return fn(*args, **kwargs)

        return countWrapReqId_

    def setupDetectWrapperReqId(self):
        methods = inspect.getmembers(wrapper.EWrapper, inspect.isfunction)
        for (methName, meth) in methods:
            self.wrapMeth2callCount[methName] = 0
            # logging.debug("meth %s", name)
            sig = inspect.signature(meth)
            for (idx, pnameNparam) in enumerate(sig.parameters.items()):
                (paramName, param) = pnameNparam # @UnusedVariable
                # we want to count the errors as 'error' not 'answer'
                if 'error' not in methName and paramName == "reqId":
                    self.wrapMeth2reqIdIdx[methName] = idx

            setattr(IBWrapper, methName, self.countWrapReqId(methName, meth))
            # print("IBClient.wrapMeth2reqIdIdx", self.wrapMeth2reqIdIdx)


class IBAgent(IBWrapper, IBClient):
    def __init__(self, trade_engine):
        IBWrapper.__init__(self)
        IBClient.__init__(self, wrapper=self)

        self._trade_engine = trade_engine

        self.total_cash_balance = 0.0
        self.buying_power = 0.0
        self.total_cash_value = 0.0
        self.stock_market_value = 0.0
        self.position_dict = {}
        self.historical_bars = {}

        self.nextValidOrderId = None
        self.reqMktData_Id2code = {}
        self.reqMktData_waitids = set()
        self.reqHistoricalData_Id2code = {}
        self.placeOrder_waitid = None
        self.cancelOrder_waitid = None
        self.reqId2nErr = collections.defaultdict(int)

        self.EventWaitSecs = 60
        self.connect_event = threading.Event()
        self.reqManagedAccts_event = threading.Event()
        self.reqAccountSummary_event = threading.Event()
        self.reqPositions_event = threading.Event()
        self.reqMktData_event = threading.Event()
        self.reqHistoricalData_event = threading.Event()
        self.placeOrder_event = threading.Event()
        self.cancelOrder_event = threading.Event()
        self.reqOpenOrders_event = threading.Event()
        self.reqCompletedOrders_event = threading.Event()

    def dumpTestCoverageSituation(self):
        for clntMeth in sorted(self.clntMeth2callCount.keys()):
            if self.clntMeth2callCount[clntMeth] > 0:
                SQLog.info("ClntMeth: %-30s %6d" % (clntMeth, self.clntMeth2callCount[clntMeth]))

        for wrapMeth in sorted(self.wrapMeth2callCount.keys()):
            if self.wrapMeth2callCount[wrapMeth] > 0:
                SQLog.info("WrapMeth: %-30s %6d" % (wrapMeth, self.wrapMeth2callCount[wrapMeth]))

    def dumpReqAnsErrSituation(self):
        logging.debug("%s\t%s\t%s\t%s" % ("ReqId", "#Req", "#Ans", "#Err"))
        for reqId in sorted(self.reqId2nReq.keys()):
            nReq = self.reqId2nReq.get(reqId, 0)
            nAns = self.reqId2nAns.get(reqId, 0)
            nErr = self.reqId2nErr.get(reqId, 0)
            SQLog.info("%d\t%d\t%s\t%d" % (reqId, nReq, nAns, nErr))

    def stockcode_to_contract(self, stockcode):
        contract = Contract()
        scs = stockcode.split('.')
        if scs[0] == 'US':
            # STK, CASH
            contract.secType = 'STK'
            contract.symbol = scs[1]
            contract.exchange = 'SMART'
            if contract.symbol.upper() == 'MSFT':
                contract.exchange = 'ISLAND'
            contract.currency = 'USD'
        elif scs[0] == 'FX':
            contract.secType = 'CASH'
            # IDEALPRO is margin Forex. The margin will be held at the time of trading. Reverse trading is unwinding.
            # FXCONV is the real foreign exchange conversion.
            contract.exchange = 'IDEALPRO'
            contract.symbol = scs[1]
            contract.currency = scs[2]
        else:
            raise Exception("stockcode_to_contract,failed,stockcode=" + stockcode)

        return contract

    def contract_to_stockcode(self, contract):
        if contract.secType.upper() == 'STK':
            stockcode = 'US.' + contract.symbol.upper()
        elif contract.secType.upper() == 'CASH':
            stockcode = 'FX.' + contract.symbol.upper() + '.' + contract.currency.upper()
        else:
            stockcode = contract.secType.upper() + '.' + contract.exchange.upper()\
                        + '.' + contract.symbol.upper() + '.' + contract.currency.upper()
        return stockcode

    def connect_start_wait(self, ApiIP, ApiPort, clientId):
        self.connect_event.clear()
        self.connect(ApiIP, ApiPort, clientId)
        threading.Thread(target=(lambda: self.run())).start()
        self.connect_event.wait(self.EventWaitSecs)
        return self.connect_event.is_set()

    def reqManagedAccts_wait(self):
        if not self.is_ready():
            raise Exception("reqManagedAccts_wait,failed,is_ready return False")
        self.reqManagedAccts_event.clear()
        self.reqManagedAccts()
        self.reqManagedAccts_event.wait(self.EventWaitSecs)
        return self.reqManagedAccts_event.is_set()

    def reqAccountSummary_wait(self):
        if not self.is_ready():
            raise Exception("reqAccountSummary_wait,failed,is_ready return False")
        self.reqAccountSummary_event.clear()
        self.reqAccountSummary(9001, "All", ",".join(("$LEDGER:USD", AccountSummaryTags.TotalCashValue, AccountSummaryTags.BuyingPower)))
        self.reqAccountSummary_event.wait(self.EventWaitSecs)
        return self.reqAccountSummary_event.is_set()

    def reqPositions_wait(self):
        if not self.is_ready():
            raise Exception("reqPositions_wait,failed,is_ready return False")
        self.position_dict.clear()
        self.reqPositions_event.clear()
        self.reqPositions()
        self.reqPositions_event.wait(self.EventWaitSecs)
        return self.reqPositions_event.is_set()

    def subscribeMktData(self, stockcode):
        if not self.is_ready():
            raise Exception("subscribeMktData,failed,is_ready return False")

        contract = self.stockcode_to_contract(stockcode)
        reqId = self.nextOrderId()
        self.reqMktData_Id2code[reqId] = stockcode
        self.reqMktData(reqId, contract, "", False, False, [])

    def reqMktData_wait(self, stockcodes):
        if not self.is_ready():
            raise Exception("reqMktData_wait,failed,is_ready return False")
        SQLog.info("reqMktData_wait,stockcodes=", stockcodes)
        self.reqMktData_event.clear()
        self.reqMktData_waitids.clear()
        for code in stockcodes:
            contract = self.stockcode_to_contract(code)
            reqId = self.nextOrderId()
            self.reqMktData_Id2code[reqId] = code
            self.reqMktData_waitids.add(reqId)
            self.reqMktData(reqId, contract, "", True, False, [])

        self.reqMktData_event.wait(self.EventWaitSecs)
        return self.reqMktData_event.is_set()

    def reqHistoricalData_wait(self, stockcode):
        if not self.is_ready():
            raise Exception("reqHistoricalData_wait,failed,is_ready return False")
        SQLog.info("reqHistoricalData_wait,stockcode=", stockcode)

        self.historical_bars[stockcode] = []
        self.reqHistoricalData_event.clear()
        reqId = self.nextOrderId()
        self.reqHistoricalData_Id2code[reqId] = stockcode
        contract = self.stockcode_to_contract(stockcode)
        queryTime = (datetime.datetime.today() - datetime.timedelta(days=30)).strftime("%Y%m%d %H:%M:%S")
        self.reqHistoricalData(reqId, contract, queryTime,
                               "1 D", "1 day", "TRADES", 1, 1, False, [])
        self.reqHistoricalData_event.wait(self.EventWaitSecs)
        return self.reqHistoricalData_event.is_set()

    def placeOrder_wait(self, stockcode, volume, price, isbuy, ismarketorder):
        if not self.is_ready():
            raise Exception("placeOrder_wait,failed,is_ready return False")

        contract = self.stockcode_to_contract(stockcode)

        order = Order()
        order.account = self.account
        order.action = 'BUY' if isbuy else 'SELL'
        order.orderType = 'MKT' if ismarketorder else 'LMT'
        order.totalQuantity = volume
        if not ismarketorder:
            order.lmtPrice = price

        orderId = self.nextOrderId()

        self.placeOrder_waitid = orderId
        self.placeOrder_event.clear()
        self.placeOrder(orderId, contract, order)
        self.placeOrder_event.wait(self.EventWaitSecs)
        if self.placeOrder_event.is_set():
            return orderId
        else:
            self.reqOpenOrders_wait()
            self.placeOrder_event.wait(self.EventWaitSecs)
            if self.placeOrder_event.is_set():
                return orderId
            return None

    def cancelOrder_wait(self, orderId):
        if not self.is_ready():
            raise Exception("cancelOrder_wait,failed,is_ready return False")
        self.cancelOrder_waitid = orderId
        self.cancelOrder_event.clear()
        self.cancelOrder(orderId)
        self.cancelOrder_event.wait(self.EventWaitSecs)
        return self.cancelOrder_event.is_set()

    def reqOpenOrders_wait(self):
        if not self.is_ready():
            raise Exception("reqOpenOrders_wait,failed,is_ready return False")
        self.reqOpenOrders_event.clear()
        self.reqOpenOrders()
        self.reqOpenOrders_event.wait(self.EventWaitSecs)
        return self.reqOpenOrders_event.is_set()

    def reqCompletedOrders_wait(self):
        # note: in method "completedOrder", order.orderId is always 0, so "reqCompletedOrders_wait" maybe no use.

        #if not self.is_ready():
        #    raise Exception("reqCompletedOrders_wait,failed,is_ready return False")
        #self.reqCompletedOrders_event.clear()
        #self.reqCompletedOrders(True)
        #self.reqCompletedOrders_event.wait(self.EventWaitSecs)
        #return self.reqCompletedOrders_event.is_set()
        return True

    def is_ready(self):
        return self.isConnected() and not self.nextValidOrderId is None

    def stop(self):
        self.nextValidOrderId = None
        self.done = True
        self.disconnect()

    def nextOrderId(self):
        oid = self.nextValidOrderId
        self.nextValidOrderId += 1
        return oid

    @iswrapper
    def connectAck(self):
        super().connectAck()
        if self.asynchronous:
            self.startApi()
        SQLog.info("IBAgent.connectAck")

    @iswrapper
    def connectionClosed(self):
        super().connectionClosed()
        SQLog.info("IBAgent.connectionClosed")
        self._trade_engine.connection_closed()

    @iswrapper
    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.nextValidOrderId = orderId
        SQLog.info("IBAgent.nextValidId,orderId=", orderId)
        self.connect_event.set()

    @iswrapper
    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        super().error(reqId, errorCode, errorString)
        self.reqId2nErr[reqId] += 1
        SQLog.info("IBAgent.error,reqId=", reqId, "errorCode=", errorCode, "errorString=", errorString)
        if self.cancelOrder_waitid == reqId and errorCode == 10147:
            self._trade_engine.order_handler(reqId, None, True, None, None, None, None, None)
            self.cancelOrder_event.set()

    @iswrapper
    def winError(self, text: str, lastError: int):
        super().winError(text, lastError)
        SQLog.info("IBAgent.winError,lastError=", lastError, "text=", text)

    @iswrapper
    def managedAccounts(self, accountsList: str):
        super().managedAccounts(accountsList)
        self.account = accountsList.split(",")[0]
        SQLog.info("managedAccounts")
        self.reqManagedAccts_event.set()

    @iswrapper
    def accountSummary(self, reqId: int, account: str, tag: str, value: str,
                       currency: str):
        super().accountSummary(reqId, account, tag, value, currency)
        if 'TotalCashBalance' == tag and 'USD' == currency:
            self.total_cash_balance = float(value)
        if 'TotalCashValue' == tag and 'USD' == currency:
            self.total_cash_value = float(value)
        if AccountSummaryTags.BuyingPower == tag and 'USD' == currency:
            self.buying_power = float(value)
        if 'StockMarketValue' == tag and 'USD' == currency:
            self.stock_market_value = float(value)

    @iswrapper
    def accountSummaryEnd(self, reqId: int):
        super().accountSummaryEnd(reqId)
        SQLog.info("accountSummaryEnd")
        self.reqAccountSummary_event.set()

    @iswrapper
    def position(self, account: str, contract: Contract, position: float,
                 avgCost: float):
        super().position(account, contract, position, avgCost)
        stockcode = self.contract_to_stockcode(contract)
        if not stockcode is None:
            if stockcode not in self.position_dict:
                self.position_dict[stockcode] = {}
            p = self.position_dict[stockcode]
            p['qty'] = position
            p['cost_price'] = avgCost
            p['cost_price_valid'] = True

    @iswrapper
    def positionEnd(self):
        super().positionEnd()
        SQLog.info("positionEnd")
        self.reqPositions_event.set()

    @iswrapper
    def marketDataType(self, reqId: TickerId, marketDataType: int):
        super().marketDataType(reqId, marketDataType)
        SQLog.info("marketDataType,reqId=", reqId, "marketDataType=", marketDataType)

    @iswrapper
    def tickPrice(self, reqId: TickerId, tickType: TickType, price: float,
                  attrib: TickAttrib):
        super().tickPrice(reqId, tickType, price, attrib)
        SQLog.debug("tickPrice,reqId=", reqId, "tickType=", tickType, "price=", price)
        stockcode = self.reqMktData_Id2code[reqId]
        if price > 0 and not stockcode is None:
            quotes_dict = self._trade_engine.get_quotes_dict()
            if stockcode not in quotes_dict:
                quotes_dict[stockcode] = {}
            d = quotes_dict[stockcode]
            if tickType == TickTypeEnum.LAST or tickType == TickTypeEnum.DELAYED_LAST:
                d['last_price'] = price
            if tickType == TickTypeEnum.BID or tickType == TickTypeEnum.DELAYED_BID:
                d['bid_price'] = price
            if tickType == TickTypeEnum.ASK or tickType == TickTypeEnum.DELAYED_ASK:
                d['ask_price'] = price
            if tickType == TickTypeEnum.CLOSE or tickType == TickTypeEnum.DELAYED_CLOSE:
                d['close_price'] = price

    @iswrapper
    def tickSnapshotEnd(self, reqId: int):
        super().tickSnapshotEnd(reqId)
        SQLog.info("TickSnapshotEnd. TickerId:", reqId, "waitids=", self.reqMktData_waitids)
        self.reqMktData_waitids.remove(reqId)
        if len(self.reqMktData_waitids) == 0:
            SQLog.info("tickSnapshotEnd,reqMktData_event.set")
            self.reqMktData_event.set()

    @iswrapper
    def historicalData(self, reqId:int, bar: BarData):
        super().historicalData(reqId, bar)
        stockcode = self.reqHistoricalData_Id2code[reqId]
        SQLog.info("historicalData,reqId=", reqId, "stockcode=", stockcode, "bar=", bar)
        if not stockcode is None:
            if stockcode not in self.historical_bars:
                self.historical_bars[stockcode] = []
            self.historical_bars[stockcode].append(bar)

    @iswrapper
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        super().historicalDataEnd(reqId, start, end)
        SQLog.info("historicalDataEnd,reqId=", reqId, "start=", start, "end=", end)
        self.reqHistoricalData_event.set()

    @iswrapper
    def historicalDataUpdate(self, reqId: int, bar: BarData):
        super().historicalDataUpdate(reqId, bar)
        print("HistoricalDataUpdate. ReqId:", reqId, "BarData.", bar)

    @iswrapper
    def openOrder(self, orderId: OrderId, contract: Contract, order: Order,
                  orderState: OrderState):
        super().openOrder(orderId, contract, order, orderState)
        order.orderId = orderId
        order.contract = contract
        stockcode = self.contract_to_stockcode(contract)
        self._trade_engine.order_handler(orderId, stockcode, None, order.action == 'BUY',
                                         None, None, order.totalQuantity, order.lmtPrice)

        if self.placeOrder_waitid == orderId:
            self.placeOrder_event.set()

    @iswrapper
    def openOrderEnd(self):
        super().openOrderEnd()
        SQLog.info("openOrderEnd")
        self.reqOpenOrders_event.set()

    @iswrapper
    def orderStatus(self, orderId: OrderId, status: str, filled: float,
                    remaining: float, avgFillPrice: float, permId: int,
                    parentId: int, lastFillPrice: float, clientId: int,
                    whyHeld: str, mktCapPrice: float):
        super().orderStatus(orderId, status, filled, remaining,
                            avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        isclose = 'Filled' == status or 'Cancelled' == status or abs(remaining) < 0.01
        self._trade_engine.order_handler(orderId, None, isclose, None, avgFillPrice, filled, None, None)
        if self.cancelOrder_waitid == orderId and isclose:
            self.cancelOrder_event.set()

    @iswrapper
    def completedOrder(self, contract: Contract, order: Order,
                       orderState: OrderState):
        super().completedOrder(contract, order, orderState)
        stockcode = self.contract_to_stockcode(contract)
        # note: order.orderId here is always 0
        self._trade_engine.order_handler(order.orderId, stockcode,
                                         'Filled' == orderState.status or 'Cancelled' == orderState.status,
                                         order.action == 'BUY', None, order.filledQuantity,
                                         order.totalQuantity, order.lmtPrice)
        if self.placeOrder_waitid == order.orderId:
            self.placeOrder_event.set()

    @iswrapper
    def completedOrdersEnd(self):
        super().completedOrdersEnd()
        SQLog.info("completedOrdersEnd")
        self.reqCompletedOrders_event.set()


class TradeEngineIb(TradeEngineBase):

    def __init__(self, marketname):
        super().__init__(marketname)

        self._ib_agent = None

        # variables which start with uppercase letter may have configuration in setting.json
        self.ApiIP = '127.0.0.1'
        self.ApiPort = None
        self.HasStreamingQuote = 0
        self.HasHistoricalPermission = 0
        self.UseMargin = 0
        self.MarginLeverage = 0

        self._lasttime_dump = 0

        # variables which start with uppercase letter may have configuration in setting.json
        self.load_setting()

        SQLog.info("__init__,marketname=", marketname, "self.__dict__=", self.__dict__)

    def open_api(self):
        SQLog.info("open_api,already open=", self._ib_agent and self._ib_agent.isConnected())
        if self._ib_agent and self._ib_agent.isConnected():
            return True

        self._ib_agent = IBAgent(self)
        if self._ib_agent.connect_start_wait(self.ApiIP, self.ApiPort, 0):
            self._ib_agent.reqManagedAccts_wait()
            self.call_get_account()
            self._ib_agent.reqMarketDataType(MarketDataTypeEnum.DELAYED_FROZEN)
            if not self._ib_agent.reqMktData_wait(self.get_stockcode_pools_forquotes()):
                SQLog.warn("open_api warning,reqMktData_wait timeout")
                #raise Exception("open_api failed,reqMktData_wait timeout")
            for code in self.get_stockcode_pools_forquotes():
                self._ib_agent.subscribeMktData(code)
        else:
            self._ib_agent = None
            raise Exception("open_api failed,connect timeout")
        SQLog.info("open_api,is_ready=", self._ib_agent.is_ready(), "ib serverVersion=",
                   self._ib_agent.serverVersion(), "ib connectionTime=", self._ib_agent.twsConnectionTime())
        super().open_api()
        return True

    def close_api(self):
        if self._ib_agent and self._ib_agent.isConnected():
            self._ib_agent.stop()
        SQLog.info("close_api")
        if time.time() - self._lasttime_dump < 3600 * 17:
            SQLog.info("close_api,too frequently dump,now=", time.time(), "lasttime=", self._lasttime_dump)
        else:
            self._lasttime_dump = time.time()
            self._ib_agent.dumpTestCoverageSituation()
            self._ib_agent.dumpReqAnsErrSituation()
        super().close_api()
        self._ib_agent = None
        return True

    def is_open(self):
        return self._ib_agent and self._ib_agent.isConnected()

    def secs_toopen(self):
        return super().secs_toopen()

    def secs_to_preopen_end(self):
        return self.secs_to_preopen_end_us()

    def secs_to_afterhours_end(self):
        return self.secs_to_afterhours_end_us()

    def has_preopen(self):
        return True

    def isnow_can_placeorder_usstk(self):
        ret = False
        tz = pytz.timezone('Etc/GMT+5')
        now = datetime.datetime.now(tz)
        is_summer_now = self.is_summer_time(now)
        if now.weekday() < 5:
            if is_summer_now:
                ret = now.hour >= 3 and now.hour < 15
            else:
                ret = now.hour >= 4 and now.hour < 16
        SQLog.info("TradeEngineIb.isnow_can_placeorder_usstk,ret=", ret)
        return ret

    def call_isnow_can_placeorder(self, stockcode=None):
        return super().call_isnow_can_placeorder(stockcode)

    def call_isnow_continuous_bidding(self, stockcode=None):
        return super().call_isnow_continuous_bidding(stockcode)

    def call_get_account(self):
        if self._ib_agent.reqAccountSummary_wait():
            with self.account_lock:
                self.nowasserts_total = self._ib_agent.total_cash_value + self._ib_agent.stock_market_value
                leverage = self.MarginLeverage
                if 0 == leverage:
                    leverage = (self._ib_agent.buying_power + self._ib_agent.stock_market_value) / self.nowasserts_total
                if self.UseMargin and leverage > 1:
                    self.nowbalance = self._ib_agent.total_cash_balance + (leverage-1)*self.nowasserts_total
                    self.nowpower = min(self.nowbalance, self._ib_agent.buying_power)
                else:
                    self.nowbalance = self._ib_agent.total_cash_balance
                    self.nowpower = min(self.nowbalance, self._ib_agent.buying_power)
                SQLog.info("call_get_account,nowbalance=", self.nowbalance, "nowpower=", self.nowpower,
                           "nowasserts_total=", self.nowasserts_total, "engine buying_power=", self._ib_agent.buying_power)
        else:
            raise Exception("call_get_account failed,reqAccountSummary_wait timeout")

        if self._ib_agent.reqPositions_wait():
            with self.account_lock:
                self.nowstocks_dict = self._ib_agent.position_dict.copy()
                SQLog.info("call_get_account,nowstocks_dict=", self.nowstocks_dict)
        else:
            raise Exception("call_get_account failed,reqPositions_wait timeout")
        return [True, self.nowbalance, self.nowstocks_dict]

    def call_resolve_dealtsum(self):
        self._ib_agent.reqOpenOrders_wait()
        self._ib_agent.reqCompletedOrders_wait()
        self.resolve_dealtsum()
        SQLog.info("call_resolve_dealtsum,ret=True")
        return True

    def call_get_market_snapshot(self, stockcodes):
        if not self.HasStreamingQuote:
            if not self._ib_agent.reqMktData_wait(stockcodes):
                SQLog.warn("call_get_market_snapshot warning,reqMktData_wait timeout")
                return [False, self.quotes_dict]

        for code in stockcodes:
            q = self.quotes_dict.get(code)
            if not q:
                continue
            bid_price = q.get('bid_price', 0)
            ask_price = q.get('ask_price', 0)
            last_price = q.get('last_price', 0)
            close_price = q.get('close_price', 0)
            if bid_price > 0.01 and ask_price > 0.01 and (not last_price or last_price < bid_price or last_price > ask_price):
                q['last_price'] = round(0.5 * (ask_price + bid_price), self.precision(code))
            if not last_price and close_price > 0.01:
                q['last_price'] = close_price
        SQLog.info("call_get_market_snapshot,quotes_dict=", self.quotes_dict)
        return [True, self.quotes_dict]

    def call_get_average_volatility(self, stockcode):
        if not self.HasHistoricalPermission:
            SQLog.info("call_get_average_volatility,stockcode=", stockcode, "average=0,volatility=0")
            return [0, 0]

        if self._ib_agent.reqHistoricalData_wait(stockcode):
            bars = self._ib_agent.historical_bars.get(stockcode, [])

            if len(bars) > 5:
                sumcloses = 0.0
                for i in range(len(bars)):
                    sumcloses += bars[i].close
                average = round(sumcloses / len(bars), self.precision(stockcode))

                #use the latest 5 days data is more prefered
                sumv = 0
                for i in range(-1, -len(bars), -1):
                    sumv += abs(bars[i].high / bars[i].low - 1) if bars[i].low > 0 else 0
                    sumv += abs(bars[i].close / bars[i-1].close - 1) if bars[i-1].close > 0 else 0
                volatility = round(sumv / (2*len(bars)), 6)
                SQLog.info("call_get_average_volatility,stockcode=", stockcode, "average=", average, "volatility=", volatility)
                return [average, volatility]
            else:
                SQLog.warn("call_get_average_volatility,bars too small,stockcode=", stockcode, "bars=", bars)
                return [0, 0]
        else:
            SQLog.warn("call_get_average_volatility,reqHistoricalData_wait fail,stockcode=", stockcode)
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

        orderId = self._ib_agent.placeOrder_wait(stockcode, volume_v, price_v, isbuy, ismarketorder)
        if orderId:
            if isbuy:
                self.nowpower -= (volume_v * price_v * self.MaxFees)
            SQLog.info("call_place_order,stockcode=", stockcode,
                       "volume=", volume, "volume_v=", volume_v, "price=", price, "price_v=", price_v,
                       "isbuy=", isbuy, "ismarketorder=", ismarketorder, "orderid=", orderId)
            SQLog.info("--------------------PlaceOrderOK--------------------", stockcode, "--------------------",
                       'BUY' if isbuy else 'SELL', volume_v, '@ ', 'MKT' if ismarketorder else price_v,
                       "--------------------", orderId)
            self.order_handler(orderId, stockcode, None, isbuy, None, None, volume_v, price_v)
        else:
            raise Exception("call_place_order failed,timeout,stockcode=" + stockcode + ",volume=" + str(volume)
                            + ",price=" + str(price) + ",isbuy=" + str(isbuy) + ",ismarketorder=" + str(ismarketorder))
        return orderId

    def call_get_order(self, orderid):
        if orderid is None:
            SQLog.info("call_get_order,orderid=", orderid, "order=None")
            return None
        if self._ib_agent.reqOpenOrders_wait() and self._ib_agent.reqCompletedOrders_wait():
            order = self.get_order_from_cache(orderid)
            SQLog.info("call_get_order,orderid=", orderid, "order=", order)
            return order
        else:
            raise Exception("call_get_order failed,timeout,orderid=" + str(orderid))

    def call_list_order(self):
        content = ""
        orders = self.get_orders_notclose()
        for (orderid, order) in orders.items():
            isclose = order.get('isclose')
            if not isclose:
                content += "\n\torderid=" + str(orderid) + ",order=" + str(order)
        SQLog.info("call_list_order,orders=", content)
        return True

    def call_cancel_order(self, orderid):
        if orderid is None:
            SQLog.info("call_cancel_order,orderid=", orderid, "return False")
            return False

        if self._ib_agent.cancelOrder_wait(orderid):
            SQLog.info("call_cancel_order,orderid=", orderid)
            return True
        else:
            order = self.get_order_from_cache(orderid)
            if order and order.get('isclose'):
                SQLog.info("call_cancel_order,orderid=", orderid)
            else:
                SQLog.info("call_cancel_order,orderid=", orderid, ",timeout")

    def call_cancel_all_orders(self):
        self._ib_agent.reqGlobalCancel()
        SQLog.info("call_cancel_all_orders")
        return True


if __name__ == '__main__':
    args = SunquantFrame.getargs('ib-sun', 'shannon')

    #SQLog.setup_root_logger(args.market, args.strategy+'-debug', 'info', 'debug', 0, 1)
    SQLog.setup_root_logger(args.market, args.strategy+'-debug', 'info', 'info', 0, 1)
    SQLog.init_default(args.market, args.strategy, 'info', 'info', 1, 1)

    engine = TradeEngineIb(args.market)
    frame = SunquantFrame(engine, args.market, args.strategy)
    engine.set_frame(frame)
    if SunquantFrame.doargs(args, engine):
        exit(0)

    SQLog.init_default(args.market, args.strategy, 'info', 'info', 1 if platform.system() == "Windows" else 0, 1)
    frame.monitor_run()
    exit(0)
