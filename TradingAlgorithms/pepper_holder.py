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


def penny(
    product: str,
    best_bid: int | None,
    best_ask: int | None,
    fair: int,
    spread_thresh: int,
    position: int,
    limit: int,
) -> List[Order]:
    orders: List[Order] = []
    spread = best_ask - best_bid if (best_ask is not None and best_bid is not None) else 0
    if spread >= spread_thresh:
        if best_bid + 1 < fair and position < limit:
            orders.append(buy(product, best_bid + 1, limit - position))
        if best_ask - 1 > fair and position > -limit:
            orders.append(sell(product, best_ask - 1, limit + position))
    return orders


def market_take(
    product: str,
    best_bid: int | None,
    best_bid_quantity: int | None,
    best_ask: int | None,
    best_ask_quantity: int | None,
    fair: int,
    position: int,
) -> List[Order]:
    orders: List[Order] = []
    if best_ask is not None and best_ask <= fair and position < 0:
        qty = min(-position, -best_ask_quantity)
        orders.append(buy(product, best_ask, qty))
    if best_bid is not None and best_bid >= fair and position > 0:
        qty = min(position, best_bid_quantity)
        orders.append(sell(product, best_bid, qty))
    return orders


class Trader:
    TRADED_PRODUCTS = {
        "EMERALDS",
        "TOMATOES",
        "INTARIAN_PEPPER_ROOT",
        "ASH_COATED_OSMIUM",
    }

    POSITION_LIMITS: Dict[str, int] = {
        "EMERALDS": 80,
        "TOMATOES": 80,
        "INTARIAN_PEPPER_ROOT": 80,
        "ASH_COATED_OSMIUM": 80,
    }

    FAIR_VALUES: Dict[str, int] = {
        "EMERALDS": 10_000,
        "ASH_COATED_OSMIUM": 10_000,
    }

    ENABLE_STRATEGY: Dict[str, bool] = {
        "EMERALDS": False,
        "TOMATOES": False,
        "INTARIAN_PEPPER_ROOT": True,
        "ASH_COATED_OSMIUM": True,
    }

    def __init__(self) -> None:
        self.strategies: Dict[str, Callable[[str, TradingState], List[Order]]] = {
            "EMERALDS": self._trade_emeralds,
            "TOMATOES": self._trade_tomatoes,
            "INTARIAN_PEPPER_ROOT": self._trade_pepper,
            "ASH_COATED_OSMIUM": self._trade_osmium,
        }
        self.price_history: Dict[str, List[List[int | None]]] = {}

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        #logger.print("timestamp:", state.timestamp)
        logger.print("positions:", state.position)

        for product in self.TRADED_PRODUCTS:
            if product not in state.order_depths:
                continue
            strategy = self.strategies.get(product, self._trade_default)
            result[product] = strategy(product, state)

        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def _trade_default(self, product: str, state: TradingState) -> List[Order]:
        return []

    def _trade_emeralds(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        return []

    def _trade_tomatoes(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        return []

    def _trade_pepper(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        return self._run_pepper_strategy(product, state)

    def _trade_osmium(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_ask, best_ask_quantity = asks[0] if asks else (None, None)
        best_bid, best_bid_quantity = bids[0] if bids else (None, None)

        limit = self.POSITION_LIMITS.get(product, 80)
        fair = 10_000
        spread_thresh = 16

        take_orders = market_take(
            product,
            best_bid,
            best_bid_quantity,
            best_ask,
            best_ask_quantity,
            fair,
            position,
        )
        for order in take_orders:
            position += order.quantity
        orders.extend(take_orders)

        orders.extend(
            penny(
                product,
                best_bid,
                best_ask,
                fair,
                spread_thresh,
                position,
                limit,
            )
        )

        self.price_history.setdefault(product, []).append([best_bid, best_ask])
        return orders

    def _previous_bbo(self, product: str) -> Tuple[int | None, int | None]:
        if self.price_history.get(product):
            return tuple(self.price_history[product][-1])
        return None, None

    def _run_pepper_strategy(self, product: str, state: TradingState) -> List[Order]:
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)
        limit = self.POSITION_LIMITS.get(product, 80)
        reserve = 8
        spread_market_thresh = 12
        spike_thresh = 9
        spread_take_thresh = 3
        core_target = limit - reserve
        buy_capacity = max(0, core_target - position)

        for ask_price in sorted(order_depth.sell_orders):
            if buy_capacity <= 0:
                break

            ask_volume = -order_depth.sell_orders[ask_price]
            size = min(buy_capacity, ask_volume)

            if size > 0:
                orders.append(Order(product, ask_price, size))
                buy_capacity -= size
                position += size

        prev_bid, prev_ask = self._previous_bbo(product)
        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_ask, best_ask_quantity = asks[0] if asks else (None, None)
        best_bid, best_bid_quantity = bids[0] if bids else (None, None)
        spread = best_ask - best_bid if (best_ask is not None and best_bid is not None) else 0

        # market taking10
        if spread <= spread_take_thresh:
            if (
                best_ask is not None
                and prev_ask is not None
                and prev_ask - best_ask >= spike_thresh
                and position < limit
            ):
                qty = min(limit - position, -best_ask_quantity)
                if qty > 0:
                    orders.append(buy(product, best_ask, qty))
                    position += qty

            if (
                best_bid is not None
                and prev_bid is not None
                and best_bid - prev_bid >= spike_thresh
                and position > core_target
            ):
                qty = min(position - core_target, best_bid_quantity)
                if qty > 0:
                    orders.append(sell(product, best_bid, qty))
                    position -= qty

        # market making
        if spread >= spread_market_thresh and best_bid is not None and best_ask is not None:
            if position < limit:
                orders.append(buy(product, best_bid + 1, limit - position))
            if position > core_target:
                orders.append(sell(product, best_ask - 1, position - core_target))

        self.price_history.setdefault(product, []).append([best_bid, best_ask])
        return orders
    def _fair_value(self, product: str, order_depth: OrderDepth) -> int | None:
        if product in self.FAIR_VALUES:
            return self.FAIR_VALUES[product]

        best_bid, best_ask = self._best_bid_ask(order_depth)
        if best_bid is None and best_ask is None:
            return None
        if best_bid is None:
            return best_ask
        if best_ask is None:
            return best_bid
        return (best_bid + best_ask) // 2

    def _best_bid_ask(self, order_depth: OrderDepth) -> Tuple[int | None, int | None]:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        return best_bid, best_ask

    def _take_edges(
        self,
        product: str,
        order_depth: OrderDepth,
        fair: int,
        orders: List[Order],
        buy_capacity: int,
        sell_capacity: int,
    ) -> Tuple[int, int]:
        for ask_price in sorted(order_depth.sell_orders):
            if ask_price >= fair or buy_capacity <= 0:
                break
            ask_volume = -order_depth.sell_orders[ask_price]
            size = min(buy_capacity, ask_volume)
            if size > 0:
                orders.append(Order(product, ask_price, size))
                buy_capacity -= size

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price <= fair or sell_capacity <= 0:
                break
            bid_volume = order_depth.buy_orders[bid_price]
            size = min(sell_capacity, bid_volume)
            if size > 0:
                orders.append(Order(product, bid_price, -size))
                sell_capacity -= size

        return buy_capacity, sell_capacity

    def _place_passive_quotes(
        self,
        product: str,
        order_depth: OrderDepth,
        fair: int,
        orders: List[Order],
        buy_capacity: int,
        sell_capacity: int,
    ) -> None:
        best_bid, best_ask = self._best_bid_ask(order_depth)

        bid_quote = fair - 1
        ask_quote = fair + 1

        if best_bid is not None:
            bid_quote = min(fair - 1, best_bid + 1)
        if best_ask is not None:
            ask_quote = max(fair + 1, best_ask - 1)

        if buy_capacity > 0:
            orders.append(Order(product, bid_quote, max(1, buy_capacity // 4)))

        if sell_capacity > 0:
            orders.append(Order(product, ask_quote, -max(1, sell_capacity // 4)))
