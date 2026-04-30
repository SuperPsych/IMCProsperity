from datamodel import Order, TradingState
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
    SNACKPACK_PRODUCTS = [
        "SNACKPACK_CHOCOLATE",
        "SNACKPACK_VANILLA",
        "SNACKPACK_PISTACHIO",
        "SNACKPACK_RASPBERRY",
        "SNACKPACK_STRAWBERRY",
    ]

    POSITION_LIMIT: Dict[str, int] = {p: 10 for p in SNACKPACK_PRODUCTS}

    PARAMS = {
        "quote_size": 10,
        "min_spread": 6,
        "unwind_size": 2,
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in self.SNACKPACK_PRODUCTS}
        logger.print("positions:", state.position)

        for product in self.SNACKPACK_PRODUCTS:
            result[product] = self.market_make_product(state, product)

        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def market_make_product(self, state: TradingState, product: str) -> List[Order]:
        depth = state.order_depths.get(product)
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            return []

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        spread = best_ask - best_bid
        position = state.position.get(product, 0)
        limit = self.POSITION_LIMIT[product]

        quote_size = self.PARAMS["quote_size"]
        min_spread = self.PARAMS["min_spread"]
        unwind_size = self.PARAMS["unwind_size"]

        orders: List[Order] = []

        if spread >= min_spread:
            bid_price = best_bid + 1
            ask_price = best_ask - 1

            buy_room = max(0, limit - position)
            sell_room = max(0, limit + position)

            bid_size = min(quote_size, buy_room)
            ask_size = min(quote_size, sell_room)

            if bid_size > 0:
                orders.append(buy(product, bid_price, bid_size))
            if ask_size > 0:
                orders.append(sell(product, ask_price, ask_size))
        else:
            if position > 0:
                unwind = min(unwind_size, position)
                orders.append(sell(product, best_bid, unwind))
            elif position < 0:
                unwind = min(unwind_size, -position)
                orders.append(buy(product, best_ask, unwind))

        logger.print(
            product,
            "bid=", best_bid,
            "ask=", best_ask,
            "spread=", spread,
            "position=", position,
            "orders=", [(order.price, order.quantity) for order in orders],
        )
        return orders
