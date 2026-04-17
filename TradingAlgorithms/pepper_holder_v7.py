from datamodel import Order, OrderDepth, TradingState
from typing import Any, Callable, Dict, List, Tuple
import json


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    @staticmethod
    def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in d.items():
            key = f"{prefix}_{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(Logger._flatten(v, key))
            else:
                out[key] = v
        return out

    def flush(
        self,
        state: TradingState,
        orders,
        conversions: int,
        trader_data: str,
        internal_state: Dict[str, Dict[str, Any]] | None = None,
    ) -> None:
        internal_state = internal_state or {}
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
            row.update(Logger._flatten(internal_state.get(symbol, {})))

            print(json.dumps(row, default=str))

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
        # running sums for O(1) linear regression: y = a + b*x, x = step index
        self.linreg: Dict[str, Dict[str, float]] = {}
        # per-product snapshot of variables driving this tick's trading decision
        self.internal_state: Dict[str, Dict[str, Any]] = {}

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        self.internal_state = {}
        #logger.print("timestamp:", state.timestamp)
        logger.print("positions:", state.position)

        for product in self.TRADED_PRODUCTS:
            if product not in state.order_depths:
                continue
            strategy = self.strategies.get(product, self._trade_default)
            result[product] = strategy(product, state)

        conversions = 0
        trader_data = ""
        logger.flush(state, result, conversions, trader_data, self.internal_state)
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
        start_position = position

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_ask, best_ask_quantity = asks[0] if asks else (None, None)
        best_bid, best_bid_quantity = bids[0] if bids else (None, None)

        limit = self.POSITION_LIMITS.get(product, 80)

        # --- parameters ---
        OS_CFG = {
            "base_fair": 10_000,
            "alpha": 0.125,       # fair adjustment per unit of position (fair -= alpha * position)
            "edge": 0.5,          # minimum ticks of edge vs fair required to post a quote
            "half_width": 8,
            "take_edge": 1.5,
        }
        base_fair = OS_CFG["base_fair"]
        alpha = OS_CFG["alpha"]
        edge = OS_CFG["edge"]
        half_width = OS_CFG["half_width"]
        take_edge = OS_CFG["take_edge"]

        pos_adj = -alpha * position
        fair = base_fair + pos_adj

        take_buy_qty = 0
        take_sell_qty = 0

        # take when good to fair by at least take_edge
        if best_ask is not None and best_ask_quantity is not None and fair - best_ask >= take_edge and position < limit:
            qty = min(limit - position, -best_ask_quantity)
            if qty > 0:
                orders.append(buy(product, best_ask, qty))
                position += qty
                take_buy_qty = qty
        if best_bid is not None and best_bid_quantity is not None and best_bid - fair >= take_edge and position > -limit:
            qty = min(limit + position, best_bid_quantity)
            if qty > 0:
                orders.append(sell(product, best_bid, qty))
                position -= qty
                take_sell_qty = qty

        # fill missing side with moving average for market making only
        mm_bid, mm_ask = best_bid, best_ask
        mm_bid_synth = False
        mm_ask_synth = False
        ma = self._moving_avg(product)
        if mm_bid is None and ma is not None:
            mm_bid = int(min(ma - half_width, fair - half_width))
            mm_bid_synth = True
        if mm_ask is None and ma is not None:
            mm_ask = int(max(ma + half_width, fair + half_width))
            mm_ask_synth = True

        # penny the spread
        penny_orders = penny(product, mm_bid, mm_ask, fair, edge, position, limit)
        penny_buy = next((o for o in penny_orders if o.quantity > 0), None)
        penny_sell = next((o for o in penny_orders if o.quantity < 0), None)
        orders.extend(penny_orders)

        self._update_mid(product, best_bid, best_ask)
        last_bid, last_ask = self._previous_bbo(product)
        stored_bid = best_bid if best_bid is not None else last_bid
        stored_ask = best_ask if best_ask is not None else last_ask
        self.price_history.setdefault(product, []).append([stored_bid, stored_ask])

        self.internal_state[product] = {
            "params": OS_CFG,
            "limit": limit,
            "position_start": start_position,
            "position_end": position,
            "best_bid": best_bid,
            "best_bid_qty": best_bid_quantity,
            "best_ask": best_ask,
            "best_ask_qty": best_ask_quantity,
            "mid": (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None,
            "base_fair": base_fair,
            "pos_adj": pos_adj,
            "fair": fair,
            "buy_zone_max": fair - take_edge,
            "sell_zone_min": fair + take_edge,
            "ma": ma,
            "mm_bid": mm_bid,
            "mm_ask": mm_ask,
            "mm_bid_synth": mm_bid_synth,
            "mm_ask_synth": mm_ask_synth,
            "take_buy_qty": take_buy_qty,
            "take_sell_qty": take_sell_qty,
            "penny_buy": {"price": penny_buy.price, "qty": penny_buy.quantity} if penny_buy else None,
            "penny_sell": {"price": penny_sell.price, "qty": penny_sell.quantity} if penny_sell else None,
            "orders_emitted": len(orders),
        }
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
        components = self._linreg_components(product)
        if components is None:
            return None
        return components["predicted"]

    def _linreg_components(self, product: str) -> Dict[str, float] | None:
        """Return dict with intercept (a), slope (b), n, and next-step prediction, or None."""
        s = self.linreg.get(product)
        if s is None or s["n"] < 2:
            return None
        n, sx, sy, sxx, sxy = s["n"], s["sx"], s["sy"], s["sxx"], s["sxy"]
        denom = n * sxx - sx * sx
        if denom == 0:
            mean = sy / n
            return {"n": n, "intercept": mean, "slope": 0.0, "predicted": mean}
        b = (n * sxy - sx * sy) / denom
        a = (sy - b * sx) / n
        return {"n": n, "intercept": a, "slope": b, "predicted": a + b * n}

    def _run_pepper_strategy(self, product: str, state: TradingState) -> List[Order]:
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)
        start_position = position
        limit = self.POSITION_LIMITS.get(product, 80)

        # --- parameters ---
        PARAMS = {
            "reserve": 8,
            "take_edge": 2,   # take when price is good to fair by at least this many ticks
            "mm_edge": 4,     # post passive quote when price is good to fair by at least this many ticks
            "limit_fade": 3,  # fair -= pepper_fade * (position - core_target) when over core_target
        }
        reserve = PARAMS["reserve"]
        take_edge = PARAMS["take_edge"]
        mm_edge = PARAMS["mm_edge"]
        limit_fade = PARAMS["limit_fade"]

        core_target = limit - reserve

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_ask, best_ask_quantity = asks[0] if asks else (None, None)
        best_bid, best_bid_quantity = bids[0] if bids else (None, None)

        mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None

        # update linear regression with current mid price
        if mid is not None:
            self._update_linreg(product, mid)

        linreg = self._linreg_components(product)
        fair_raw = linreg["predicted"] if linreg is not None else None
        if fair_raw is None:
            self.price_history.setdefault(product, []).append([
                bids[0][0] if bids else None,
                asks[0][0] if asks else None,
            ])
            self.internal_state[product] = {
                "params": PARAMS,
                "limit": limit,
                "core_target": core_target,
                "position_start": start_position,
                "position_end": position,
                "best_bid": best_bid,
                "best_bid_qty": best_bid_quantity,
                "best_ask": best_ask,
                "best_ask_qty": best_ask_quantity,
                "mid": mid,
                "linreg": linreg,
                "fair_raw": None,
                "fair_final": None,
                "fade_applied": False,
                "aa_qty": 0,
                "take_buy_qty": 0,
                "take_sell_qty": 0,
                "mm_buy_qty": 0,
                "mm_sell_qty": 0,
                "orders_emitted": 0,
                "skipped_reason": "no_linreg_fit",
            }
            return orders

        # fade fair down when at limit
        fade_applied = position == limit
        fair = fair_raw - limit_fade if fade_applied else fair_raw

        # aggressive accumulation up to core_target (first level only)
        aa_qty = 0
        buy_capacity = max(0, core_target - position)
        if asks and buy_capacity > 0:
            size = min(buy_capacity, -best_ask_quantity)
            if size > 0:
                orders.append(Order(product, best_ask, size))
                buy_capacity -= size
                position += size
                aa_qty = size

        # taking: buy when ask is at least take_edge below fair,
        #         sell when bid is at least take_edge above fair
        take_buy_qty = 0
        take_sell_qty = 0
        if best_ask is not None and fair - best_ask >= take_edge and position < limit:
            qty = min(limit - position, -best_ask_quantity)
            if qty > 0:
                orders.append(buy(product, best_ask, qty))
                position += qty
                take_buy_qty = qty

        if best_bid is not None and best_bid - fair >= take_edge and position > core_target:
            qty = min(position - core_target, best_bid_quantity)
            if qty > 0:
                orders.append(sell(product, best_bid, qty))
                position -= qty
                take_sell_qty = qty

        # market making: post 1 tick inside spread when quote is at least mm_edge better than fair
        mm_buy_qty = 0
        mm_sell_qty = 0
        mm_buy_price = None
        mm_sell_price = None
        if best_bid is not None and best_bid + 1 <= fair - mm_edge and position < limit:
            mm_buy_qty = limit - position
            mm_buy_price = best_bid + 1
            orders.append(buy(product, mm_buy_price, mm_buy_qty))
        if best_ask is not None and best_ask - 1 >= fair + mm_edge and position > core_target:
            mm_sell_qty = position - core_target
            mm_sell_price = best_ask - 1
            orders.append(sell(product, mm_sell_price, mm_sell_qty))

        self.price_history.setdefault(product, []).append([
            bids[0][0] if bids else None,
            asks[0][0] if asks else None,
        ])

        self.internal_state[product] = {
            "params": PARAMS,
            "limit": limit,
            "core_target": core_target,
            "position_start": start_position,
            "position_end": position,
            "best_bid": best_bid,
            "best_bid_qty": best_bid_quantity,
            "best_ask": best_ask,
            "best_ask_qty": best_ask_quantity,
            "mid": mid,
            "linreg": linreg,
            "fair_raw": fair_raw,
            "fair_final": fair,
            "fade_applied": fade_applied,
            "buy_zone_max": fair - take_edge,
            "sell_zone_min": fair + take_edge,
            "mm_buy_threshold": fair - mm_edge,
            "mm_sell_threshold": fair + mm_edge,
            "aa_qty": aa_qty,
            "take_buy_qty": take_buy_qty,
            "take_sell_qty": take_sell_qty,
            "mm_buy_qty": mm_buy_qty,
            "mm_buy_price": mm_buy_price,
            "mm_sell_qty": mm_sell_qty,
            "mm_sell_price": mm_sell_price,
            "orders_emitted": len(orders),
        }
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
