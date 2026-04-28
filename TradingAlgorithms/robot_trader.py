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

PARAMS = {
    "PENNY_AMOUNT" : 3,
    "MIN_SPREAD_THRESHOLD" : 7,
    "MASSIVE_SPIKE_THRESH" : 90,
}



def buy(product: str, price: int, quantity: int) -> Order:
    return Order(product, price, abs(quantity))


def sell(product: str, price: int, quantity: int) -> Order:
    return Order(product, price, -abs(quantity))

POSITION_LIMITS: Dict[str, int] = {
    "MICROCHIP_CIRCLE": 10,
    "MICROCHIP_RECTANGLE": 10,
    "MICROCHIP_SQUARE" : 10,
    "MICROCHIP_OVAL": 10,
    "MICROCHIP_TRIANGLE" : 10,
    "ROBOT_DISHES" : 10,
}

TRADED_PRODUCTS: List[str] = [
    # "MICROCHIP_CIRCLE",
    # "MICROCHIP_RECTANGLE",
    # "MICROCHIP_SQUARE",
    # "MICROCHIP_OVAL",
    # "MICROCHIP_TRIANGLE",
    "ROBOT_DISHES",
    "OXYGEN_SHAKE_EVENING_BREATH",
    "OXYGEN_SHAKE_CHOCOLATE"
]

class Trader:

    def __init__(self):
        self.strategies = {
            "ROBOT_DISHES" : self._trade_massive_spike_product,
            "OXYGEN_SHAKE_EVENING_BREATH" : self._trade_massive_spike_product,
            "OXYGEN_SHAKE_CHOCOLATE" : self._trade_massive_spike_product,
        }
        self.POSITION_LIMITS = POSITION_LIMITS
        self.TRADED_PRODUCTS = TRADED_PRODUCTS
        self.massive_spike_mid_history = {}

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        logger.print("positions:", state.position)

        for product in self.TRADED_PRODUCTS:
            if product not in state.order_depths:
                continue
            strategy = self.strategies.get(product, self._trade_default)
            result[product] = strategy(product, state, result)

        conversions = 0
        trader_data = json.dumps({})
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def _trade_default(self, product: str, state: TradingState, orders) -> List[Order]:
        orderbook = state.order_depths[product]
        buy_orders = orderbook.buy_orders
        sell_orders = orderbook.sell_orders
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        pos = state.position.get(product, 0)
        buy_capacity = self.POSITION_LIMITS[product] - pos
        sell_capacity = self.POSITION_LIMITS[product] + pos
        res = []
        if best_bid is not None and best_ask is not None and best_ask - best_bid >= PARAMS["MIN_SPREAD_THRESHOLD"]:
            res.append(sell(
                    product,
                    best_ask - 1,
                    min(PARAMS["PENNY_AMOUNT"], sell_capacity)
                ))
            res.append(buy(
                    product,
                    best_bid + 1,
                    min(PARAMS["PENNY_AMOUNT"], buy_capacity)
                ))
        return res

    def _trade_massive_spike_product(self, product, state, orders):
        orderbook = state.order_depths[product]
        buy_orders = orderbook.buy_orders
        sell_orders = orderbook.sell_orders
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        pos = state.position.get(product, 0)
        res = []
        prev_mid = self.massive_spike_mid_history.get(product, None)
        mid = (best_bid + best_ask)/2
        if prev_mid is not None:
            if mid - prev_mid >= PARAMS["MASSIVE_SPIKE_THRESH"]:
                res.extend(self.get_target_position(product, buy_orders, sell_orders, pos, -10))
            elif prev_mid - mid >= PARAMS["MASSIVE_SPIKE_THRESH"]:
                res.extend(self.get_target_position(product, buy_orders, sell_orders, pos, 10))     
        self.massive_spike_mid_history[product] = mid
        return res
    
    def get_target_position(self, product, buy_orders, sell_orders, pos, target_pos):
        if target_pos is None:
            return []
        orders = []
        delta = target_pos - pos
        if delta == 0:
            return orders
        if delta > 0:
            remaining = delta
            asks = sorted(sell_orders.items())
            for price, volume in asks:
                available = abs(volume)
                qty = min(remaining, available)
                if qty <= 0:
                    continue
                orders.append(buy(product, price, qty))
                remaining -= qty
                if remaining <= 0:
                    break
        else:
            remaining = abs(delta)
            bids = sorted(buy_orders.items(), reverse=True)
            for price, volume in bids:
                available = abs(volume)
                qty = min(remaining, available)
                if qty <= 0:
                    continue
                orders.append(sell(product, price, qty))
                remaining -= qty
                if remaining <= 0:
                    break
        return orders


