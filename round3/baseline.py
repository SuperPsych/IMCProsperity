from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List


POSITION_LIMITS: Dict[str, int] = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
}


def penny_quotes(
    product: str,
    depth: OrderDepth,
    position: int,
    limit: int,
) -> List[Order]:
    orders: List[Order] = []
    if not depth.buy_orders or not depth.sell_orders:
        return orders

    best_bid = max(depth.buy_orders.keys())
    best_ask = min(depth.sell_orders.keys())

    bid_px = best_bid + 1
    ask_px = best_ask - 1
    if bid_px >= ask_px:
        return orders

    buy_size = limit - position
    if buy_size > 0:
        orders.append(Order(product, bid_px, buy_size))

    sell_size = limit + position
    if sell_size > 0:
        orders.append(Order(product, ask_px, -sell_size))

    return orders


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        for product, limit in POSITION_LIMITS.items():
            depth = state.order_depths.get(product)
            if depth is None:
                continue
            position = state.position.get(product, 0)
            orders = penny_quotes(product, depth, position, limit)
            if orders:
                result[product] = orders
        return result, 0, ""
