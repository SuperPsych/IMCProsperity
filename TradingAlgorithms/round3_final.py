from datamodel import Order, OrderDepth, TradingState
from typing import Any, Callable, Dict, List, Tuple
import json


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders, conversions: int, trader_data: str) -> None:
        for symbol, depth in state.order_depths.items():
            bids = sorted(depth.buy_orders.items(), reverse=True)
            asks = sorted(depth.sell_orders.items())

            def get_level(side, i):
                if i < len(side):
                    return side[i]
                return (None, None)

            bid_levels = [get_level(bids, i) for i in range(3)]
            ask_levels = [get_level(asks, i) for i in range(3)]

            best_bid = bid_levels[0][0]
            best_ask = ask_levels[0][0]

            mid_price = (
                (best_bid + best_ask) / 2
                if best_bid is not None and best_ask is not None
                else None
            )

            row = {
                "timestamp": state.timestamp,
                "product": symbol,
                "bid_price_1": bid_levels[0][0],
                "bid_volume_1": bid_levels[0][1],
                "bid_price_2": bid_levels[1][0],
                "bid_volume_2": bid_levels[1][1],
                "bid_price_3": bid_levels[2][0],
                "bid_volume_3": bid_levels[2][1],
                "ask_price_1": ask_levels[0][0],
                "ask_volume_1": ask_levels[0][1],
                "ask_price_2": ask_levels[1][0],
                "ask_volume_2": ask_levels[1][1],
                "ask_price_3": ask_levels[2][0],
                "ask_volume_3": ask_levels[2][1],
                "mid_price": mid_price,
                "own_trades": [
                    (t.price, t.quantity, t.timestamp)
                    for t in state.own_trades.get(symbol, [])
                ],
                "market_trades": [
                    (t.price, t.quantity, t.timestamp)
                    for t in state.market_trades.get(symbol, [])
                ],
                "position": state.position.get(symbol, 0),
                "log": self.logs.strip(),
            }

            print(json.dumps(row))

        self.logs = ""


logger = Logger()


def buy(product: str, price: int, quantity: int) -> Order:
    return Order(product, price, abs(quantity))


def sell(product: str, price: int, quantity: int) -> Order:
    return Order(product, price, -abs(quantity))

HYDRO_OFFSET = 1
VELVET_OFFSET = 1
OPT_OFFSET = 1

PARAMS = {
    "hydrogel_mean": 9990,
    "hydrogel_alpha": 300.0,
    "hydrogel_offset": HYDRO_OFFSET*31.9,

    "velvetfruit_mean": 5250,
    "velvetfruit_alpha": 300.0,
    "velvetfruit_offset": VELVET_OFFSET*15.6,

    # voucher fair = mean + slope * timestamp ; mean is the t=0 intercept
    "VEV_4000_mean": 1250, "VEV_4000_alpha": 300.0, "VEV_4000_offset": VELVET_OFFSET*15.6, "VEV_4000_slope": 0,
    "VEV_4500_mean": 750,  "VEV_4500_alpha": 300.0, "VEV_4500_offset": VELVET_OFFSET*15.6, "VEV_4500_slope": 0,
    "VEV_5000_mean": 257,  "VEV_5000_alpha": 300.0, "VEV_5000_offset": OPT_OFFSET*14.4,    "VEV_5000_slope": -1.485e-06,
    "VEV_5100_mean": 172.6322,  "VEV_5100_alpha": 300.0, "VEV_5100_offset": OPT_OFFSET*12.7,    "VEV_5100_slope": -4.096e-06,
    "VEV_5200_mean": 103.9988,  "VEV_5200_alpha": 300.0, "VEV_5200_offset": OPT_OFFSET*9.7,    "VEV_5200_slope": -5.559e-06,
    "VEV_5300_mean": 56.8749,   "VEV_5300_alpha": 300.0, "VEV_5300_offset": OPT_OFFSET*6.2,     "VEV_5300_slope": -5.898e-06,
    "VEV_5400_mean": 20.5659,   "VEV_5400_alpha": 300.0, "VEV_5400_offset": OPT_OFFSET*3.4,     "VEV_5400_slope": -3.231e-06,
    "VEV_5500_mean": 9.3823,    "VEV_5500_alpha": 300.0, "VEV_5500_offset": OPT_OFFSET*1.7,     "VEV_5500_slope": -1.838e-06,
    "VEV_6000_mean": 0.5,    "VEV_6000_alpha": 300.0, "VEV_6000_offset": OPT_OFFSET*0.0,     "VEV_6000_slope": 0,
    "VEV_6500_mean": 0.5,    "VEV_6500_alpha": 300.0, "VEV_6500_offset": OPT_OFFSET*0.0,     "VEV_6500_slope": 0,

    "ewma_gamma": 1,
    "ewma_gamma_opts": 1,
}


