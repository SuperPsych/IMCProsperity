from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict


class Trader:

    POSITION_LIMIT = {
        "EMERALDS": 80,
        "TOMATOES": 80
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            position = state.position.get(product, 0)

            if product == "EMERALDS":
                fair = 10000
                best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
                best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]
                if best_ask == fair and position<0:
                    orders.append(Order(product, -best_ask, position))

                elif best_bid == fair and position>0:
                    orders.append(Order(product, -best_bid, position))

                if position < self.POSITION_LIMIT[product] and best_bid<fair:
                    orders.append(Order(product, best_bid+1, self.POSITION_LIMIT[product]-position))

                if position > -self.POSITION_LIMIT[product] and best_ask>fair:
                    orders.append(Order(product, best_ask-1, self.POSITION_LIMIT[product]-position))

            if product == "TOMATOES":
                best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
                best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]

                if position < self.POSITION_LIMIT[product]:
                    orders.append(Order(product, best_bid + 1, 5))

                if position > -self.POSITION_LIMIT[product]:
                    orders.append(Order(product, best_ask - 1, -5))

            result[product] = orders

        traderData = ""
        conversions = 0
        return result, conversions, traderData