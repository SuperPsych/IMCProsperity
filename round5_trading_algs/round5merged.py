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


# ---------------------------------------------------------------------------
# Sleep pods: penny with optional intraday momentum overlay
# ---------------------------------------------------------------------------

SLEEP_POD_LIMIT = 10
SLEEP_POD_MIN_SPREAD = 6
SLEEP_POD_FADE_TICKS = 3
SLEEP_POD_TARGET_POS = 4

SLEEP_PODS = {
    "SLEEP_POD_COTTON",
    "SLEEP_POD_NYLON",
    "SLEEP_POD_POLYESTER",
    "SLEEP_POD_SUEDE",
    # LAMB_WOOL excluded — basket allocation too small, bleeds at any bias.
}

# Per-pod momentum size: when non-zero, replaces the static long bias with
# target = ±SIZE based on intraday drift vs day-open mid.
SLEEP_POD_MOMENTUM = {
    "SLEEP_POD_NYLON": 10,
}


def sleep_pod_penny(
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


# ---------------------------------------------------------------------------
# Galaxy sounds: penny vs wall-mid with linear position fade
# ---------------------------------------------------------------------------

GALAXY_PRODUCTS = [
    "GALAXY_SOUNDS_DARK_MATTER",
    "GALAXY_SOUNDS_BLACK_HOLES",
    "GALAXY_SOUNDS_PLANETARY_RINGS",
    "GALAXY_SOUNDS_SOLAR_WINDS",
    "GALAXY_SOUNDS_SOLAR_FLAMES",
]

GALAXY_LIMIT: Dict[str, int] = {p: 10 for p in GALAXY_PRODUCTS}

GALAXY_PARAMS = {
    "spread_thresh": 6,  # min ticks of edge each penny quote needs vs the wall-mid fair
    "fade": 0.2,         # fair -= fade * position
}


# ---------------------------------------------------------------------------
# Microchip pair trading: mean-revert spread between two assets
# ---------------------------------------------------------------------------

MICROCHIP_PAIRS = [
    {
        "asset_a": "MICROCHIP_OVAL",
        "asset_b": "MICROCHIP_TRIANGLE",
        "beta": 1.62,
        "mean": -7500,
        "threshold": 350,
        "size_a": 6,
        "size_b": -10,
    },
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


def _sweep_to(product: str, target: int, position: int, depth: OrderDepth) -> List[Order]:
    """Walk the book and place orders at every level until position reaches target."""
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


# ---------------------------------------------------------------------------
# Pebbles: penny with drift bias and inventory skew
# ---------------------------------------------------------------------------

PEBBLES_PARAMS: Dict[str, Dict[str, float]] = {
    "PEBBLES_XL": {
        "edge_pct": 0.04,
        "inventory_skew": 0.2,
        "drift_bias": 3,
        "target_position": 0,
    },
    "PEBBLES_XS": {
        "edge_pct": 0.04,
        "inventory_skew": 0.1,
        "drift_bias": -3,
        "target_position": 0,
    },
    "PEBBLES_S": {
        "edge_pct": 0.06,
        "inventory_skew": 0.05,
        "drift_bias": -1.5,
        "target_position": 0,
    },
    "PEBBLES_L": {
        "edge_pct": 0.06,
        "inventory_skew": 0.05,
        "drift_bias": 1.5,
        "target_position": 0,
    },
}

PEBBLES_PRODUCTS = list(PEBBLES_PARAMS.keys())
PEBBLES_LIMIT: Dict[str, int] = {p: 10 for p in PEBBLES_PRODUCTS}


# ---------------------------------------------------------------------------
# Robot dishes: spike reversal
# ---------------------------------------------------------------------------

ROBOT_PARAMS = {
    "PENNY_AMOUNT": 3,
    "MIN_SPREAD_THRESHOLD": 7,
    "ROBOT_MASSIVE_SPIKE_THRESH": 90,
}

ROBOT_LIMIT = 10


def _take_to_target(product: str, buy_orders, sell_orders, pos: int, target: int) -> List[Order]:
    if target is None:
        return []
    delta = target - pos
    if delta == 0:
        return []
    orders: List[Order] = []
    if delta > 0:
        remaining = delta
        for price, volume in sorted(sell_orders.items()):
            available = abs(volume)
            qty = min(remaining, available)
            if qty <= 0:
                continue
            orders.append(buy(product, price, qty))
            remaining -= qty
            if remaining <= 0:
                break
    else:
        remaining = abs(delta)
        for price, volume in sorted(buy_orders.items(), reverse=True):
            available = abs(volume)
            qty = min(remaining, available)
            if qty <= 0:
                continue
            orders.append(sell(product, price, qty))
            remaining -= qty
            if remaining <= 0:
                break
    return orders


# ---------------------------------------------------------------------------
# Combined trader
# ---------------------------------------------------------------------------

class Trader:
    def __init__(self) -> None:
        # sleep_pod day-rollover state
        self.sleep_pod_day_open: Dict[str, float] = {}
        self.last_ts: int | None = None
        # robot_dishes spike detection state
        self.prev_robot_dish_price: float | None = None

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        logger.print("positions:", state.position)

        # Day rollover: timestamps reset to 0 each day.
        if self.last_ts is not None and state.timestamp < self.last_ts:
            self.sleep_pod_day_open = {}
        self.last_ts = state.timestamp

        self._trade_sleep_pods(state, result)
        self._trade_galaxy(state, result)
        self._trade_microchips(state, result)
        self._trade_pebbles(state, result)
        self._trade_robot_dishes(state, result)

        logger.flush(state, result, 0, "")
        return result, 0, ""

    # -- sleep pods --------------------------------------------------------

    def _trade_sleep_pods(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        for product, depth in state.order_depths.items():
            if product not in SLEEP_PODS:
                continue
            position = state.position.get(product, 0)

            mid = _mid(depth)
            if mid is not None and product not in self.sleep_pod_day_open:
                self.sleep_pod_day_open[product] = mid

            mom_size = SLEEP_POD_MOMENTUM.get(product, 0)
            if mom_size > 0:
                target = 0
                open_px = self.sleep_pod_day_open.get(product)
                if mid is not None and open_px is not None:
                    if mid > open_px:
                        target = mom_size
                    elif mid < open_px:
                        target = -mom_size
            else:
                target = SLEEP_POD_TARGET_POS

            orders = sleep_pod_penny(
                product, depth, position,
                SLEEP_POD_LIMIT, SLEEP_POD_MIN_SPREAD, SLEEP_POD_FADE_TICKS, target,
            )
            if orders:
                result[product] = orders

    # -- galaxy sounds -----------------------------------------------------

    def _trade_galaxy(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        spread_thresh = GALAXY_PARAMS["spread_thresh"]
        fade = GALAXY_PARAMS["fade"]

        for product in GALAXY_PRODUCTS:
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

            if bid_2 is None or ask_2 is None:
                result[product] = orders
                continue
            fair = (bid_2 + ask_2) / 2

            limit = GALAXY_LIMIT[product]
            position = state.position.get(product, 0)
            fair -= fade * position

            if (best_bid is not None
                    and (fair - (best_bid + 1)) >= spread_thresh
                    and position < limit):
                orders.append(buy(product, best_bid + 1, limit - position))

            if (best_ask is not None
                    and ((best_ask - 1) - fair) >= spread_thresh
                    and position > -limit):
                orders.append(sell(product, best_ask - 1, limit + position))

            result[product] = orders

    # -- microchip pairs ---------------------------------------------------

    def _trade_microchips(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        for cfg in MICROCHIP_PAIRS:
            result.update(pair_trade(state, **cfg))

    # -- pebbles -----------------------------------------------------------

    def _trade_pebbles(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        for product in PEBBLES_PRODUCTS:
            p = PEBBLES_PARAMS[product]
            edge_pct = p["edge_pct"]
            inventory_skew = p["inventory_skew"]
            drift_bias = p["drift_bias"]
            target_position = p["target_position"]

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

            if bid_2 is None or ask_2 is None:
                result[product] = orders
                continue
            mid = (bid_2 + ask_2) / 2

            limit = PEBBLES_LIMIT[product]
            position = state.position.get(product, 0)
            fair = mid + drift_bias - inventory_skew * (position - target_position)

            if (best_bid is not None
                    and (fair - (best_bid + 1)) / fair * 100 >= edge_pct
                    and position < limit):
                orders.append(buy(product, best_bid + 1, limit - position))

            if (best_ask is not None
                    and ((best_ask - 1) - fair) / fair * 100 >= edge_pct
                    and position > -limit):
                orders.append(sell(product, best_ask - 1, limit + position))

            result[product] = orders

    # -- robot dishes ------------------------------------------------------

    def _trade_robot_dishes(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        product = "ROBOT_DISHES"
        depth = state.order_depths.get(product)
        if depth is None:
            return

        buy_orders = depth.buy_orders
        sell_orders = depth.sell_orders
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        if best_bid is None or best_ask is None:
            return

        pos = state.position.get(product, 0)
        mid = (best_bid + best_ask) / 2
        prev_mid = self.prev_robot_dish_price
        spike = ROBOT_PARAMS["ROBOT_MASSIVE_SPIKE_THRESH"]

        orders: List[Order] = []
        if prev_mid is not None:
            if mid - prev_mid >= spike:
                orders.extend(_take_to_target(product, buy_orders, sell_orders, pos, -ROBOT_LIMIT))
            elif prev_mid - mid >= spike:
                orders.extend(_take_to_target(product, buy_orders, sell_orders, pos, ROBOT_LIMIT))
        self.prev_robot_dish_price = mid

        if orders:
            result[product] = orders
