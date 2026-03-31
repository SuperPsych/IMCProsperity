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

PARAMS = {
    "TOMATOES_POSITION_LIMIT": 64,
    "TOMATOES_SPIKE_THRESHOLD": 5,
    "TOMATOES_SPIKE_POSITION_GUARD": 20,
}


# ─────────────────────────────────────────────────────────────────────────────


    "TOMATOES_SPIKE_POSITION_GUARD": 24,
} 
class Trader:
    POSITION_LIMIT = {
        "EMERALDS": 80,
        "TOMATOES": PARAMS["TOMATOES_POSITION_LIMIT"],
    }

    def __init__(self):
        self.price_history = {"EMERALDS": [], "TOMATOES": []}

    def run(self, state: TradingState):
        logger.print("timestamp:", state.timestamp)
        logger.print("positions:", state.position)
        result: Dict[str, List[Order]] = {}

        # Pull live params so grid search injections take effect
        tomato_limit = PARAMS["TOMATOES_POSITION_LIMIT"]
        spike_thresh = PARAMS["TOMATOES_SPIKE_THRESHOLD"]
        spike_pos_guard = PARAMS["TOMATOES_SPIKE_POSITION_GUARD"]

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            position = state.position.get(product, 0)

            best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
            best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]

            LIMIT = PARAMS["TOMATOES_POSITION_LIMIT"] if product == "TOMATOES" else self.POSITION_LIMIT[product]

            # ── EMERALDS ──────────────────────────────────────────────────────
            if product == "EMERALDS":
                fair = 10000

                if best_ask == fair and position < 0:
                    amount = min(-position, -best_ask_amount)
                    orders.append(Order(product, best_ask, amount))
                    position += amount
                elif best_bid == fair and position > 0:
                    amount = min(position, best_bid_amount)
                    orders.append(Order(product, best_bid, -amount))
                    position -= amount

                if position < LIMIT and best_bid < fair:
                    orders.append(Order(product, best_bid + 1, LIMIT - position))
                if position > -LIMIT and best_ask > fair:
                    orders.append(Order(product, best_ask - 1, -LIMIT - position))

            # ── TOMATOES ──────────────────────────────────────────────────────
            if product == "TOMATOES":
                spread = best_ask - best_bid
                bid_spike = False
                ask_spike = False

                if spread <= 7 and self.price_history["TOMATOES"]:
                    prev_bid, prev_ask = self.price_history["TOMATOES"][-1]
                    if best_bid - prev_bid >= 5:
                        fair = best_ask - 7
                        if best_bid >= fair:
                            bid_spike = True
                    elif prev_ask - best_ask >= 5:
                        ask_spike = True
                        fair = best_bid + 7
                        if best_ask <= fair:
                            ask_spike = True

                if bid_spike:
                    if position > -spike_pos_guard:
                        amount = best_bid_amount
                        orders.append(Order(product, best_bid, -amount))
                        position -= amount
                elif position < LIMIT:
                    orders.append(Order(product, best_bid + 1, LIMIT - position))

                if ask_spike:
                    if position < spike_pos_guard:
                        amount = -best_ask_amount
                        orders.append(Order(product, best_ask, amount))
                        position += amount
                elif position > -LIMIT:
                    orders.append(Order(product, best_ask - 1, -LIMIT - position))

            self.price_history[product].append([best_bid, best_ask])
            result[product] = orders

        traderData = ""
        conversions = 0
        logger.flush(state, orders, conversions, traderData)
        return result, conversions, traderData
