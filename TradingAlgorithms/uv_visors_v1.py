from datamodel import Order, OrderDepth, TradingState
from typing import Any, Dict, List
import json


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders, conversions: int, trader_data: str) -> None:
        traded = set(orders.keys()) if orders else set()
        for symbol, depth in state.order_depths.items():
            if symbol not in traded:
                continue
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


DEFAULT_LIMIT = 10
UV_VISOR_MIN_SPREAD = 8
UV_VISOR_FADE_TICKS = 2

UV_VISORS = {
    "UV_VISOR_AMBER",
    "UV_VISOR_MAGENTA",
    "UV_VISOR_ORANGE",
    "UV_VISOR_RED",
    "UV_VISOR_YELLOW",
}

# Per-product long/short bias. Empty by default.
UV_VISOR_TARGET_POS: Dict[str, int] = {
    "UV_VISOR_AMBER":   -5,
    "UV_VISOR_MAGENTA": 5,
    "UV_VISOR_RED":     5,
}


def penny(
    product: str,
    depth: OrderDepth,
    position: int,
    limit: int,
    min_spread: int,
    fade_ticks: int = 0,
    target_pos: int = 0,
) -> List[Order]:
    bids = sorted(depth.buy_orders.items(), reverse=True)
    asks = sorted(depth.sell_orders.items())
    if not bids or not asks:
        return []

    best_bid = bids[0][0]
    best_ask = asks[0][0]
    if best_ask - best_bid < min_spread:
        return []

    # Asymmetric fade around target_pos: only encourage moving toward
    # target, never past it.
    delta = position - target_pos
    if target_pos > 0:
        delta = min(0, delta)
    elif target_pos < 0:
        delta = max(0, delta)
    shift = round(fade_ticks * delta / limit) if limit > 0 else 0
    buy_price = best_bid + 1 - shift
    sell_price = best_ask - 1 - shift

    orders: List[Order] = []
    buy_capacity = limit - position
    sell_capacity = limit + position
    if buy_capacity > 0:
        orders.append(buy(product, buy_price, buy_capacity))
    if sell_capacity > 0:
        orders.append(sell(product, sell_price, sell_capacity))
    return orders


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            if product not in UV_VISORS:
                continue
            position = state.position.get(product, 0)
            target = UV_VISOR_TARGET_POS.get(product, 0)
            orders = penny(product, depth, position, DEFAULT_LIMIT, UV_VISOR_MIN_SPREAD, UV_VISOR_FADE_TICKS, target)
            if orders:
                result[product] = orders

        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
