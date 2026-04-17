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
    fair: float,
    edge: int,
    position: int,
    limit: int,
) -> List[Order]:
    """Place orders 1 tick inside the spread if the price is at least `edge` ticks better than fair."""
    orders: List[Order] = []
    if best_bid is not None and best_bid + 1 <= fair - edge and position < limit:
        orders.append(buy(product, best_bid + 1, limit - position))
    if best_ask is not None and best_ask - 1 >= fair + edge and position > -limit:
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


def spike_take(
    product: str,
    best_bid: int | None,
    best_bid_amount: int | None,
    best_ask: int | None,
    best_ask_quantity: int | None,
    prev_bid: int | None,
    prev_ask: int | None,
    position: int,
    spike_thresh: int = 10,
) -> List[Order]:
    """Take on price spikes. Sell into bid spikes (long only), buy into ask spikes (short only)."""
    orders: List[Order] = []
    if prev_bid is None or prev_ask is None or best_bid is None or best_ask is None:
        return orders

    bid_diff = best_bid - prev_bid
    ask_diff = best_ask - prev_ask

    # Bid spike: bid jumped up, and bid moved more than ask
    if bid_diff >= spike_thresh and bid_diff - ask_diff >= spike_thresh and position > 0:
        qty = min(position, best_bid_amount)
        if qty > 0:
            orders.append(sell(product, best_bid, qty))

    # Ask spike: ask dropped down, and ask moved more than bid
    if ask_diff <= -spike_thresh and bid_diff - ask_diff >= spike_thresh and position < 0:
        qty = min(-position, -best_ask_quantity)
        if qty > 0:
            orders.append(buy(product, best_ask, qty))

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

    MA_WINDOW = 10

    def __init__(self) -> None:
        self.strategies: Dict[str, Callable[[str, TradingState], List[Order]]] = {
            "EMERALDS": self._trade_emeralds,
            "TOMATOES": self._trade_tomatoes,
            "INTARIAN_PEPPER_ROOT": self._trade_pepper,
            "ASH_COATED_OSMIUM": self._trade_osmium,
        }
        self.price_history: Dict[str, List[List[int | None]]] = {}
        self.mid_history: Dict[str, List[float]] = {}
        self.initial_fair: Dict[str, float | None] = {}
        # running sums for O(1) linear regression: y = a + b*x, x = step index
        self.linreg: Dict[str, Dict[str, float]] = {}

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

        best_ask, _ = asks[0] if asks else (None, None)
        best_bid, _ = bids[0] if bids else (None, None)

        limit = self.POSITION_LIMITS.get(product, 80)

        # --- parameters ---
        PARAMS = {
            "base_fair": 10_000,
            "alpha": 0.075,       # fair adjustment per unit of position (fair -= alpha * position)
            "edge": 0,            # minimum ticks of edge vs fair required to post a quote
            "half_width": 8,
            "take_edge": 0.6,
        }
        base_fair = PARAMS["base_fair"]
        alpha = PARAMS["alpha"]
        edge = PARAMS["edge"]
        half_width = PARAMS["half_width"]
        take_edge = PARAMS["take_edge"]

        # Blend base_fair (70%) with recent mid price (30%) for better quote placement
        mid_hist = self.mid_history.get(product, [])
        recent_mid = mid_hist[-1] if mid_hist else base_fair
        fair = 0.70 * base_fair + 0.30 * recent_mid - alpha * position

        # take when good to fair by at least take_edge — sweep all book levels
        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > fair - take_edge or position >= limit:
                break
            qty = min(limit - position, -order_depth.sell_orders[ask_price])
            if qty > 0:
                orders.append(buy(product, ask_price, qty))
                position += qty
        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < fair + take_edge or position <= -limit:
                break
            qty = min(limit + position, order_depth.buy_orders[bid_price])
            if qty > 0:
                orders.append(sell(product, bid_price, qty))
                position -= qty

        # fill missing side with moving average for market making only
        mm_bid, mm_ask = best_bid, best_ask
        ma = self._moving_avg(product)
        if mm_bid is None and ma is not None:
            mm_bid = int(min(ma - half_width, fair - half_width))
        if mm_ask is None and ma is not None:
            mm_ask = int(max(ma + half_width, fair + half_width))

        # penny the spread
        orders.extend(penny(product, mm_bid, mm_ask, fair,
                            edge, position, limit))

        self._update_mid(product, best_bid, best_ask)
        last_bid, last_ask = self._previous_bbo(product)
        stored_bid = best_bid if best_bid is not None else last_bid
        stored_ask = best_ask if best_ask is not None else last_ask
        self.price_history.setdefault(product, []).append([stored_bid, stored_ask])
        return orders

    def _previous_bbo(self, product: str) -> Tuple[int | None, int | None]:
        if self.price_history.get(product):
            return tuple(self.price_history[product][-1])
        return None, None

    def _update_mid(self, product: str, best_bid: int | None, best_ask: int | None) -> None:
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2
            self.mid_history.setdefault(product, []).append(mid)

    def _moving_avg(self, product: str) -> float | None:
        history = self.mid_history.get(product, [])
        if not history:
            return None
        window = history[-self.MA_WINDOW:]
        return sum(window) / len(window)

    def _update_linreg(self, product: str, mid: float) -> None:
        s = self.linreg.setdefault(product, {"n": 0, "sx": 0.0, "sy": 0.0, "sxx": 0.0, "sxy": 0.0})
        x = float(s["n"])
        s["n"] += 1
        s["sx"] += x
        s["sy"] += mid
        s["sxx"] += x * x
        s["sxy"] += x * mid

    def _linreg_fair(self, product: str) -> float | None:
        s = self.linreg.get(product)
        if s is None or s["n"] < 2:
            return None
        n, sx, sy, sxx, sxy = s["n"], s["sx"], s["sy"], s["sxx"], s["sxy"]
        denom = n * sxx - sx * sx
        if denom == 0:
            return sy / n  # all same x — return mean
        b = (n * sxy - sx * sy) / denom
        a = (sy - b * sx) / n
        return a + b * n  # predict at next step index

    def _estimate_initial_fair(self, product: str, order_depth: OrderDepth) -> float | None:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2
        elif best_bid is not None:
            mid = best_bid
        elif best_ask is not None:
            mid = best_ask
        else:
            return None
        return round(mid / 1000) * 1000

    def _pepper_fair(self, product: str, state: TradingState) -> float | None:
        """Prior fair = initial_mid (rounded to 1000) + 0.1 per tick."""
        if product not in self.initial_fair:
            estimate = self._estimate_initial_fair(product, state.order_depths[product])
            if estimate is None:
                return None
            self.initial_fair[product] = estimate
        return 0.1 * (state.timestamp / 100) + self.initial_fair[product]

    def _run_pepper_strategy(self, product: str, state: TradingState) -> List[Order]:
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)
        limit = self.POSITION_LIMITS.get(product, 80)

        # --- parameters ---
        PEPPER_CFG = {
            "reserve": 8,
            "take_edge": 1.0,       # min ticks of edge vs fair to take
            "alpha": 0.1,           # fair -= alpha * excess position above core_target
            "mm_edge": 4,           # post passive quote when price is good to fair by at least this many ticks
        }
        reserve = PEPPER_CFG["reserve"]
        take_edge = PEPPER_CFG["take_edge"]
        alpha = PEPPER_CFG["alpha"]
        mm_edge = PEPPER_CFG["mm_edge"]

        core_target = limit - reserve

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_ask, best_ask_quantity = asks[0] if asks else (None, None)
        best_bid, best_bid_quantity = bids[0] if bids else (None, None)

        # prior fair: initial_mid (rounded to 1000) + 0.1 per tick
        prior_fair = self._pepper_fair(product, state)
        if prior_fair is None:
            self.price_history.setdefault(product, []).append([
                bids[0][0] if bids else None,
                asks[0][0] if asks else None,
            ])
            return orders

        # update linreg with residuals (actual mid - prior) so it learns the correction
        if best_bid is not None and best_ask is not None:
            self._update_linreg(product, (best_bid + best_ask) / 2)

        # linreg adjustment: how much the actual price deviates from the prior
        linreg_fair = self._linreg_fair(product)
        if linreg_fair is not None:
            fair = linreg_fair
        else:
            fair = prior_fair

        # adjust fair down based on excess position (more willing to sell when long)
        excess = max(0, position - core_target)
        fair -= alpha * excess

        # aggressive accumulation up to core_target — sweep all ask levels within ceiling
        aa_ceiling = fair + 8
        buy_capacity = max(0, core_target - position)
        for ask_price, ask_qty in asks:
            if buy_capacity <= 0 or ask_price > aa_ceiling:
                break
            size = min(buy_capacity, -ask_qty)
            if size > 0:
                orders.append(Order(product, ask_price, size))
                buy_capacity -= size
                position += size

        # taking: sweep all book levels within take_edge of fair
        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > fair - take_edge or position >= limit:
                break
            qty = min(limit - position, -order_depth.sell_orders[ask_price])
            if qty > 0:
                orders.append(buy(product, ask_price, qty))
                position += qty
        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < fair + take_edge or position <= core_target:
                break
            qty = min(position - core_target, order_depth.buy_orders[bid_price])
            if qty > 0:
                orders.append(sell(product, bid_price, qty))
                position -= qty

        # market making: post 1 tick inside spread when quote is at least mm_edge better than fair
        if best_bid is not None and best_bid + 1 <= fair - mm_edge and position < limit:
            orders.append(buy(product, best_bid + 1, limit - position))
        if best_ask is not None and best_ask - 1 >= fair + mm_edge and position > core_target:
            orders.append(sell(product, best_ask - 1, position - core_target))

        self.price_history.setdefault(product, []).append([
            bids[0][0] if bids else None,
            asks[0][0] if asks else None,
        ])
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
