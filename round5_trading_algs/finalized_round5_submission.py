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
# Liquid oxygen shakes: wall-mid market maker with positional fade (all 5)
# ---------------------------------------------------------------------------

OXYGEN_PRODUCTS = [
    "OXYGEN_SHAKE_CHOCOLATE",
    "OXYGEN_SHAKE_EVENING_BREATH",
    "OXYGEN_SHAKE_GARLIC",
    "OXYGEN_SHAKE_MINT",
    "OXYGEN_SHAKE_MORNING_BREATH",
]

OXYGEN_LIMIT_DICT: Dict[str, int] = {p: 10 for p in OXYGEN_PRODUCTS}

OXYGEN_DEFAULT_PARAMS = {
    "edge_pct": 0.055,
    "fade":     0.2,
}

OXYGEN_PARAMS: Dict[str, Dict[str, float]] = {
    "OXYGEN_SHAKE_CHOCOLATE":      OXYGEN_DEFAULT_PARAMS,
    "OXYGEN_SHAKE_EVENING_BREATH": OXYGEN_DEFAULT_PARAMS,
    "OXYGEN_SHAKE_GARLIC":         OXYGEN_DEFAULT_PARAMS,
    "OXYGEN_SHAKE_MINT":           {"edge_pct": 0.05, "fade": 0.2},
    "OXYGEN_SHAKE_MORNING_BREATH": {"edge_pct": 0.05, "fade": 0.2},
}


# ---------------------------------------------------------------------------
# Microchip pair trading
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
# Pebbles XS only: market-trade copying
# ---------------------------------------------------------------------------

PEBBLES_XS_LIMIT = 10
PEBBLES_XS_FRONTRUN_RATIO = 0.5


# ---------------------------------------------------------------------------
# Spike reversal — applied to every traded product
# ---------------------------------------------------------------------------

# Excludes products with stdev of mid-price first-differences >= 30
# (round 5 days 2-4) — only PEBBLES_XL crosses that bar and is dropped here.
SPIKE_PRODUCTS = [
    "GALAXY_SOUNDS_BLACK_HOLES",
    "GALAXY_SOUNDS_DARK_MATTER",
    "GALAXY_SOUNDS_PLANETARY_RINGS",
    "GALAXY_SOUNDS_SOLAR_FLAMES",
    "GALAXY_SOUNDS_SOLAR_WINDS",
    "MICROCHIP_CIRCLE",
    "MICROCHIP_OVAL",
    "MICROCHIP_RECTANGLE",
    "MICROCHIP_SQUARE",
    "MICROCHIP_TRIANGLE",
    "OXYGEN_SHAKE_CHOCOLATE",
    "OXYGEN_SHAKE_EVENING_BREATH",
    "OXYGEN_SHAKE_GARLIC",
    "OXYGEN_SHAKE_MINT",
    "OXYGEN_SHAKE_MORNING_BREATH",
    "PANEL_1X2",
    "PANEL_1X4",
    "PANEL_2X2",
    "PANEL_2X4",
    "PANEL_4X4",
    "PEBBLES_L",
    "PEBBLES_M",
    "PEBBLES_S",
    "PEBBLES_XS",
    "ROBOT_DISHES",
    "ROBOT_IRONING",
    "ROBOT_LAUNDRY",
    "ROBOT_MOPPING",
    "ROBOT_VACUUMING",
    "SLEEP_POD_COTTON",
    "SLEEP_POD_LAMB_WOOL",
    "SLEEP_POD_NYLON",
    "SLEEP_POD_POLYESTER",
    "SLEEP_POD_SUEDE",
    "SNACKPACK_CHOCOLATE",
    "SNACKPACK_PISTACHIO",
    "SNACKPACK_RASPBERRY",
    "SNACKPACK_STRAWBERRY",
    "SNACKPACK_VANILLA",
    "TRANSLATOR_ASTRO_BLACK",
    "TRANSLATOR_ECLIPSE_CHARCOAL",
    "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_SPACE_GRAY",
    "TRANSLATOR_VOID_BLUE",
    "UV_VISOR_AMBER",
    "UV_VISOR_MAGENTA",
    "UV_VISOR_ORANGE",
    "UV_VISOR_RED",
    "UV_VISOR_YELLOW",
]
SPIKE_LIMIT = 10
SPIKE_THRESH = 100


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
# Snackpacks: market making with unwind on tight spreads
# ---------------------------------------------------------------------------

