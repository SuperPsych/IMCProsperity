from datamodel import Order, OrderDepth, TradingState
from typing import Any, Callable, Dict, List, Tuple
import json
import os


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

# Per-asset-class multiplier on std(mid) used to set the binary-gate
# threshold. Stds measured over data/backtest d0-d3.
HYDRO_MULT = 0.8   # HYDROGEL_PACK
VELVET_MULT = 1.0  # VELVETFRUIT_EXTRACT
OPT_MULT = 0.7     # all VEV vouchers

# Per-asset-class fraction of `threshold` used as the neutralize edge:
# neutralize_edge = NEUTRALIZE_FRAC * threshold. When long, flatten by
# selling into bids >= mean + edge (and posting a sized make at
# best_ask - 1 if that price still clears the edge); when short,
# symmetrically. Fraction < 1 means the trader exits earlier than it
# enters; tweak per-class to control exit aggressiveness independently.
HYDRO_NEUTRALIZE_FRAC = 1
VELVET_NEUTRALIZE_FRAC = 2/3
OPT_NEUTRALIZE_FRAC = 1

# Left-shift the voucher poly2 fits by this many global ticks: substitute
# (t + POLY2_T_SHIFT) for t in fair = a + b*t + c*t^2. Positive shifts
# evaluate the fit at a *future* time; chosen via sweep on r3 d0-d3.
POLY2_T_SHIFT = 120_000

PARAMS = {
    # threshold = mult * std(mid) for each asset class.
    "hydrogel_mean": 9990,
    "hydrogel_threshold": HYDRO_MULT * 32.5883,

    "velvetfruit_mean": 5250,
    "velvetfruit_threshold": VELVET_MULT * 17.0908,

    # voucher fair = a + b*t + c*t^2 ; t = day*1e6 + timestamp.
    # Quadratic fit on data/backtest d0-d3 ATM ticks
    # (|VELVETFRUIT_EXTRACT - 5250| <= 1). See
    # DataExploration/round4/fit_poly2_atm_all_strikes.py.
    "VEV_4000_a": 1250.130358, "VEV_4000_b": -1.550169e-07, "VEV_4000_c": 3.696308e-14,  "VEV_4000_threshold": VELVET_MULT * 17.1139,
    "VEV_4500_a": 750.049440,  "VEV_4500_b": -6.222299e-08, "VEV_4500_c": 1.723681e-14,  "VEV_4500_threshold": VELVET_MULT * 17.1046,
    "VEV_5000_a": 257.262152,  "VEV_5000_b": -1.897015e-06, "VEV_5000_c": 1.119142e-13,  "VEV_5000_threshold": OPT_MULT * 16.3813,
    "VEV_5100_a": 172.895117,  "VEV_5100_b": -4.623187e-06, "VEV_5100_c": 1.958090e-13,  "VEV_5100_threshold": OPT_MULT * 15.3267,
    "VEV_5200_a": 100.835494,  "VEV_5200_b": -2.450560e-06, "VEV_5200_c": -6.518959e-13, "VEV_5200_threshold": OPT_MULT * 12.7964,
    "VEV_5300_a": 51.032929,   "VEV_5300_b": -1.385397e-06, "VEV_5300_c": -8.488619e-13, "VEV_5300_threshold": OPT_MULT * 8.9759,
    "VEV_5400_a": 20.780619,   "VEV_5400_b": -3.562812e-06, "VEV_5400_c": 1.107900e-13,  "VEV_5400_threshold": OPT_MULT * 4.6081,
    "VEV_5500_a": 9.169631,    "VEV_5500_b": -1.518481e-06, "VEV_5500_c": -9.224589e-14, "VEV_5500_threshold": OPT_MULT * 2.4770,
    "VEV_6000_a": 0.5,         "VEV_6000_b": 0.0,           "VEV_6000_c": 0.0,           "VEV_6000_threshold": OPT_MULT * 0.0,
    "VEV_6500_a": 0.5,         "VEV_6500_b": 0.0,           "VEV_6500_c": 0.0,           "VEV_6500_threshold": OPT_MULT * 0.0,
}


