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


def _mid(depth: OrderDepth):
    if not depth.buy_orders or not depth.sell_orders:
        return None
    return (max(depth.buy_orders) + min(depth.sell_orders)) / 2


def _sweep_to(product: str, target: int, position: int, depth: OrderDepth) -> List[Order]:
    """Walk the book and place orders at every level until we've moved position to target."""
    delta = target - position
    orders: List[Order] = []
    if delta > 0:
        for price, vol in sorted(depth.sell_orders.items()):
            take = min(delta, -vol)
            if take <= 0:
                break
            orders.append(buy(product, price, take))
            delta -= take
            if delta == 0:
                break
    elif delta < 0:
        need = -delta
        for price, vol in sorted(depth.buy_orders.items(), reverse=True):
            take = min(need, vol)
            if take <= 0:
                break
            orders.append(sell(product, price, take))
            need -= take
            if need == 0:
                break
    return orders


def pair_trade(state: TradingState, asset_a: str, asset_b: str, beta: float,
               mean: float, threshold: float, size_a: int, size_b: int) -> Dict[str, List[Order]]:
    """Mean-revert on spread around `mean`. Sweeps book to reach targets.
    sign(size_b) sets the B leg: spread = mid_a + sign(size_b)*beta*mid_b.
    Below mean -> target = (size_a, size_b); above mean -> negate."""
    result: Dict[str, List[Order]] = {asset_a: [], asset_b: []}

    depth_a = state.order_depths.get(asset_a)
    depth_b = state.order_depths.get(asset_b)
    if depth_a is None or depth_b is None:
        return result

    mid_a = _mid(depth_a)
    mid_b = _mid(depth_b)
    if mid_a is None or mid_b is None:
        return result

    sign_b = 1 if size_b >= 0 else -1
    spread = mid_a + sign_b * beta * mid_b
    deviation = spread - mean

    if deviation < -threshold:
        target_a, target_b = size_a, size_b
    elif deviation > threshold:
        target_a, target_b = -size_a, -size_b
    else:
        target_a, target_b = 0, 0

    logger.print(f"{asset_a}/{asset_b} spread:", spread, "deviation:", deviation,
                 "targets:", target_a, target_b)

    pos_a = state.position.get(asset_a, 0)
    pos_b = state.position.get(asset_b, 0)
    result[asset_a] = _sweep_to(asset_a, target_a, pos_a, depth_a)
    result[asset_b] = _sweep_to(asset_b, target_b, pos_b, depth_b)
    return result


class Trader:
    PAIRS = [
        {
            "asset_a": "MICROCHIP_OVAL",
            "asset_b": "MICROCHIP_TRIANGLE",
            "beta": 1.62,
            "mean": -7500,
            "threshold": 350,
            "size_a": 6,
            "size_b": -10,
        },
        # {
        #     "asset_a": "SLEEP_POD_LAMB_WOOL",
        #     "asset_b": "SLEEP_POD_NYLON",
        #     "beta": 0.6,
        #     "mean": 4934,
        #     "threshold": 500,
        #     "size_a": 10,
        #     "size_b": -6,
        # },
        {
            "asset_a": "MICROCHIP_SQUARE",
            "asset_b": "MICROCHIP_RECTANGLE",
            "beta": 2.14,
            "mean": 32000,  
            "threshold": 350,
            "size_a": 5,
            "size_b": 10,
        },
    ]

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        for cfg in self.PAIRS:
            result.update(pair_trade(state, **cfg))

        logger.flush(state, result, 0, "")
        return result, 0, ""
