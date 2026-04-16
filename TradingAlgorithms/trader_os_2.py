from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Any
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

            # top 3 levels
            bid_levels = [get_level(bids, i) for i in range(3)]
            ask_levels = [get_level(asks, i) for i in range(3)]

            best_bid = bid_levels[0][0]
            best_ask = ask_levels[0][0]

            mid_price = (
                (best_bid + best_ask) / 2
                if best_bid is not None and best_ask is not None
                else None
            )

            # --- print ONE ROW ---
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

                # trades (leave as lists, easy to explode later)
                "own_trades": [
                    (t.price, t.quantity, t.timestamp)
                    for t in state.own_trades.get(symbol, [])
                ],
                "market_trades": [
                    (t.price, t.quantity, t.timestamp)
                    for t in state.market_trades.get(symbol, [])
                ],

                "position": state.position.get(symbol, 0),

                # optional debug
                "log": self.logs.strip()
            }

            print(json.dumps(row))

        self.logs = ""

logger = Logger()

def buy(product: str, price: int, quantity: int) -> Order:
    """Create a buy order. Quantity should be positive."""
    return Order(product, price, abs(quantity))

def sell(product: str, price: int, quantity: int) -> Order:
    """Create a sell order. Quantity should be positive."""
    return Order(product, price, -abs(quantity))

def penny(product, best_bid, best_ask, fair, spread_thresh, position, limit):
    """Place orders 1 tick inside the spread if spread >= threshold and price stays on our side of fair."""
    orders = []
    spread = best_ask - best_bid if (best_ask is not None and best_bid is not None) else 0
    if spread >= spread_thresh:
        if (best_bid + 1 < fair or (best_bid + 1 == fair and position < 0)) and position < limit:
            orders.append(buy(product, best_bid + 1, limit - position))
        if (best_ask - 1 > fair or (best_ask - 1 == fair and position > 0)) and position > -limit:
            orders.append(sell(product, best_ask - 1, limit + position))
    return orders

def market_take(product, best_bid, best_bid_amount, best_ask, best_ask_quantity, fair, position):
    """Hit mispriced quotes to flatten position toward zero."""
    orders = []
    # ask at or below fair and we're short → buy to flatten
    if best_ask is not None and best_ask <= fair and position < 0:
        qty = min(-position, -best_ask_quantity)  # ask amounts are negative
        orders.append(buy(product, best_ask, qty))
    # bid at or above fair and we're long → sell to flatten
    if best_bid is not None and best_bid >= fair and position > 0:
        qty = min(position, best_bid_amount)
        orders.append(sell(product, best_bid, qty))
    return orders

def spike_take(product, best_bid, best_bid_amount, best_ask, best_ask_quantity,
               prev_bid, prev_ask, position, spike_thresh=10):
    """Take on price spikes. Sell into bid spikes (long only), buy into ask spikes (short only)."""
    orders = []
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

    POSITION_LIMIT = {
        "ASH_COATED_OSMIUM": 80
    }

    MA_WINDOW = 10

    def __init__(self):
        self.price_history = {}
        self.mid_history = {}

    def _previous_bbo(self, product):
        history = self.price_history.get(product)
        if history:
            return history[-1][0], history[-1][1]
        return None, None

    def _update_mid(self, product, best_bid, best_ask):
        """Track mid prices for moving average. Only stores real mid values."""
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2
            self.mid_history.setdefault(product, []).append(mid)

    def _moving_avg(self, product):
        """Short-term moving average of recent mid prices."""
        history = self.mid_history.get(product, [])
        if not history:
            return None
        window = history[-self.MA_WINDOW:]
        return sum(window) / len(window)

    def run(self, state: TradingState):
        logger.print("positions:", state.position)
        result: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            position = state.position.get(product, 0)

            asks = sorted(order_depth.sell_orders.items())
            bids = sorted(order_depth.buy_orders.items(), reverse=True)

            best_ask, best_ask_quantity = asks[0] if asks else (None, None)
            best_bid, best_bid_amount = bids[0] if bids else (None, None)

            LIMIT = self.POSITION_LIMIT.get(product, 50)

            if product == "ASH_COATED_OSMIUM":
                # --- parameters ---
                PARAMS = {
                    "base_fair": 10000,
                    "spread_thresh": 16,
                    "half_width": 8,
                    "position_adjust_step": 15,
                    "spike_thresh": 10,
                }
                base_fair = PARAMS["base_fair"]
                spread_thresh = PARAMS["spread_thresh"]
                half_width = PARAMS["half_width"]
                pos_step = PARAMS["position_adjust_step"]
                spike_thresh = PARAMS["spike_thresh"]

                fair = base_fair + (position // pos_step * -1)

                # flatten position when price crosses fair
                take_orders = market_take(product, best_bid, best_bid_amount,
                                          best_ask, best_ask_quantity, fair, position)
                for o in take_orders:
                    position += o.quantity
                orders.extend(take_orders)

                # take on price spikes
                prev_bid, prev_ask = self._previous_bbo(product)
                spike_orders = spike_take(product, best_bid, best_bid_amount,
                                          best_ask, best_ask_quantity,
                                          prev_bid, prev_ask, position,
                                          spike_thresh)
                for o in spike_orders:
                    position += o.quantity
                orders.extend(spike_orders)

                # fill missing side with moving average for market making only
                mm_bid, mm_ask = best_bid, best_ask
                ma = self._moving_avg(product)
                if mm_bid is None and ma is not None:
                    mm_bid = int(min(ma - half_width, fair - half_width))
                if mm_ask is None and ma is not None:
                    mm_ask = int(max(ma + half_width, fair + half_width))

                # penny the spread
                orders.extend(penny(product, mm_bid, mm_ask, fair,
                                    spread_thresh, position, LIMIT))

            self._update_mid(product, best_bid, best_ask)
            last_bid, last_ask = self._previous_bbo(product)
            stored_bid = best_bid if best_bid is not None else last_bid
            stored_ask = best_ask if best_ask is not None else last_ask
            self.price_history.setdefault(product, []).append([stored_bid, stored_ask])
            result[product] = orders

        traderData = ""
        conversions = 0
        logger.flush(state, result, conversions, traderData)
        return result, conversions, traderData