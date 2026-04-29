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
    PEBBLES_PRODUCTS = [
        "PEBBLES_XL",
    ]

    POSITION_LIMIT: Dict[str, int] = {p: 10 for p in PEBBLES_PRODUCTS}

    PARAMS = {
        "edge_pct": 0.05,    # min % edge each penny quote needs vs the wall-mid fair (e.g. 0.06 == 0.06%)
        "fade": 0.2,         # fair -= fade * position
        "fair_bias": 3,      # constant added to wall-mid fair to bias the book long
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        logger.print("positions:", state.position)

        edge_pct = self.PARAMS["edge_pct"]
        fade = self.PARAMS["fade"]
        fair_bias = self.PARAMS["fair_bias"]

        for product in self.PEBBLES_PRODUCTS:
            orders: List[Order] = []
            depth = state.order_depths.get(product)
            if depth is None:
                result[product] = orders
                continue

            asks = sorted(depth.sell_orders.items())
            bids = sorted(depth.buy_orders.items(), reverse=True)
            best_ask, _ = asks[0] if asks else (None, None)
            best_bid, _ = bids[0] if bids else (None, None)
            ask_2, _ = asks[1] if len(asks) > 1 else (None, None)
            bid_2, _ = bids[1] if len(bids) > 1 else (None, None)

            # wall mid: average of level-2 quotes
            if bid_2 is None or ask_2 is None:
                result[product] = orders
                continue
            fair = (bid_2 + ask_2) / 2 + fair_bias

            limit = self.POSITION_LIMIT[product]
            position = state.position.get(product, 0)

            # fade fair by position so we're more willing to sell when long, buy when short
            fair -= fade * position

            # penny each side independently if quote is at least edge_pct from fair
            if (best_bid is not None
                    and (fair - (best_bid + 1)) / fair * 100 >= edge_pct
                    and position < limit):
                orders.append(buy(product, best_bid + 1, limit - position))

            if (best_ask is not None
                    and ((best_ask - 1) - fair) / fair * 100 >= edge_pct
                    and position > -limit):
                orders.append(sell(product, best_ask - 1, limit + position))

            result[product] = orders

        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
