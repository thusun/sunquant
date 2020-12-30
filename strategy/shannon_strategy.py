# encoding: UTF-8
# author email: szy@tsinghua.org.cn

import random

from utils.sq_log import *
from utils.sq_setting import *


class ShannonStrategy(object):
    BeLurker = 0
    BeMaker = 0
    MaxWaitsecsTaker = 300
    MaxWaitsecsMaker = 600
    MaxWaitsecsLurker = 18000

    def __init__(self, stockcode, marketname, strategyname, invest_total, midprice_auto, volatility):
        # variables which start with uppercase letter may have configuration in setting.json
        self.Threshold = 0.005
        self.BasePrice = None
        self.MinPrice = None
        self.MaxPrice = None
        self.UseOptimalLeverage = False
        self.BaseLeverage = 20
        self.NeedRePosition = False
        self.MaxFees = 1.000
        self.PricePrecision = 2
        self.Invest = None
        self.InvestRatio = None
        self.StartPrice = None
        self.MidPrice = 0
        self.MidPosition = 0.5
        self.SelfAdaptionMP = 1
        self.MidPriceMaxDeviation = 5.0
        self.SelfAdaptionT = 1

        self._leverage = self.BaseLeverage
        self._initprice = 0
        self._initbalance = 0
        self._initstocks = 0
        self._nowbalance = 0
        self._nowstocks = 0
        self._nowprice = 0
        self._virtualBalance = 0
        self._virtualStocks = 0
        self._timesRePosition = 0
        self._timesReLeverage = 0
        self._timesOnTick = 0
        self._timesRatioLtThreshold = 0
        self._timesRatioMtThreshold = 0
        self._sumRatioMtThreshold = 0
        self._timesLurker = 0
        self._timesPlaceOrder = 0
        self._timesDeal = 0
        self._timesNotDeal = 0
        self._totalMoneyBuyDeal = 0
        self._totalMoneySellDeal = 0
        self._totalStocksBuyDeal = 0
        self._totalStocksSellDeal = 0

        self._stockcode = stockcode  # same as it is in setting.xml
        self._marketname = marketname
        self._ishalfopen = False
        self._isopen = False

        ps = SQSetting.part_settings(marketname + '_' + strategyname)
        ShannonStrategy.BeLurker = ps.get('BeLurker', ShannonStrategy.BeLurker)
        ShannonStrategy.BeMaker = ps.get('BeMaker', ShannonStrategy.BeMaker)
        ShannonStrategy.MaxWaitsecsTaker = ps.get('MaxWaitsecsTaker', ShannonStrategy.MaxWaitsecsTaker)
        ShannonStrategy.MaxWaitsecsMaker = ps.get('MaxWaitsecsMaker', ShannonStrategy.MaxWaitsecsMaker)
        ShannonStrategy.MaxWaitsecsLurker = ps.get('MaxWaitsecsLurker', ShannonStrategy.MaxWaitsecsLurker)
        SQSetting.fill_dict_from_settings(self.__dict__, marketname + '_' + strategyname + '_' + self._stockcode)

        if not self.StartPrice:
            self.StartPrice = self.MidPrice

        if self.SelfAdaptionMP and midprice_auto:
            if midprice_auto / self.MidPrice < 1.0 / self.MidPriceMaxDeviation:
                self.MidPrice = self.MidPrice * 1.0 / self.MidPriceMaxDeviation
            elif midprice_auto / self.MidPrice > self.MidPriceMaxDeviation:
                self.MidPrice = self.MidPrice * self.MidPriceMaxDeviation
            else:
                self.MidPrice = midprice_auto
            self.MidPrice = round(self.MidPrice * (0.999 + 0.002*random.random()), self.PricePrecision)

        if self.SelfAdaptionT and volatility:
            self.Threshold = max(self.Threshold, round(volatility*0.618*0.618*0.618, 6))

        if not self.Invest:
            self.Invest = invest_total * self.InvestRatio

        if not self.MinPrice or not self.MaxPrice:
            if (0.5 * self.BaseLeverage - (1 - self.MidPosition)) > 0 and (0.5 * self.BaseLeverage - self.MidPosition) > 0:
                self.BasePrice = round(self.MidPrice * (0.5 * self.BaseLeverage - (1 - self.MidPosition)) / (0.5 * self.BaseLeverage - self.MidPosition),
                                       self.PricePrecision)
            else:
                self.BasePrice = self.MidPrice

            if self.BaseLeverage > 2.0001:
                self.MinPrice = round(self.BasePrice * (self.BaseLeverage - 2) / self.BaseLeverage, self.PricePrecision)
                self.MaxPrice = round(self.BasePrice * self.BaseLeverage / (self.BaseLeverage - 2), self.PricePrecision)
            else:
                self.MinPrice = self.BasePrice * 0.0001
                self.MaxPrice = self.BasePrice * 10000

        if not self.BasePrice:
            self.BasePrice = round(pow(self.MinPrice * self.MaxPrice, 0.5), self.PricePrecision)

        SQLog.info("__init__:", self._stockcode, "marketname=", marketname, "strategyname=", strategyname,
                   "invest_total=", invest_total, "BeLurker=", ShannonStrategy.BeLurker,
                   "BeMaker=", ShannonStrategy.BeMaker, "MaxWaitsecsTaker=", ShannonStrategy.MaxWaitsecsTaker,
                   "MaxWaitsecsMaker=",  ShannonStrategy.MaxWaitsecsMaker,
                   "MaxWaitsecsLurker=", ShannonStrategy.MaxWaitsecsLurker,
                   "self.__dict__=", self.__dict__)

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

    def open(self, lastprice, nowbalance, nowstocks):
        if self._isopen:
            SQLog.error("open:already opened,", self._stockcode)
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

        if self.Threshold <= 0 or self.Threshold >= 1:
            SQLog.error("open:Threshold <= 0 or Threshold >= 1,reset to 0.01,", self._stockcode,
                        "Threshold=", self.Threshold)
            self.Threshold = 0.01

        if self.UseOptimalLeverage:
            if self.BasePrice <= 0 or self.MinPrice < 0 or self.MaxPrice <= 0\
                    or self.MinPrice >= self.BasePrice or self.MaxPrice <= self.BasePrice:
                SQLog.error("open:UseOptimalLeverage but Price is not set properly,", self._stockcode,
                            "BasePrice=", self.BasePrice, "MinPrice=", self.MinPrice, "MaxPrice=", self.MaxPrice)
            else:
                LMAX_minprice = 2 * self.BasePrice / (self.BasePrice - self.MinPrice)
                LMAX_maxprice = 2 * self.MaxPrice / (self.MaxPrice - self.BasePrice)
                self.BaseLeverage = min(LMAX_minprice, LMAX_maxprice)

        if self.BaseLeverage <= 0:
            SQLog.error("open:BaseLeverage <= 0,reset to 1,", self._stockcode, "BaseLeverage=", self.BaseLeverage)
            self.BaseLeverage = 1
        self._leverage = self.BaseLeverage

        Pnow = lastprice
        Pbase = self.BasePrice if self.BasePrice > 0 else Pnow
        Anow = nowbalance + nowstocks * Pnow
        B = nowbalance
        Bwant = (Pbase-0.5*self._leverage*Pbase+0.5*self._leverage*Pnow) * Anow / (Pbase+Pnow)
        self._virtualBalance = 0.5 * self._leverage * Anow + B - Bwant
        self._virtualStocks = (0.5 * self._leverage * Anow - B + Bwant) / Pnow

        openValue = self._initbalance + self._initstocks * self._initprice
        SQLog.info("open:", self._stockcode, "openValue=", openValue, "_initbalance=", self._initbalance,
                   "_initprice=", self._initprice, "_initstocks=", self._initstocks,
                   "Threshold=", self.Threshold, "BasePrice=", self.BasePrice,
                   "MinPrice=", self.MinPrice, "MaxPrice=", self.MaxPrice,
                   "UseOptimalLeverage=", self.UseOptimalLeverage, "Leverage=", self._leverage, "/", self.BaseLeverage,
                   "NeedRePosition=", self.NeedRePosition, "nowbalance=", nowbalance, "nowstocks=", nowstocks,
                   "VBalance=", self._virtualBalance, "VStocks=", self._virtualStocks,
                   "Pnow=", Pnow, "Pbase=", Pbase, "Anow=", Anow, "B=", B, "Bwant=", Bwant)

        self._isopen = True
        return Bwant

    def close(self):
        self._isopen = False
        self._ishalfopen = False
        SQLog.info("close:", self._stockcode)

    def begin_transact(self, lastprice, nowbalance, nowstocks, bidprice, askprice, spread, minstocks, forcelurker, blind):
        self._timesOnTick += 1
        needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume = 0, 0, 0, 0, 0, 0

        if abs(nowbalance - self._nowbalance) > 1 or abs(nowstocks - self._nowstocks) > 0.5:
            SQLog.warn("begin_transact:nowbalance or nowstocks not match,", self._stockcode,
                       "lastprice=", lastprice, "nowbalance=", nowbalance, "nowstocks=", nowstocks,
                       "self._nowbalance=", self._nowbalance, "self._nowstocks=", self._nowstocks,
                       "_isopen=", self._isopen)
            self.end_transact(lastprice, nowbalance - self._nowbalance, nowstocks - self._nowstocks, 0, lastprice, minstocks)
            return [needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume]
        if 0 == lastprice or (0 == nowbalance and 0 == nowstocks) or not self._isopen:
            SQLog.error("begin_transact:something wrong,", self._stockcode, "lastprice=", lastprice,
                        "nowbalance=", nowbalance, "nowstocks=", nowstocks, "_isopen=", self._isopen)
            return [needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume]

        self._nowbalance = nowbalance
        self._nowstocks = nowstocks
        self._nowprice = lastprice

        if askprice is None or askprice < 0.01:
            askprice = lastprice
        if bidprice is None or bidprice < 0.01:
            bidprice = lastprice

        priceToBuy = askprice
        priceToSell = bidprice
        if self.BeMaker or forcelurker:
            priceToBuy = bidprice+spread
            priceToSell = askprice-spread

        diffAssetBuy = 0
        diffAssetSell = 0
        ratio = 0
        if self._virtualBalance - self._virtualStocks * priceToBuy > 0:
            diffAssetBuy = 0.5 * (self._virtualBalance - self._virtualStocks * priceToBuy)
            ratio = diffAssetBuy / (0.5*(self._virtualBalance + (self._virtualStocks * priceToBuy)))
        elif self._virtualBalance - (self._virtualStocks * priceToSell) < 0:
            diffAssetSell = 0.5 * (self._virtualBalance - self._virtualStocks * priceToSell)
            ratio = diffAssetSell / (0.5*(self._virtualBalance + self._virtualStocks * priceToSell))

        lurkersign = False
        if abs(ratio) < self.Threshold or blind:
            self._timesRatioLtThreshold += 1
            if (self.BeLurker or forcelurker) and self._virtualStocks > 0 and self.Threshold < 1:
                priceToBuy = self._virtualBalance * (1-self.Threshold) / (self._virtualStocks*(1+self.Threshold))
                diffAssetBuy = self._virtualBalance * self.Threshold / (1+self.Threshold)
                priceToSell = self._virtualBalance * (1+self.Threshold) / (self._virtualStocks*(1-self.Threshold))
                diffAssetSell = - self._virtualBalance * self.Threshold / (1-self.Threshold)
                lurkersign = True
                self._timesLurker += 1
            else:
                SQLog.info("begin_transact:ratio less than Threshold,", self._stockcode,
                           "ratio=", ratio, "Threshold=", self.Threshold,
                           "lastprice=", lastprice, "priceToBuy=", priceToBuy, "priceToSell=", priceToSell,
                           "priceEquilibrium=", self._virtualBalance/self._virtualStocks if self._virtualStocks>0 else 0)
                return [needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume]
        else:
            self._timesRatioMtThreshold += 1
            self._sumRatioMtThreshold += abs(ratio)

        nowValue = nowbalance + nowstocks * lastprice
        balance_step = nowValue * 0.5 * self._leverage * self.Threshold
        buyprice_in_range = False
        sellprice_in_range = False

        if ratio > 0 or lurkersign:
            buyprice = priceToBuy
            buyvolume = min(diffAssetBuy / buyprice, nowbalance / (self.MaxFees * buyprice), 2 * balance_step / buyprice)
            buyprice_in_range = -4 * self.Threshold < (priceToBuy-lastprice)/lastprice < 0.005
            needbuy = buyvolume > 0 and buyprice_in_range
            self._timesPlaceOrder += 1

        if ratio < 0 or lurkersign:
            sellprice = priceToSell
            sellvolume = min((- diffAssetSell) / sellprice, nowstocks, 2 * balance_step / sellprice)
            sellprice_in_range = -0.005 < (priceToSell-lastprice)/lastprice < 4 * self.Threshold
            needsell = sellvolume > 0 and sellprice_in_range
            self._timesPlaceOrder += 1

        position = nowstocks * lastprice / nowValue
        vposition = self._virtualStocks * lastprice /(self._virtualBalance+self._virtualStocks*lastprice)
        SQLog.info("begin_transact:", self._stockcode, "profit=", nowValue/self.Invest,
                   "benchmark=", lastprice/self.StartPrice,
                   "posotion=", position, "vposotion=", vposition,
                   "_initprice=", self._initprice, "lastprice=", lastprice,
                   "Buy=", buyvolume if needbuy else "0", "@", buyprice,
                   "Sell=", sellvolume if needsell else "0", "@", sellprice,
                   "buyprice_in_range=", buyprice_in_range, "sellprice_in_range=", sellprice_in_range,
                   "nowbalance=", nowbalance, "nowstocks=", nowstocks, "bidprice=", bidprice, "askprice=", askprice,
                   "spread=", spread, "minstocks=", minstocks, "forcelurker=", forcelurker, "blind=", blind)

        if self.NeedRePosition and not(needbuy or needsell):
            self.end_transact(lastprice, 0, 0, 0, lastprice, minstocks)
            self._timesNotDeal -= 1

        return [needbuy, buyprice, buyvolume, needsell, sellprice, sellvolume]
    
    def end_transact(self, lastprice, diffbalance, diffstocks, cursorstep, dealprice, minstocks):
        if not self._isopen:
            SQLog.error("end_transact:not opened,", self._stockcode)
            return False

        if diffbalance > 0:
            self._totalMoneySellDeal += diffbalance
        else:
            self._totalMoneyBuyDeal += (-diffbalance)
        if diffstocks > 0:
            self._totalStocksBuyDeal += diffstocks
        else:
            self._totalStocksSellDeal += (-diffstocks)
        if not diffbalance == 0:
            self._timesDeal += 1
        else:
            self._timesNotDeal += 1

        self._virtualBalance = self._virtualBalance + diffbalance
        self._virtualStocks = self._virtualStocks + diffstocks

        self._nowbalance = self._nowbalance + diffbalance
        self._nowstocks = self._nowstocks + diffstocks
        self._nowprice = lastprice

        nowValue = self._nowbalance + self._nowstocks * lastprice

        position = self._nowstocks * lastprice /nowValue
        if self.NeedRePosition:
            if self._nowstocks < minstocks:
                B = 1 - position
                Bwant = 1 - 1 * 0.5 * self.Threshold * self._leverage
                Bwant = 0.5 if Bwant < 0.5 else Bwant
                self._virtualBalance = nowValue * (0.5 * self._leverage + B - Bwant)
                self._virtualStocks  = nowValue * (0.5 * self._leverage - B + Bwant) / lastprice
                self._timesRePosition += 1
                SQLog.info("end_transact,reposition up,", self._stockcode,
                           "_timesRePosition=", self._timesRePosition)
            elif self._nowbalance < minstocks*lastprice*self.MaxFees:
                B = 1 - position
                Bwant = 1 * 0.5 * self.Threshold * self._leverage
                Bwant = 0.5 if Bwant>0.5 else Bwant
                self._virtualBalance = nowValue * (0.5 * self._leverage + B - Bwant)
                self._virtualStocks  = nowValue * (0.5 * self._leverage - B + Bwant) / lastprice
                self._timesRePosition += 1
                SQLog.info("end_transact,reposition down,", self._stockcode,
                           "_timesRePosition=", self._timesRePosition)

        #nowLeverage = (self._virtualBalance+self._virtualStocks*lastprice) / nowValue
        #if nowLeverage < self._leverage*0.8 or nowLeverage > self._leverage*1.2:
        #    self._virtualBalance = self._virtualBalance * self._leverage / nowLeverage
        #    self._virtualStocks = self._virtualStocks * self._leverage / nowLeverage
        #    self._leverage = nowLeverage
        #    self._timesReLeverage += 1

        vposition = self._virtualStocks * lastprice /(self._virtualBalance+self._virtualStocks*lastprice)
        SQLog.info("end_transact:", self._stockcode, "profit=", nowValue/self.Invest,
                   "benchmark=", lastprice/self.StartPrice,
                   "Leverage=", self._leverage, "/", self.BaseLeverage,
                   "postition=", position, "vposition=", vposition,
                   "_initprice=", self._initprice, "lastprice=", lastprice,
                   "_nowbalance=", self._nowbalance, "_nowstocks=", self._nowstocks,
                   "VBalance=", self._virtualBalance, "VStocks=", self._virtualStocks,
                   "diffbalance=", diffbalance, "diffstocks=", diffstocks, "minstocks=", minstocks)

        averatio = self._sumRatioMtThreshold / self._timesRatioMtThreshold if self._timesRatioMtThreshold > 0 else 0
        SQLog.info("STATISTICS:", self._stockcode, "TotalMoney:[BuyDeal=", self._totalMoneyBuyDeal,
                   "SellDeal=", self._totalMoneySellDeal, "]",
                   "TotalStocks:[BuyDeal=", self._totalStocksBuyDeal, "SellDeal=", self._totalStocksSellDeal, "]",
                   "_timesOnTick=", self._timesOnTick,
                   "_timesRatioLtThreshold=", self._timesRatioLtThreshold,
                   "_timesRatioMtThreshold=", self._timesRatioMtThreshold, "averageRatio=", averatio,
                   "_timesLurker=", self._timesLurker, "_timesPlaceOrder=", self._timesPlaceOrder,
                   "_timesDeal=", self._timesDeal, "_timesNotDeal=", self._timesNotDeal,
                   "_timesRePosition=", self._timesRePosition, "_timesReLeverage=", self._timesReLeverage)
        return True