SNACKPACK_PRODUCTS = [
    "SNACKPACK_CHOCOLATE",
    "SNACKPACK_VANILLA",
    "SNACKPACK_PISTACHIO",
    "SNACKPACK_RASPBERRY",
    "SNACKPACK_STRAWBERRY",
]

SNACKPACK_LIMIT: Dict[str, int] = {p: 10 for p in SNACKPACK_PRODUCTS}

SNACKPACK_PARAMS = {
    "quote_size": 10,
    "min_spread": 6,
    "unwind_size": 2,
}


# ---------------------------------------------------------------------------
# Galaxy sounds: wall-mid market maker with positional fade
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
    "edge_pct": 0.055,
    "fade":     0.4,
}


# ---------------------------------------------------------------------------
# UV visors: same wall-mid market maker, AMBER tuned more aggressive
# ---------------------------------------------------------------------------

UV_VISOR_PRODUCTS = [
    "UV_VISOR_AMBER",
    "UV_VISOR_MAGENTA",
    "UV_VISOR_ORANGE",
    "UV_VISOR_RED",
    "UV_VISOR_YELLOW",
]

UV_VISOR_LIMIT: Dict[str, int] = {p: 10 for p in UV_VISOR_PRODUCTS}

UV_VISOR_DEFAULT_PARAMS = {
    "edge_pct": 0.055,
    "fade":     0.4,
}

UV_VISOR_PARAMS: Dict[str, Dict[str, float]] = {
    "UV_VISOR_AMBER":   {"edge_pct": 0.04, "fade": 0.4},
    "UV_VISOR_MAGENTA": UV_VISOR_DEFAULT_PARAMS,
    "UV_VISOR_ORANGE":  UV_VISOR_DEFAULT_PARAMS,
    "UV_VISOR_RED":     UV_VISOR_DEFAULT_PARAMS,
    "UV_VISOR_YELLOW":  UV_VISOR_DEFAULT_PARAMS,
}


# ---------------------------------------------------------------------------
# Panels: wall-mid market maker, PANEL_1X2 only
# ---------------------------------------------------------------------------

PANEL_PRODUCTS = [
    "PANEL_1X2",
]

PANEL_LIMIT: Dict[str, int] = {p: 10 for p in PANEL_PRODUCTS}

PANEL_PARAMS: Dict[str, Dict[str, float]] = {
    "PANEL_1X2": {"edge_pct": 0.053, "fade": 0.4},
}


# ---------------------------------------------------------------------------
# Combined trader
# ---------------------------------------------------------------------------

