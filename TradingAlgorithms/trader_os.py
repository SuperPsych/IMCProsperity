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
        if best_bid + 1 < fair and position < limit:
            orders.append(buy(product, best_bid + 1, limit - position))
        if best_ask - 1 > fair and position > -limit:
            orders.append(sell(product, best_ask - 1, limit + position))
    return orders

def market_take(product, best_bid, best_bid_quantity, best_ask, best_ask_quantity, fair, position):
    """Hit mispriced quotes to flatten position toward zero."""
    orders = []
    # ask at or below fair and we're short → buy to flatten
    if best_ask is not None and best_ask <= fair and position < 0:
        qty = min(-position, -best_ask_quantity)  # ask amounts are negative
        orders.append(buy(product, best_ask, qty))
    # bid at or above fair and we're long → sell to flatten
    if best_bid is not None and best_bid >= fair and position > 0:
        qty = min(position, best_bid_quantity)
        orders.append(sell(product, best_bid, qty))
    return orders

class Trader:

    POSITION_LIMIT = {
        "ASH_COATED_OSMIUM": 80
    }

    def __init__(self):
        self.price_history = {}

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
            best_bid, best_bid_quantity = bids[0] if bids else (None, None)

            LIMIT = self.POSITION_LIMIT.get(product, 50)

            if product == "ASH_COATED_OSMIUM":
                fair = 10000
                spread_thresh = 16

                # flatten position when price crosses fair
                take_orders = market_take(product, best_bid, best_bid_quantity,
                                          best_ask, best_ask_quantity, fair, position)
                for o in take_orders:
                    position += o.quantity
                orders.extend(take_orders)

                # penny the spread
                orders.extend(penny(product, best_bid, best_ask, fair,
                                    spread_thresh, position, LIMIT))

            self.price_history.setdefault(product, []).append([best_bid, best_ask])
            result[product] = orders

        traderData = ""
        conversions = 0
        logger.flush(state, result, conversions, traderData)
        return result, conversions, traderData