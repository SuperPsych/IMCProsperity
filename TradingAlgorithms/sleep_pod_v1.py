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
SLEEP_POD_MIN_SPREAD = 6
SLEEP_POD_FADE_TICKS = 3
SLEEP_POD_TARGET_POS = 4   # default static long bias for trenders
DEFAULT_FADE_TICKS = 0
DEFAULT_TARGET_POS = 0

# Per-pod momentum size: only applied when non-zero. Replaces the static
# long bias for that pod with target = ±SIZE based on intraday drift.
SLEEP_POD_MOMENTUM = {
    "SLEEP_POD_NYLON": 10,
}


def product_type(product: str) -> str:
    if product.startswith("SLEEP_POD_"):
        return "SLEEP_POD"
    return "DEFAULT"


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

    # Inventory fade, recentered on target_pos. Above target → behave as
    # if long (passive buy, aggressive sell). Below target → behave as
    # if short, even at position 0, which biases us toward accumulating
    # to target_pos.
    shift = round(fade_ticks * (position - target_pos) / limit) if limit > 0 else 0
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
    def __init__(self) -> None:
        # Per-product day-open mid, reset on day rollover (detected via
        # state.timestamp going backwards).
        self.day_open: Dict[str, float] = {}
        self.last_ts: int | None = None

    def run(self, state: TradingState):
        # Day rollover: timestamps reset to 0 each day.
        if self.last_ts is not None and state.timestamp < self.last_ts:
            self.day_open = {}
        self.last_ts = state.timestamp

        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            position = state.position.get(product, 0)
            ptype = product_type(product)

            mid: float | None = None
            if depth.buy_orders and depth.sell_orders:
                mid = (max(depth.buy_orders) + min(depth.sell_orders)) / 2
                if product not in self.day_open:
                    self.day_open[product] = mid

            if ptype == "SLEEP_POD":
                mom_size = SLEEP_POD_MOMENTUM.get(product, 0)
                if mom_size > 0:
                    target = 0
                    open_px = self.day_open.get(product)
                    if mid is not None and open_px is not None:
                        if mid > open_px:
                            target = mom_size
                        elif mid < open_px:
                            target = -mom_size
                else:
                    target = SLEEP_POD_TARGET_POS
                orders = penny(product, depth, position, DEFAULT_LIMIT, SLEEP_POD_MIN_SPREAD, SLEEP_POD_FADE_TICKS, target)
            else:
                orders = penny(product, depth, position, DEFAULT_LIMIT, 2, DEFAULT_FADE_TICKS, DEFAULT_TARGET_POS)

            if orders:
                result[product] = orders

        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
