from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Any
import json


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders, conversions: int, trader_data: str) -> None:
        print(json.dumps([
            state.timestamp,
            trader_data,
            {symbol: [depth.buy_orders, depth.sell_orders] for symbol, depth in state.order_depths.items()},
            {symbol: [[o.symbol, o.price, o.quantity] for o in arr] for symbol, arr in orders.items()},
            conversions,
            self.logs,
            state.position,
        ]))
        self.logs = ""

logger = Logger()

class Trader:

    POSITION_LIMIT = {
        "EMERALDS": 80,
        "TOMATOES": 50
    }

    def __init__(self):
        self.price_history = {"EMERALDS": [], "TOMATOES": []}

    def run(self, state: TradingState):
        logger.print("timestamp:", state.timestamp)
        logger.print("positions:", state.position)
        result: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            position = state.position.get(product, 0)

            best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
            best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]

            LIMIT = self.POSITION_LIMIT[product]

            if product == "EMERALDS":
                fair = 10000

                if best_ask == fair and position<0:
                    amount = min(-position, -best_ask_amount)
                    orders.append(Order(product, best_ask, amount))
                    position += amount

                elif best_bid == fair and position>0:
                    amount = min(position, best_bid_amount)
                    orders.append(Order(product, best_bid, -amount))
                    position -= amount

                if position < LIMIT and best_bid < fair:
                    orders.append(Order(product, best_bid + 1, LIMIT - position))

                if position > -LIMIT and best_ask > fair:
                    orders.append(Order(product, best_ask - 1, -LIMIT - position))

            if product == "TOMATOES":
                spread = best_ask - best_bid
                bid_spike = False
                ask_spike = False
                if spread <= 7:
                    prev_order = self.price_history["TOMATOES"][-1]
                    prev_bid = prev_order[0]
                    prev_ask = prev_order[1]
                    if best_bid - prev_bid >= 5:
                        bid_spike = True
                    elif prev_ask - best_ask >= 5:
                        ask_spike = True

                if bid_spike:
                    if position > -5:
                        amount = best_bid_amount
                        orders.append(Order(product, best_bid, -amount))
                        position -= amount
                elif position < LIMIT:
                    orders.append(Order(product, best_bid + 1, LIMIT - position))

                if ask_spike:
                    if position < 5:
                        amount = -best_ask_amount
                        orders.append(Order(product, best_ask, amount))
                        position += amount
                elif position > -LIMIT:
                    orders.append(Order(product, best_ask - 1, -LIMIT - position))

            self.price_history[product].append([best_bid, best_ask])
            result[product] = orders

        traderData = ""
        conversions = 0
        return result, conversions, traderData