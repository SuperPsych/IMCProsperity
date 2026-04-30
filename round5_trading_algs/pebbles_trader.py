from datamodel import Order, OrderDepth, TradingState
from typing import Any, Dict, List
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


class Trader:
    # per-product parameter sets
    PARAMS: Dict[str, Dict[str, float]] = {
        "PEBBLES_XL": {
            "edge_pct": 0.06,        # min % edge each penny quote needs vs the fair
            "inventory_skew": 0.5,   # fair -= inventory_skew * (position - target_position)
            "drift_bias": 0,         # constant added to wall-mid fair to bias the book long
            "target_position": 0,    # inventory level the skew pulls fair toward
        },
        "PEBBLES_M": {
            "edge_pct": 0.06,        # ≈ galaxy's spread_thresh=6 at ~10000 mid
            "inventory_skew": 0.2,   # galaxy's fade
            "drift_bias": 0,
            "target_position": 0,
        },
        "PEBBLES_XS": {
            "frontrun_ratio": 0.5,   # fraction of observed market trade qty to copy
        },
        "PEBBLES_S": {
            "edge_pct": 0.06,
            "inventory_skew": 0.2,
            "drift_bias": 0,        # bias book short since this is the most liquid product
            "target_position": 0,
        },
        "PEBBLES_L": {
            "edge_pct": 0.06,
            "inventory_skew": 0.2,
            "drift_bias": 0,        # bias book short since this is the most liquid product
            "target_position": 0,
        },
    }

    PENNYING_PRODUCTS = ["PEBBLES_XL", "PEBBLES_M", "PEBBLES_S", "PEBBLES_L"]
    COPYING_PRODUCTS = ["PEBBLES_XS"]
    PEBBLES_PRODUCTS = PENNYING_PRODUCTS + COPYING_PRODUCTS

    POSITION_LIMIT: Dict[str, int] = {p: 10 for p in PEBBLES_PRODUCTS}

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        logger.print("positions:", state.position)

        for product in self.PENNYING_PRODUCTS:
            result[product] = self._trade_pennying(product, state)

        for product in self.COPYING_PRODUCTS:
            result[product] = self._trade_copying(product, state)

        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def _trade_pennying(self, product: str, state: TradingState) -> List[Order]:
        p = self.PARAMS[product]
        edge_pct = p["edge_pct"]
        inventory_skew = p["inventory_skew"]
        drift_bias = p["drift_bias"]
        target_position = p["target_position"]

        orders: List[Order] = []
        depth = state.order_depths.get(product)
        if depth is None:
            return orders

        asks = sorted(depth.sell_orders.items())
        bids = sorted(depth.buy_orders.items(), reverse=True)
        best_ask, _ = asks[0] if asks else (None, None)
        best_bid, _ = bids[0] if bids else (None, None)
        ask_2, _ = asks[1] if len(asks) > 1 else (None, None)
        bid_2, _ = bids[1] if len(bids) > 1 else (None, None)

        # wall mid: average of level-2 quotes
        if bid_2 is None or ask_2 is None:
            return orders
        mid = (bid_2 + ask_2) / 2

        limit = self.POSITION_LIMIT[product]
        position = state.position.get(product, 0)

        fair = mid + drift_bias - inventory_skew * (position - target_position)

        # penny each side independently if quote is at least edge_pct from fair
        if (best_bid is not None
                and (fair - (best_bid + 1)) / fair * 100 >= edge_pct
                and position < limit):
            orders.append(buy(product, best_bid + 1, limit - position))

        if (best_ask is not None
                and ((best_ask - 1) - fair) / fair * 100 >= edge_pct
                and position > -limit):
            orders.append(sell(product, best_ask - 1, limit + position))

        return orders

    def _trade_copying(self, product: str, state: TradingState) -> List[Order]:
        orders: List[Order] = []
        depth = state.order_depths.get(product)
        if depth is None:
            return orders

        frontrun_ratio = self.PARAMS[product]["frontrun_ratio"]
        limit = self.POSITION_LIMIT[product]

        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if best_bid is None or best_ask is None:
            return orders

        position = state.position.get(product, 0)
        buy_capacity = limit - position
        sell_capacity = limit + position

        market_trades = state.market_trades.get(product, [])
        if not market_trades:
            return orders

        order = market_trades[0]
        qty = int(abs(order.quantity) * frontrun_ratio)
        if order.quantity < 0:
            qty = min(qty, buy_capacity)
            if qty > 0:
                orders.append(buy(product, best_bid + 1, qty))
        else:
            qty = min(qty, sell_capacity)
            if qty > 0:
                orders.append(sell(product, best_ask - 1, qty))

        return orders