VEV_VOUCHERS = [
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500",
]


class Trader:
    TRADED_PRODUCTS = {
        "HYDROGEL_PACK",
        "VELVETFRUIT_EXTRACT",
        *VEV_VOUCHERS,
    }

    POSITION_LIMITS: Dict[str, int] = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        **{v: 300 for v in VEV_VOUCHERS},
    }

    ENABLE_STRATEGY: Dict[str, bool] = {
        "HYDROGEL_PACK": True,
        "VELVETFRUIT_EXTRACT": True,
        **{v: True for v in VEV_VOUCHERS},
    }

    MA_WINDOW = 10

    def __init__(self) -> None:
        self.strategies: Dict[str, Callable[[str, TradingState], List[Order]]] = {
            "HYDROGEL_PACK": self._trade_hydrogel,
            "VELVETFRUIT_EXTRACT": self._trade_velvetfruit,
            **{v: self._trade_voucher for v in VEV_VOUCHERS},
        }
        self.price_history: Dict[str, List[List[int | None]]] = {}
        self.mid_history: Dict[str, List[float]] = {}
        self.initial_fair: Dict[str, float | None] = {}
        # running sums for O(1) linear regression: y = a + b*x, x = step index
        self.linreg: Dict[str, Dict[str, float]] = {}

    def run(self, state: TradingState):
        if state.traderData:
            # reload persistent strategy state from traderData here
            pass

        result: Dict[str, List[Order]] = {}
        logger.print("positions:", state.position)

        for product in self.TRADED_PRODUCTS:
            if product not in state.order_depths:
                continue
            strategy = self.strategies.get(product, self._trade_default)
            result[product] = strategy(product, state)

        conversions = 0
        trader_data = json.dumps({})
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def _trade_default(self, product: str, state: TradingState) -> List[Order]:
        return []

    def _trade_hydrogel(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        limit = self.POSITION_LIMITS.get(product, 200)
        mean = PARAMS["hydrogel_mean"]
        threshold = PARAMS["hydrogel_threshold"]
        neutralize_edge = HYDRO_NEUTRALIZE_FRAC * threshold

        position = self._neutralize_position(
            product, orders, position, mean, neutralize_edge, threshold, bids, asks,
        )
        self._apply_binary_gate(
            product, orders, position, limit, mean, threshold, bids, asks,
        )
        return orders

    def _trade_velvetfruit(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        limit = self.POSITION_LIMITS.get(product, 200)
        mean = PARAMS["velvetfruit_mean"]
        threshold = PARAMS["velvetfruit_threshold"]
        neutralize_edge = VELVET_NEUTRALIZE_FRAC * threshold

        # Neutralize via taking against the fixed 5250 center, and post
        # a passive penny inside the touch sized to flatten residual
        # position whenever that maker price still clears the edge.
        position = self._neutralize_position(
            product, orders, position, mean, neutralize_edge, threshold, bids, asks,
        )
        self._apply_binary_gate(
            product, orders, position, limit, mean, threshold, bids, asks,
        )
        return orders

    def _trade_voucher(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        order_depth = state.order_depths[product]
        orders: List[Order] = []
        position = state.position.get(product, 0)

        asks = sorted(order_depth.sell_orders.items())
        bids = sorted(order_depth.buy_orders.items(), reverse=True)

        limit = self.POSITION_LIMITS.get(product, 300)
        threshold = PARAMS[f"{product}_threshold"]
        neutralize_edge = OPT_NEUTRALIZE_FRAC * threshold

        # quadratic fair: fair = a + b*t + c*t^2. state.timestamp resets
        # per day; PROSPERITY4BT_DAY gives the day index. POLY2_T_SHIFT
        # left-shifts the evaluation point.
        day = int(os.environ.get("PROSPERITY4BT_DAY", 3))
        effective_t = day * 1_000_000 + state.timestamp + POLY2_T_SHIFT
        a = PARAMS[f"{product}_a"]
        b = PARAMS[f"{product}_b"]
        c = PARAMS[f"{product}_c"]
        mean = a + b * effective_t + c * effective_t * effective_t

        position = self._neutralize_position(
            product, orders, position, mean, neutralize_edge, threshold, bids, asks,
        )
        self._apply_binary_gate(
            product, orders, position, limit, mean, threshold, bids, asks,
        )
        return orders

    def _neutralize_position(
        self,
        product: str,
        orders: List[Order],
        position: int,
        mean: float,
        edge: float,
        threshold: float,
        bids: List[Tuple[int, int]],
        asks: List[Tuple[int, int]],
    ) -> int:
        """Flatten existing position back to 0 by hitting the book on the
        favorable side: long -> sell into bids >= mean + edge; short ->
        buy asks <= mean - edge. Walks levels until position is flat or
        the next level no longer clears the edge.

        After the take pass, post a passive penny inside the touch for any
        residual position when that maker price would itself clear the
        neutralize edge — i.e., treat best_ask-1 / best_bid+1 as if it were
        a take level. Skip the maker when the gate's `threshold` would
        already place a maker at the same price (avoid duplicate orders).
        """
        if position > 0 and bids:
            for bid_price, bid_qty in bids:
                if bid_price < mean + edge:
                    break
                if position <= 0:
                    break
                qty = min(position, bid_qty)
                if qty > 0:
                    orders.append(sell(product, bid_price, -qty))
                    position -= qty
        elif position < 0 and asks:
            for ask_price, ask_qty in asks:
                if ask_price > mean - edge:
                    break
                if position >= 0:
                    break
                qty = min(-position, -ask_qty)
                if qty > 0:
                    orders.append(buy(product, ask_price, qty))
                    position += qty

        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        if position > 0 and best_ask is not None:
            maker_price = best_ask - 1
            if maker_price >= mean + edge and maker_price <= mean + threshold:
                orders.append(sell(product, maker_price, -position))
        elif position < 0 and best_bid is not None:
            maker_price = best_bid + 1
            if maker_price <= mean - edge and maker_price >= mean - threshold:
                orders.append(buy(product, maker_price, -position))
        return position

    def _apply_binary_gate(
        self,
        product: str,
        orders: List[Order],
        position: int,
        limit: int,
        mean: float,
        threshold: float,
        bids: List[Tuple[int, int]],
        asks: List[Tuple[int, int]],
    ) -> int:
        """Binary trade gate: take full size at every order-book level whose
        price clears `mean ± threshold`, walking from the touch outward.
        After taking, post a passive maker order at bid+1 / ask-1 for any
        remaining capacity if that price still clears the threshold.
        `bids` is sorted high-to-low; `asks` is sorted low-to-high (with
        negative quantities, per OrderDepth convention).
        """
        # Take: walk asks (cheapest first) on the buy side, or bids on the sell side
        if asks and asks[0][0] < mean - threshold:
            for ask_price, ask_qty in asks:
                if ask_price >= mean - threshold:
                    break
                capacity = limit - position
                if capacity <= 0:
                    break
                qty = min(capacity, -ask_qty)
                if qty > 0:
                    orders.append(buy(product, ask_price, qty))
                    position += qty
                
        elif bids and bids[0][0] > mean + threshold:
            for bid_price, bid_qty in bids:
                if bid_price <= mean + threshold:
                    break
                capacity = limit + position
                if capacity <= 0:
                    break
                qty = min(capacity, bid_qty)
                if qty > 0:
                    orders.append(sell(product, bid_price, -qty))
                    position -= qty

        # Make: post one level inside the touch if that price still clears the threshold
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        if best_bid is not None and (best_bid + 1) < mean - threshold:
            qty = limit - position
            if qty > 0:
                orders.append(buy(product, best_bid + 1, qty))
        elif best_ask is not None and (best_ask - 1) > mean + threshold:
            qty = limit + position
            if qty > 0:
                orders.append(sell(product, best_ask - 1, -qty))

        return position

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
            return sy / n
        b = (n * sxy - sx * sy) / denom
        a = (sy - b * sx) / n
        return a + b * n

    def _best_bid_ask(self, order_depth: OrderDepth) -> Tuple[int | None, int | None]:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        return best_bid, best_ask
