from datamodel import Order, TradingState
from pathlib import Path
from typing import Any, Dict, List
import json

try:
    from prosperity4bt import data as p4bt_data
    from prosperity4bt.file_reader import PackageResourcesReader, wrap_in_context_manager

    if not hasattr(PackageResourcesReader, "_round5_patched"):
        _orig_file = PackageResourcesReader.file
        _repo_root = Path(__file__).resolve().parents[1]
        _data_root = _repo_root / "data"

        def _patched_file(self, path_parts: list[str]):
            if path_parts and path_parts[0] == "round5":
                file = _data_root
                for part in path_parts:
                    file = file / part
                if file.is_file():
                    return wrap_in_context_manager(file)
            return _orig_file(self, path_parts)

        PackageResourcesReader.file = _patched_file
        PackageResourcesReader._round5_patched = True

    p4bt_data.LIMITS.update(
        {
            "SNACKPACK_CHOCOLATE": 10,
            "SNACKPACK_VANILLA": 10,
            "SNACKPACK_PISTACHIO": 10,
            "SNACKPACK_RASPBERRY": 10,
            "SNACKPACK_STRAWBERRY": 10,
        }
    )
except Exception:
    pass


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
    PRODUCT = "SNACKPACK_PISTACHIO"
    POSITION_LIMIT = 10

    PARAMS = {
        "quote_size": 10,
        "min_spread": 2,
        "unwind_size": 2,
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {self.PRODUCT: []}
        logger.print("positions:", state.position)

        result[self.PRODUCT] = self.market_make_product(state)

        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def market_make_product(self, state: TradingState) -> List[Order]:
        depth = state.order_depths.get(self.PRODUCT)
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            return []

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        spread = best_ask - best_bid
        position = state.position.get(self.PRODUCT, 0)

        quote_size = self.PARAMS["quote_size"]
        min_spread = self.PARAMS["min_spread"]
        unwind_size = self.PARAMS["unwind_size"]

        orders: List[Order] = []

        if spread >= min_spread:
            bid_price = best_bid + 1
            ask_price = best_ask - 1

            buy_room = max(0, self.POSITION_LIMIT - position)
            sell_room = max(0, self.POSITION_LIMIT + position)

            bid_size = min(quote_size, buy_room)
            ask_size = min(quote_size, sell_room)

            if bid_size > 0:
                orders.append(buy(self.PRODUCT, bid_price, bid_size))
            if ask_size > 0:
                orders.append(sell(self.PRODUCT, ask_price, ask_size))
        else:
            if position > 0:
                unwind = min(unwind_size, position)
                orders.append(sell(self.PRODUCT, best_bid, unwind))
            elif position < 0:
                unwind = min(unwind_size, -position)
                orders.append(buy(self.PRODUCT, best_ask, unwind))

        logger.print(
            self.PRODUCT,
            "bid=",
            best_bid,
            "ask=",
            best_ask,
            "spread=",
            spread,
            "position=",
            position,
            "orders=",
            [(order.price, order.quantity) for order in orders],
        )
        return orders
