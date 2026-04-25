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
        "VELVETFRUIT_EXTRACT": False,
        **{v: False for v in VEV_VOUCHERS},
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
        mean = 9990
        alpha = 0.1
        offset = 2

        buy_amount = round((mean-best_ask-offset)*alpha)
        sell_amount = round((best_bid-mean-offset)*alpha)
        if buy_amount > 0 and position < limit:
            orders.append(buy(product, best_ask, min(limit - position, best_ask_qty, buy_amount)))
        elif sell_amount > 0 and position > -limit:
            orders.append(sell(product, best_bid, min(limit + position, best_bid_qty, sell_amount)))
        return orders

    def _trade_velvetfruit(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        return []

    def _trade_voucher(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        return []

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
