from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict


class Trader:

    POSITION_LIMIT = {
        "EMERALDS": 35,
        "TOMATOES": 35
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
                    amount = min(-position, -best_ask_amount)
                    orders.append(Order(product, best_ask, amount))
                    position += amount

                elif best_bid == fair and position>0:
                    amount = min(position, best_bid_amount)
                    orders.append(Order(product, best_bid, -amount))
                    position -= amount

                if position < self.POSITION_LIMIT[product] and best_bid<fair:
                    orders.append(Order(product, best_bid+1, self.POSITION_LIMIT[product]-position))

                if position > -self.POSITION_LIMIT[product] and best_ask>fair:
                    orders.append(Order(product, best_ask-1, -position-self.POSITION_LIMIT[product]))

            if product == "TOMATOES":
                best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
                best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]

                if position < self.POSITION_LIMIT[product]:
                    orders.append(Order(product, best_bid + 1, 6))

                if position > -self.POSITION_LIMIT[product]:
                    orders.append(Order(product, best_ask - 1, -6))

            result[product] = orders

        traderData = ""
        conversions = 0
        return result, conversions, traderData