class Trader:
    def __init__(self) -> None:
        self.prev_mid: Dict[str, float] = {}

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        logger.print("positions:", state.position)

        self._trade_oxygen(state, result)
        self._trade_microchips(state, result)
        self._trade_pebbles_xs(state, result)
        self._trade_snackpacks(state, result)
        self._trade_galaxy(state, result)
        self._trade_uv_visor(state, result)
        self._trade_panel(state, result)
        # Spike reversal runs last so a detected spike cancels concurrent quotes
        # on that product and replaces them with a sweep to the opposite limit.
        self._trade_spikes(state, result)

        logger.flush(state, result, 0, "")
        return result, 0, ""

    # -- liquid oxygen -----------------------------------------------------

    def _trade_oxygen(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        for product in OXYGEN_PRODUCTS:
            params = OXYGEN_PARAMS[product]
            edge_pct = params["edge_pct"]
            fade = params["fade"]

            depth = state.order_depths.get(product)
            if depth is None:
                continue

            asks = sorted(depth.sell_orders.items())
            bids = sorted(depth.buy_orders.items(), reverse=True)
            best_ask = asks[0][0] if asks else None
            best_bid = bids[0][0] if bids else None
            ask_2 = asks[1][0] if len(asks) > 1 else None
            bid_2 = bids[1][0] if len(bids) > 1 else None

            if bid_2 is None or ask_2 is None:
                continue

            fair = (bid_2 + ask_2) / 2
            limit = OXYGEN_LIMIT_DICT[product]
            position = state.position.get(product, 0)
            fair -= fade * position

            orders: List[Order] = []
            if (best_bid is not None
                    and (fair - (best_bid + 1)) / fair * 100 >= edge_pct
                    and position < limit):
                orders.append(buy(product, best_bid + 1, limit - position))

            if (best_ask is not None
                    and ((best_ask - 1) - fair) / fair * 100 >= edge_pct
                    and position > -limit):
                orders.append(sell(product, best_ask - 1, limit + position))

            if orders:
                result[product] = orders

    # -- microchip pairs ---------------------------------------------------

    def _trade_microchips(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        for cfg in MICROCHIP_PAIRS:
            result.update(pair_trade(state, **cfg))

    # -- pebbles XS copying ------------------------------------------------

    def _trade_pebbles_xs(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        product = "PEBBLES_XS"
        depth = state.order_depths.get(product)
        if depth is None:
            return

        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if best_bid is None or best_ask is None:
            return

        position = state.position.get(product, 0)
        buy_capacity = PEBBLES_XS_LIMIT - position
        sell_capacity = PEBBLES_XS_LIMIT + position

        market_trades = state.market_trades.get(product, [])
        if not market_trades:
            return

        order = market_trades[0]
        qty = int(abs(order.quantity) * PEBBLES_XS_FRONTRUN_RATIO)
        orders: List[Order] = []
        if order.quantity < 0:
            qty = min(qty, buy_capacity)
            if qty > 0:
                orders.append(buy(product, best_ask, qty))
        else:
            qty = min(qty, sell_capacity)
            if qty > 0:
                orders.append(sell(product, best_bid, qty))

        if orders:
            result[product] = orders

    # -- galaxy sounds -----------------------------------------------------

    def _trade_galaxy(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        edge_pct = GALAXY_PARAMS["edge_pct"]
        fade = GALAXY_PARAMS["fade"]

        for product in GALAXY_PRODUCTS:
            depth = state.order_depths.get(product)
            if depth is None:
                continue

            asks = sorted(depth.sell_orders.items())
            bids = sorted(depth.buy_orders.items(), reverse=True)
            best_ask = asks[0][0] if asks else None
            best_bid = bids[0][0] if bids else None
            ask_2 = asks[1][0] if len(asks) > 1 else None
            bid_2 = bids[1][0] if len(bids) > 1 else None

            if bid_2 is None or ask_2 is None:
                continue

            fair = (bid_2 + ask_2) / 2
            limit = GALAXY_LIMIT[product]
            position = state.position.get(product, 0)
            fair -= fade * position

            orders: List[Order] = []
            if (best_bid is not None
                    and (fair - (best_bid + 1)) / fair * 100 >= edge_pct
                    and position < limit):
                orders.append(buy(product, best_bid + 1, limit - position))

            if (best_ask is not None
                    and ((best_ask - 1) - fair) / fair * 100 >= edge_pct
                    and position > -limit):
                orders.append(sell(product, best_ask - 1, limit + position))

            if orders:
                result[product] = orders

    # -- uv visors ---------------------------------------------------------

    def _trade_uv_visor(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        for product in UV_VISOR_PRODUCTS:
            params = UV_VISOR_PARAMS[product]
            edge_pct = params["edge_pct"]
            fade = params["fade"]

            depth = state.order_depths.get(product)
            if depth is None:
                continue

            asks = sorted(depth.sell_orders.items())
            bids = sorted(depth.buy_orders.items(), reverse=True)
            best_ask = asks[0][0] if asks else None
            best_bid = bids[0][0] if bids else None
            ask_2 = asks[1][0] if len(asks) > 1 else None
            bid_2 = bids[1][0] if len(bids) > 1 else None

            if bid_2 is None or ask_2 is None:
                continue

            fair = (bid_2 + ask_2) / 2
            limit = UV_VISOR_LIMIT[product]
            position = state.position.get(product, 0)
            fair -= fade * position

            orders: List[Order] = []
            if (best_bid is not None
                    and (fair - (best_bid + 1)) / fair * 100 >= edge_pct
                    and position < limit):
                orders.append(buy(product, best_bid + 1, limit - position))

            if (best_ask is not None
                    and ((best_ask - 1) - fair) / fair * 100 >= edge_pct
                    and position > -limit):
                orders.append(sell(product, best_ask - 1, limit + position))

            if orders:
                result[product] = orders

    # -- panels ------------------------------------------------------------

    def _trade_panel(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        for product in PANEL_PRODUCTS:
            params = PANEL_PARAMS[product]
            edge_pct = params["edge_pct"]
            fade = params["fade"]

            depth = state.order_depths.get(product)
            if depth is None:
                continue

            asks = sorted(depth.sell_orders.items())
            bids = sorted(depth.buy_orders.items(), reverse=True)
            best_ask = asks[0][0] if asks else None
            best_bid = bids[0][0] if bids else None
            ask_2 = asks[1][0] if len(asks) > 1 else None
            bid_2 = bids[1][0] if len(bids) > 1 else None

            if bid_2 is None or ask_2 is None:
                continue

            fair = (bid_2 + ask_2) / 2
            limit = PANEL_LIMIT[product]
            position = state.position.get(product, 0)
            fair -= fade * position

            orders: List[Order] = []
            if (best_bid is not None
                    and (fair - (best_bid + 1)) / fair * 100 >= edge_pct
                    and position < limit):
                orders.append(buy(product, best_bid + 1, limit - position))

            if (best_ask is not None
                    and ((best_ask - 1) - fair) / fair * 100 >= edge_pct
                    and position > -limit):
                orders.append(sell(product, best_ask - 1, limit + position))

            if orders:
                result[product] = orders

    # -- spike reversal ----------------------------------------------------

    def _trade_spikes(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        for product in SPIKE_PRODUCTS:
            depth = state.order_depths.get(product)
            if depth is None:
                continue

            buy_orders = depth.buy_orders
            sell_orders = depth.sell_orders
            best_bid = max(buy_orders.keys()) if buy_orders else None
            best_ask = min(sell_orders.keys()) if sell_orders else None
            if best_bid is None or best_ask is None:
                continue

            pos = state.position.get(product, 0)
            mid = (best_bid + best_ask) / 2
            prev_mid = self.prev_mid.get(product)

            orders: List[Order] = []
            if prev_mid is not None:
                if mid - prev_mid >= SPIKE_THRESH:
                    orders.extend(_take_to_target(product, buy_orders, sell_orders, pos, -SPIKE_LIMIT))
                elif prev_mid - mid >= SPIKE_THRESH:
                    orders.extend(_take_to_target(product, buy_orders, sell_orders, pos, SPIKE_LIMIT))
            self.prev_mid[product] = mid

            if orders:
                result[product] = orders

    # -- snackpacks --------------------------------------------------------

    def _trade_snackpacks(self, state: TradingState, result: Dict[str, List[Order]]) -> None:
        quote_size = SNACKPACK_PARAMS["quote_size"]
        min_spread = SNACKPACK_PARAMS["min_spread"]
        unwind_size = SNACKPACK_PARAMS["unwind_size"]

        for product in SNACKPACK_PRODUCTS:
            depth = state.order_depths.get(product)
            if depth is None or not depth.buy_orders or not depth.sell_orders:
                continue

            best_bid = max(depth.buy_orders)
            best_ask = min(depth.sell_orders)
            spread = best_ask - best_bid
            position = state.position.get(product, 0)
            limit = SNACKPACK_LIMIT[product]

            orders: List[Order] = []
            if spread >= min_spread:
                buy_room = max(0, limit - position)
                sell_room = max(0, limit + position)
                bid_size = min(quote_size, buy_room)
                ask_size = min(quote_size, sell_room)
                if bid_size > 0:
                    orders.append(buy(product, best_bid + 1, bid_size))
                if ask_size > 0:
                    orders.append(sell(product, best_ask - 1, ask_size))
            else:
                if position > 0:
                    unwind = min(unwind_size, position)
                    orders.append(sell(product, best_bid, unwind))
                elif position < 0:
                    unwind = min(unwind_size, -position)
                    orders.append(buy(product, best_ask, unwind))

            if orders:
                result[product] = orders
