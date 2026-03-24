from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict


class Trader:

    POSITION_LIMIT = {
        "EMERALDS": 80,
        "TOMATOES": 50
    }

    def __init__(self):
        self.price_history = {"EMERALDS": [], "TOMATOES": []}

    def run(self, state: TradingState):
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

                if position < LIMIT and best_bid<fair:
                    orders.append(Order(product, best_bid+1, LIMIT-position))

                if position > -LIMIT and best_ask>fair:
                    orders.append(Order(product, best_ask-1, -position-LIMIT))

            if product == "TOMATOES":
                spread = best_ask - best_bid

                if spread <= 7:
                    prev_order = self.price_history["TOMATOES"][-1]
                    prev_bid = prev_order[0]
                    prev_ask = prev_order[1]
                    if best_bid - prev_bid >= 5 and position > -5:
                        amount = best_bid_amount
                        orders.append(Order(product, best_bid, -amount))
                        position -= amount
                    elif prev_ask - best_ask >= 5 and position < 5:
                        amount = -best_ask_amount
                        orders.append(Order(product, best_ask, amount))
                        position += amount

                if position < LIMIT:
                    orders.append(Order(product, best_bid + 1, LIMIT - position))
                if position > -LIMIT:
                    orders.append(Order(product, best_ask - 1, -LIMIT - position))

            self.price_history[product].append([best_bid, best_ask])
            result[product] = orders

        traderData = ""
        conversions = 0
        return result, conversions, traderData