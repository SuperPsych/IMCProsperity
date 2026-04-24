from datamodel import Order, OrderDepth, TradingState
from typing import Callable, Dict, List, Tuple


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

    if bid_diff >= spike_thresh and bid_diff - ask_diff >= spike_thresh and position > 0:
        qty = min(position, best_bid_amount)
        if qty > 0:
            orders.append(sell(product, best_bid, qty))

    if ask_diff <= -spike_thresh and bid_diff - ask_diff >= spike_thresh and position < 0:
        qty = min(-position, -best_ask_quantity)
        if qty > 0:
            orders.append(buy(product, best_ask, qty))

    return orders


VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_PRODUCTS = [f"VEV_{k}" for k in VEV_STRIKES]


class Trader:
    TRADED_PRODUCTS = {
        "HYDROGEL_PACK",
        "VELVETFRUIT_EXTRACT",
        *VEV_PRODUCTS,
    }

    POSITION_LIMITS: Dict[str, int] = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        **{p: 300 for p in VEV_PRODUCTS},
    }

    ENABLE_STRATEGY: Dict[str, bool] = {
        "HYDROGEL_PACK": True,
        "VELVETFRUIT_EXTRACT": False,
        **{p: False for p in VEV_PRODUCTS},
    }

    MA_WINDOW = 10

    def __init__(self) -> None:
        self.strategies: Dict[str, Callable[[str, TradingState], List[Order]]] = {
            "HYDROGEL_PACK": self._trade_hydrogel,
            "VELVETFRUIT_EXTRACT": self._trade_velvetfruit,
            **{p: self._trade_vev_voucher for p in VEV_PRODUCTS},
        }
        self.price_history: Dict[str, List[List[int | None]]] = {}
        self.mid_history: Dict[str, List[float]] = {}
        self.initial_fair: Dict[str, float | None] = {}
        self.linreg: Dict[str, Dict[str, float]] = {}
        self._logs: List[str] = []

    def _log(self, msg: str) -> None:
        self._logs.append(msg)

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        self._logs = []
        self._log(f"t={state.timestamp} positions={dict(state.position)}")

        for product in self.TRADED_PRODUCTS:
            if product not in state.order_depths:
                continue
            strategy = self.strategies.get(product, self._trade_default)
            result[product] = strategy(product, state)

        conversions = 0
        trader_data = " | ".join(self._logs)
        print(trader_data)
        return result, conversions, trader_data

    def _trade_default(self, product: str, state: TradingState) -> List[Order]:
        return []

    HYDROGEL_PARAMS = {
        "min_spread": 10,
        "spike_thresh": 7,
    }

    def _trade_hydrogel(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []

        depth = state.order_depths[product]
        position = state.position.get(product, 0)
        limit = self.POSITION_LIMITS.get(product, 200)
        P = self.HYDROGEL_PARAMS

        best_bid, best_ask = self._best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return []

        bid_vol = depth.buy_orders[best_bid]
        ask_vol = depth.sell_orders[best_ask]
        prev_bid, prev_ask = self._previous_bbo(product)

        orders: List[Order] = []

        spike_orders = spike_take(
            product, best_bid, bid_vol, best_ask, ask_vol,
            prev_bid, prev_ask, position, spike_thresh=P["spike_thresh"],
        )
        for o in spike_orders:
            position += o.quantity
        orders.extend(spike_orders)

        spread = best_ask - best_bid
        if spread >= P["min_spread"]:
            bid_px = best_bid + 1
            ask_px = best_ask - 1
            if bid_px < ask_px:
                if position < limit:
                    orders.append(buy(product, bid_px, limit - position))
                if position > -limit:
                    orders.append(sell(product, ask_px, limit + position))

        self.price_history.setdefault(product, []).append([best_bid, best_ask])

        self._log(
            f"[HYDROGEL] pos={position} bb={best_bid} ba={best_ask} spread={spread} "
            f"spike={len(spike_orders)} orders={len(orders)}"
        )
        return orders

    def _trade_velvetfruit(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        return []

    def _trade_vev_voucher(self, product: str, state: TradingState) -> List[Order]:
        if not self.ENABLE_STRATEGY.get(product, False):
            return []
        return []

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

    def _best_bid_ask(self, order_depth: OrderDepth) -> Tuple[int | None, int | None]:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        return best_bid, best_ask