VEV_VOUCHERS = [
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500",
]


class Trader:
    TRADED_PRODUCTS = {
        "HYDROGEL_PACK",
        "VELVETFRUIT_EXTRACT",
        *VEV_VOUCHERS,
    }

    POSITION_LIMITS: Dict[str, int] = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        **{v: 300 for v in VEV_VOUCHERS},
    }

    ENABLE_STRATEGY: Dict[str, bool] = {
        "HYDROGEL_PACK": True,
        "VELVETFRUIT_EXTRACT": True,
        **{v: True for v in VEV_VOUCHERS},
    }

    MA_WINDOW = 10

    def __init__(self) -> None:
        self.strategies: Dict[str, Callable[[str, TradingState], List[Order]]] = {
            "HYDROGEL_PACK": self._trade_hydrogel,
            "VELVETFRUIT_EXTRACT": self._trade_velvetfruit,
            **{v: self._trade_voucher for v in VEV_VOUCHERS},
        }
        self.price_history: Dict[str, List[List[int | None]]] = {}
        self.mid_history: Dict[str, List[float]] = {}
        self.initial_fair: Dict[str, float | None] = {}
        # running sums for O(1) linear regression: y = a + b*x, x = step index
        self.linreg: Dict[str, Dict[str, float]] = {}

    def run(self, state: TradingState):
        if state.traderData:
            # reload persistent strategy state from traderData here
            pass

        result: Dict[str, List[Order]] = {}
        logger.print("positions:", state.position)

        for product in self.TRADED_PRODUCTS:
            if product not in state.order_depths:
                continue
            strategy = self.strategies.get(product, self._trade_default)
            result[product] = strategy(product, state)

        conversions = 0
        trader_data = json.dumps({})
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def _trade_default(self, product: str, state: TradingState) -> List[Order]:
        return []

    def _trade_hydrogel(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_ask, best_ask_qty = asks[0] if asks else (None, None)
        best_bid, best_bid_qty = bids[0] if bids else (None, None)

        limit = self.POSITION_LIMITS.get(product, 200)
        mean = PARAMS["hydrogel_mean"]
        alpha = PARAMS["hydrogel_alpha"]
        offset = PARAMS["hydrogel_offset"]

        # ewma
        if best_ask and best_bid:
            mid = (best_ask + best_bid) / 2
            PARAMS["hydrogel_mean"] = (1 - PARAMS["ewma_gamma"]) * mid + (PARAMS["ewma_gamma"]) * mean

        take_buy_amount = round((mean-best_ask-offset)*alpha)
        take_buy_amount = min(limit - position, -best_ask_qty, take_buy_amount)

        take_sell_amount = round((best_bid-mean-offset)*alpha)
        take_sell_amount = min(limit + position, best_bid_qty, take_sell_amount)

        if take_buy_amount > 0:
            orders.append(buy(product, best_ask, take_buy_amount))
            position += take_buy_amount
        elif take_sell_amount > 0:
            orders.append(sell(product, best_bid, -take_sell_amount))
            position -= take_sell_amount

        make_buy_amount = round((mean-(best_bid+1)-offset)*alpha)
        make_buy_amount = min(limit - position, -best_ask_qty, take_buy_amount)

        make_sell_amount = round(((best_ask-1)-mean-offset)*alpha)
        make_sell_amount = min(limit + position, best_bid_qty, take_sell_amount)

        if make_buy_amount > 0:
            orders.append(buy(product, best_bid+1, make_buy_amount))
        elif make_sell_amount > 0:
            orders.append(sell(product, best_ask-1, -make_sell_amount))

        return orders

    def _trade_velvetfruit(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_ask, best_ask_qty = asks[0] if asks else (None, None)
        best_bid, best_bid_qty = bids[0] if bids else (None, None)

        limit = self.POSITION_LIMITS.get(product, 200)
        mean = PARAMS["velvetfruit_mean"]
        alpha = PARAMS["velvetfruit_alpha"]
        offset = PARAMS["velvetfruit_offset"]

        # ewma
        if best_ask and best_bid:
            mid = (best_ask + best_bid) / 2
            PARAMS["velvetfruit_mean"] = (1 - PARAMS["ewma_gamma"]) * mid + (PARAMS["ewma_gamma"]) * mean

        take_buy_amount = round((mean-best_ask-offset)*alpha)
        take_buy_amount = min(limit - position, -best_ask_qty, take_buy_amount)

        take_sell_amount = round((best_bid-mean-offset)*alpha)
        take_sell_amount = min(limit + position, best_bid_qty, take_sell_amount)

        if take_buy_amount > 0:
            orders.append(buy(product, best_ask, take_buy_amount))
            position += take_buy_amount
        elif take_sell_amount > 0:
            orders.append(sell(product, best_bid, -take_sell_amount))
            position -= take_sell_amount

        make_buy_amount = round((mean-(best_bid+1)-offset)*alpha)
        make_buy_amount = min(limit - position, -best_ask_qty, take_buy_amount)

        make_sell_amount = round(((best_ask-1)-mean-offset)*alpha)
        make_sell_amount = min(limit + position, best_bid_qty, take_sell_amount)

        if make_buy_amount > 0:
            orders.append(buy(product, best_bid+1, make_buy_amount))
        elif make_sell_amount > 0:
            orders.append(sell(product, best_ask-1, -make_sell_amount))

        return orders

    def _trade_voucher(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_ask, best_ask_qty = asks[0] if asks else (None, None)
        best_bid, best_bid_qty = bids[0] if bids else (None, None)

        limit = self.POSITION_LIMITS.get(product, 300)
        base_mean = PARAMS[f"{product}_mean"]
        alpha = PARAMS[f"{product}_alpha"]
        offset = PARAMS[f"{product}_offset"]
        slope = PARAMS[f"{product}_slope"]

        # linear approximation: fair at global time t = base_mean + slope * (day*1e6 + ts)
        # state.timestamp resets per day; PROSPERITY4BT_DAY (set by the backtester)
        # gives the day index so the slope continues across day boundaries.
        day = 3
        effective_t = day * 1_000_000 + state.timestamp
        mean = base_mean + slope * effective_t

        # ewma writes back to the t=0 intercept
        if best_ask and best_bid:
            mid = (best_ask + best_bid) / 2
            gamma = PARAMS["ewma_gamma"]
            if int(product[4:8]) >= 5200:
                gamma = PARAMS["ewma_gamma_opts"]
            PARAMS[f"{product}_mean"] = (1 - gamma) * (mid - slope * effective_t) + gamma * base_mean

        take_buy_amount = round((mean-best_ask-offset)*alpha)
        take_buy_amount = min(limit - position, -best_ask_qty, take_buy_amount)

        take_sell_amount = round((best_bid-mean-offset)*alpha)
        take_sell_amount = min(limit + position, best_bid_qty, take_sell_amount)

        if take_buy_amount > 0:
            orders.append(buy(product, best_ask, take_buy_amount))
            position += take_buy_amount
        elif take_sell_amount > 0:
            orders.append(sell(product, best_bid, -take_sell_amount))
            position -= take_sell_amount

        make_buy_amount = round((mean-(best_bid+1)-offset)*alpha)
        make_buy_amount = min(limit - position, -best_ask_qty, make_buy_amount)

        make_sell_amount = round(((best_ask-1)-mean-offset)*alpha)
        make_sell_amount = min(limit + position, best_bid_qty, make_sell_amount)

        if make_buy_amount > 0:
            orders.append(buy(product, best_bid+1, make_buy_amount))
        elif make_sell_amount > 0:
            orders.append(sell(product, best_ask-1, -make_sell_amount))

        return orders

    def _previous_bbo(self, product: str) -> Tuple[int | None, int | None]:
        if self.price_history.get(product):
            return tuple(self.price_history[product][-1])
        return None, None

    def _update_mid(self, product: str, best_bid: int | None, best_ask: int | None) -> None:
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2
            self.mid_history.setdefault(product, []).append(mid)

    def _moving_avg(self, product: str) -> float | None:
        history = self.mid_history.get(product, [])
        if not history:
            return None
        window = history[-self.MA_WINDOW:]
        return sum(window) / len(window)

    def _update_linreg(self, product: str, mid: float) -> None:
        s = self.linreg.setdefault(product, {"n": 0, "sx": 0.0, "sy": 0.0, "sxx": 0.0, "sxy": 0.0})
        x = float(s["n"])
        s["n"] += 1
        s["sx"] += x
        s["sy"] += mid
        s["sxx"] += x * x
        s["sxy"] += x * mid

    def _linreg_fair(self, product: str) -> float | None:
        s = self.linreg.get(product)
        if s is None or s["n"] < 2:
            return None
        n, sx, sy, sxx, sxy = s["n"], s["sx"], s["sy"], s["sxx"], s["sxy"]
        denom = n * sxx - sx * sx
        if denom == 0:
            return sy / n
        b = (n * sxy - sx * sy) / denom
        a = (sy - b * sx) / n
        return a + b * n

    def _best_bid_ask(self, order_depth: OrderDepth) -> Tuple[int | None, int | None]:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        return best_bid, best_ask