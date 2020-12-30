# encoding: UTF-8
# author email: szy@tsinghua.org.cn

import random

from utils.sq_log import *
from utils.sq_setting import *


class GridStrategy(object):
    _ktable = (0,
            0.005932, 0.011865, 0.017799, 0.023735, 0.029672, 0.035609, 0.041546, 0.047484, 0.053421, 0.059358,
            0.065294, 0.071230, 0.077163, 0.083096, 0.089027, 0.094955, 0.100882, 0.106805, 0.112726, 0.118644,
            0.124559, 0.130470, 0.136377, 0.142281, 0.148180, 0.154074, 0.159964, 0.165849, 0.171728, 0.177603,
            0.183471, 0.189333, 0.195190, 0.201040, 0.206883, 0.212720, 0.218549, 0.224371, 0.230186, 0.235993,
            0.241793, 0.247584, 0.253367, 0.259141, 0.264907, 0.270663, 0.276411, 0.282149, 0.287878, 0.293598,
            0.299307, 0.305006, 0.310696, 0.316374, 0.322043, 0.327700, 0.333347, 0.338983, 0.344607, 0.350220,
            0.355822, 0.361411, 0.366990, 0.372556, 0.378110, 0.383651, 0.389181, 0.394698, 0.400202, 0.405693,
            0.411172, 0.416637, 0.422090, 0.427529, 0.432954, 0.438367, 0.443765, 0.449150, 0.454522, 0.459879,
            0.465222, 0.470552, 0.475867, 0.481168, 0.486455, 0.491727, 0.496985, 0.502228, 0.507457, 0.512671,
            0.517870, 0.523055, 0.528224, 0.533379, 0.538519, 0.543644, 0.548754, 0.553849, 0.558929, 0.563994,
            0.569043, 0.574078, 0.579097, 0.584101, 0.589090, 0.594063, 0.599022, 0.603965, 0.608892, 0.613805,
            0.618702, 0.623584, 0.628451, 0.633302, 0.638138, 0.642959, 0.647765, 0.652556, 0.657331, 0.662091,
            0.666837, 0.671567, 0.676282, 0.680982, 0.685667, 0.690337, 0.694992, 0.699633, 0.704258, 0.708869,
            0.713465, 0.718047, 0.722614, 0.727167, 0.731705, 0.736228, 0.740738, 0.745233, 0.749714, 0.754180,
            0.758633, 0.763072, 0.767497, 0.771908, 0.776305, 0.780689, 0.785059, 0.789416, 0.793759, 0.798090,
            0.802406, 0.806710, 0.811001, 0.815279, 0.819544, 0.823796, 0.828036, 0.832263, 0.836478, 0.840681,
            0.844871, 0.849050, 0.853216, 0.857370, 0.861513, 0.865644, 0.869763, 0.873871, 0.877968, 0.882054,
            0.886128, 0.890191, 0.894244, 0.898286, 0.902317, 0.906338, 0.910348, 0.914348, 0.918338, 0.922318,
            0.926288, 0.930249, 0.934199, 0.938140, 0.942072, 0.945994, 0.949907, 0.953812, 0.957707, 0.961593,
            0.965471, 0.969340, 0.973201, 0.977053, 0.980897, 0.984734, 0.988562, 0.992382, 0.996195, 1.000000)

    TYPE_NORMAL = 'Normal'
    TYPE_KTABLE = 'KTable'
    TYPE_GEO = 'Geo'
    TYPE_ARITH = 'Arith'
    TYPE_GEOARITH = 'GeoArith'
    TYPE_BLIND = 'Blind'
    GRID_TYPES = [TYPE_NORMAL, TYPE_KTABLE, TYPE_GEO, TYPE_ARITH, TYPE_GEOARITH, TYPE_BLIND]
    GRID_TYPES_NOBAND = [TYPE_GEO, TYPE_GEOARITH, TYPE_BLIND]

    def __init__(self, stockcode, marketname, strategyname, invest_total, midprice_auto, volatility):
        # variables which start with uppercase letter may have configuration in setting.json
        self.GridCount = 10
        self.GridMinPrice = 300
        self.GridMaxPrice = 500
        self.GridType = self.TYPE_NORMAL
        self.GeoRatio = 0.6
        self.ArithDelta = -0.12
        self.NeedRePosition = False
        self.MaxFees = 1.000
        self.PricePrecision = 2
        self.Invest = None
        self.InvestRatio = None
        self.StartPrice = None
        self.MidPrice = None
        self.SelfAdaptionMP = 1
        self.MidPriceMaxDeviation = 5.0
        self.SelfAdaptionT = 1

        self._gridCursor = 0
        self._gridStep = 0
        self._gridLastDealPrice = 0
        self._initprice = 0
        self._initbalance = 0
        self._initstocks = 0
        self._nowbalance = 0
        self._nowstocks = 0
        self._nowprice = 0
        self._timesRePosition = 0

        self._stockcode = stockcode  # same as it is in setting.xml
        self._marketname = marketname
        self._ishalfopen = False
        self._isopen = False

        SQSetting.fill_dict_from_settings(self.__dict__, marketname + '_' + strategyname + "_" + self._stockcode)

        if not self.StartPrice:
            self.StartPrice = (self.GridMinPrice + self.GridMaxPrice) * 0.5

        if not self.MidPrice:
            self.MidPrice = (self.GridMinPrice + self.GridMaxPrice) * 0.5

        if self.SelfAdaptionMP and midprice_auto:
            if midprice_auto / self.MidPrice < 1.0 / self.MidPriceMaxDeviation:
                self.MidPrice = self.MidPrice * 1.0 / self.MidPriceMaxDeviation
            elif midprice_auto / self.MidPrice > self.MidPriceMaxDeviation:
                self.MidPrice = self.MidPrice * self.MidPriceMaxDeviation
            else:
                self.MidPrice = midprice_auto
            self.MidPrice = round(self.MidPrice * (0.999 + 0.002*random.random()), self.PricePrecision)
            dev = self.GridMaxPrice - self.GridMinPrice
            self.GridMinPrice = self.MidPrice - dev * 0.5
            self.GridMaxPrice = self.MidPrice + dev * 0.5

        if self.SelfAdaptionT and volatility:
            self.GridCount = max(2, round((self.GridMaxPrice - self.GridMinPrice) / (self.MidPrice * volatility * 2 * 0.618*0.618*0.618)))

        if not self.Invest:
            self.Invest = invest_total * self.InvestRatio

        if self.GridType not in self.GRID_TYPES:
            raise Exception("__init__:GridType not supported,stockcode="+self._stockcode+"GridType="+self.GridType)
        SQLog.info("__init__:", self._stockcode, "marketname=", marketname, "strategyname=", strategyname,
                   "invest_total=", invest_total, "self.__dict__=", self.__dict__)

    def is_open(self):
        return self._isopen

    def is_halfopen(self):
        return self._ishalfopen

    def get_invest(self):
        return self.Invest

    def get_investratio(self):
        return self.InvestRatio

    def get_nowbalance(self):
        return self._nowbalance

    def get_nowstocks(self):
        return self._nowstocks

    def get_nowprice(self):
        return self._nowprice

    def get_startprice(self):
        return self.StartPrice

    def __get_ktable_weight_balance(self, cursor):
        step = round(len(self._ktable) / (0.5 * self.GridCount))
        if step < 1:
            step = 1
        if step >= len(self._ktable):
            step = len(self._ktable)-1
        gnow = round(cursor - 0.5 * self.GridCount)
        gnowabs = abs(gnow)
        w = 0
        if gnowabs * step < len(self._ktable):
            w = self._ktable[gnowabs * step]
        else:
            w = self._ktable[-1]
        if gnow < 0:
            return (1 - w) / 2
        else:
            return (1 + w) / 2

    def __get_geo_weight_balance(self, cursor):
        weight = 1.0 * cursor / self.GridCount
        georatio = self.GeoRatio * 0.5 * self.GridCount
        if georatio > 1:
            gcur = round(cursor - 0.5 * self.GridCount)
            geo = 0.5
            weight = geo
            i = 0
            while i < gcur:
                weight += geo / georatio
                geo = geo * (georatio-1) / georatio
                i += 1
            i = gcur
            while i < 0:
                weight -= geo / georatio
                geo = geo * (georatio-1) / georatio
                i += 1
        return weight

    def __get_arith_weight_balance(self, cursor):
        high = 0.5 * self.GridCount
        sum_weight = 2 * 0.5 * (1 + self.ArithDelta + (1 + high * self.ArithDelta)) * high

        gnow = cursor - 0.5 * self.GridCount
        tri = 0.5 * (1 + self.ArithDelta + (1 + abs(gnow) * self.ArithDelta)) * gnow
        w = (0.5 * sum_weight + tri) / sum_weight
        return w

    def __get_arithgeo_weight_balance(self, cursor):
        if cursor >= self.GridCount/6 and cursor <= 5 * self.GridCount/6:
            return self.__get_arith_weight_balance(cursor)
        else:
            return self.__get_geo_weight_balance(cursor)

    def __get_want_balance(self, cursor, totalValue):
        wantBalance = totalValue * cursor / self.GridCount
        if self.GridType == self.TYPE_KTABLE:
            wantBalance = totalValue * self.__get_ktable_weight_balance(cursor)
        elif self.GridType == self.TYPE_GEOARITH:
            wantBalance = totalValue * self.__get_arithgeo_weight_balance(cursor)
        elif self.GridType == self.TYPE_GEO:
            wantBalance = totalValue * self.__get_geo_weight_balance(cursor)
        elif self.GridType == self.TYPE_ARITH:
            wantBalance = totalValue * self.__get_arith_weight_balance(cursor)
        elif self.GridType == self.TYPE_BLIND:
            diff = cursor - self._gridCursor
            wantBalance = self._nowbalance + diff * totalValue/self.GridCount
        return wantBalance

    def __re_position(self, lastprice):
        if not self.NeedRePosition:
            return False
        if self.GridType in self.GRID_TYPES_NOBAND:
            return False
        if self._gridCursor > 0 and self._gridCursor < self.GridCount:
            return False

        if lastprice < self.GridMinPrice - self._gridStep:
            self.GridMinPrice = self.GridMinPrice-self._gridStep
            self.GridMaxPrice = self.GridMinPrice + self.GridCount * self._gridStep
            self._gridCursor = 0
            self._gridLastDealPrice = self.GridMinPrice
            self._timesRePosition += 1
            SQLog.info("__re_position:", self._stockcode, "_gridCursor=", self._gridCursor, "/", self.GridCount,
                       "_gridLastDealPrice=", self._gridLastDealPrice,
                       "GridMinPrice=", self.GridMinPrice, "GridMaxPrice=", self.GridMaxPrice,
                       "_timesRePositoin=", self._timesRePosition, "initprice=", self._initprice, "lastprice=", lastprice)
            return True

        if lastprice > self.GridMaxPrice + self._gridStep:
            self.GridMaxPrice = self.GridMaxPrice + self._gridStep
            self.GridMinPrice = self.GridMaxPrice - self.GridCount * self._gridStep
            self._gridCursor = self.GridCount
            self._gridLastDealPrice = self.GridMaxPrice
            self._timesRePosition += 1
            SQLog.info("__re_position:", self._stockcode, "_gridCursor=", self._gridCursor, "/", self.GridCount,
                       "_gridLastDealPrice=", self._gridLastDealPrice,
                       "GridMinPrice=", self.GridMinPrice, "GridMaxPrice=", self.GridMaxPrice,
                       "_timesRePositoin=", self._timesRePosition, "initprice=", self._initprice, "lastprice=", lastprice)
            return True
        return False

    def open(self, lastprice, nowbalance, nowstocks):
        if self._isopen:
            SQLog.error("open:already opened,", self._stockcode)
            return nowbalance
        if self.GridCount < 1:
            SQLog.error("open:GridCount<1,", self._stockcode)
            return nowbalance
        if lastprice == 0:
            self._ishalfopen = True
            self._nowbalance = nowbalance
            self._nowstocks = nowstocks
            self._nowprice = lastprice
            SQLog.warn("open:halfopen,", self._stockcode, "lastprice=", lastprice,
                       "nowbalance=", nowbalance, "nowstocks=", nowstocks)
            return nowbalance

        self._ishalfopen = False

        self._initprice = lastprice
        self._initbalance = nowbalance
        self._initstocks = nowstocks
        self._nowbalance = nowbalance
        self._nowstocks = nowstocks
        self._nowprice = lastprice

        self._gridStep = (self.GridMaxPrice - self.GridMinPrice) / self.GridCount

        self._gridCursor = int(round((lastprice - self.GridMinPrice) / self._gridStep))
        if not (self.GridType in self.GRID_TYPES_NOBAND):
            if self._gridCursor < 0:
                self._gridCursor = 0
            if self._gridCursor > self.GridCount:
                self._gridCursor = self.GridCount

        self._gridLastDealPrice = self.GridMinPrice + self._gridCursor * self._gridStep

        lastDealValue = nowbalance + self._gridLastDealPrice * nowstocks
        wantBalance = self.__get_want_balance(self._gridCursor, lastDealValue)
        balance_step = lastDealValue / self.GridCount
        if self._gridCursor > 0 and 0.5 * balance_step < wantBalance - nowbalance < 1.5 * balance_step:
            wantBalance -= balance_step
            self._gridCursor -= 1
        elif self._gridCursor < self.GridCount and -1.5 * balance_step < wantBalance - nowbalance < -0.5 * balance_step:
            wantBalance += balance_step
            self._gridCursor += 1

        openValue = self._initbalance + self._initstocks * self._initprice
        SQLog.info("open:", self._stockcode, "openValue=", openValue, "_initbalance=", self._initbalance,
                   "wantBalance=", wantBalance, "_initprice=", self._initprice, "_initstocks=", self._initstocks,
                   "_gridCursor=", self._gridCursor, "_gridStep=", self._gridStep,
                   "_gridLastDealPrice=", self._gridLastDealPrice)
        self._isopen = True
        return wantBalance

    def close(self):
        self._isopen = False
        self._ishalfopen = False
        SQLog.info("close:", self._stockcode)

    def begin_transact(self, lastprice, nowbalance, nowstocks, bidprice, askprice, spread, minstocks, forcelurker, blind):
        needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume = 0, 0, 0, 0, 0, 0

        if abs(nowbalance - self._nowbalance) > 1 or abs(nowstocks - self._nowstocks) > 0.5:
            SQLog.warn("begin_transact:nowbalance or nowstocks not match,", self._stockcode, "lastprice=", lastprice,
                       "nowbalance=", nowbalance, "nowstocks=", nowstocks, "self._nowbalance=", self._nowbalance,
                       "self._nowstocks=", self._nowstocks, "_isopen=", self._isopen)
            self.end_transact(lastprice, nowbalance - self._nowbalance, nowstocks - self._nowstocks, 0, lastprice, minstocks)
            return [needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume]
        if 0 == lastprice or (0 == nowbalance and 0 == nowstocks) or not self._isopen:
            SQLog.error("begin_transact:something wrong,", self._stockcode, "lastprice=", lastprice,
                        "nowbalance=", nowbalance, "nowstocks=", nowstocks, "_isopen=", self._isopen)
            return [needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume]

        self._nowbalance = nowbalance
        self._nowstocks = nowstocks
        self._nowprice = lastprice

        self.__re_position(lastprice)

        higher = self.GridMinPrice + self._gridCursor * self._gridStep + self._gridStep
        lower  = self.GridMinPrice + self._gridCursor * self._gridStep - self._gridStep

        lowerValue = nowbalance + nowstocks * lower
        higherValue = nowbalance + nowstocks * higher
        nowValue = nowbalance + nowstocks * lastprice
        balance_step = nowValue / self.GridCount

        if self._gridCursor > 0 or self.GridType in self.GRID_TYPES_NOBAND:
            wantBalanceLower = self.__get_want_balance(self._gridCursor-1, lowerValue)
            buyprice = lower
            buyvolume = min((nowbalance - wantBalanceLower)/(self.MaxFees * buyprice),
                            nowbalance/(self.MaxFees * buyprice), 2*balance_step/buyprice)
            needbuy = buyvolume > 0
        if self._gridCursor < self.GridCount or self.GridType in self.GRID_TYPES_NOBAND:
            wantBalanceHigher = self.__get_want_balance(self._gridCursor+1, higherValue)
            sellprice = higher
            sellvolume = min((wantBalanceHigher - nowbalance) / sellprice,
                             nowstocks, 2*balance_step/sellprice)
            needsell = sellvolume > 0

        if needbuy or needsell:
            SQLog.info("begin_transact:", self._stockcode, "profit=", nowValue/self.Invest,
                       "benchmark=", lastprice/self.StartPrice, "_gridCursor=", self._gridCursor, "/", self.GridCount,
                       "postion=", nowstocks*lastprice/nowValue, "_initprice=", self._initprice,
                       "lastprice=", lastprice, "_gridLastDealPrice=", self._gridLastDealPrice,
                       "GridMinPrice=", self.GridMinPrice, "GridMaxPrice=", self.GridMaxPrice,
                       "_timesRePositoin=", self._timesRePosition,
                       "Buy=", buyvolume if needbuy else "0", "@", buyprice,
                       "Sell=", sellvolume if needsell else "0", "@", sellprice,
                       'nowalance=', nowbalance, 'nowstocks=', nowstocks)

        return [needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume]
    
    def end_transact(self, lastprice, diffbalance, diffstocks, cursorstep, dealprice, minstocks):
        if not self._isopen:
            SQLog.error("end_transact:not opened,", self._stockcode)
            return False

        self._nowbalance = self._nowbalance + diffbalance
        self._nowstocks = self._nowstocks + diffstocks
        self._nowprice = lastprice

        if not 0 == cursorstep:
            self._gridCursor = self._gridCursor + cursorstep
            self._gridLastDealPrice = dealprice
            if not (self.GridType in self.GRID_TYPES_NOBAND):
                if self._gridCursor < 0:
                    SQLog.warn("end_transact:", self._stockcode, "_gridCursor<0,",
                               "_gridCursor=", self._gridCursor, "/", self.GridCount, "cursorstep=", cursorstep,
                               "_gridLastDealPrice=", self._gridLastDealPrice )
                    self._gridCursor = 0
                if self._gridCursor > self.GridCount:
                    SQLog.warn("end_transact:", self._stockcode, "_gridCursor>GridCount,",
                               "_gridCursor=", self._gridCursor, "/", self.GridCount, "cursorstep=", cursorstep,
                               "_gridLastDealPrice=", self._gridLastDealPrice )
                    self._gridCursor = self.GridCount

        SQLog.info("end_transact:", self._stockcode, "diffbalance=", diffbalance, "diffstocks=", diffstocks,
                   "cursorstep=", cursorstep, "dealprice=", dealprice,
                   "_gridCursor=", self._gridCursor, "/", self.GridCount)
        return True

