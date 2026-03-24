from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict


class Trader:

    POSITION_LIMIT = {
        "EMERALDS": 80,
        "TOMATOES": 35
    }

    def __init__(self):
        self.price_history = {"TOMATOES": []}

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
                buy_orders = dict(sorted(order_depth.buy_orders.items(), reverse=True))
                sell_orders = dict(sorted(order_depth.sell_orders.items()))

                bid_prices = list(buy_orders.keys())
                ask_prices = list(sell_orders.keys())

                best_bid = bid_prices[0]
                best_ask = ask_prices[0]

                if len(bid_prices) > 1 and buy_orders[bid_prices[1]] >  0.77*buy_orders[best_bid]:
                    bid_wall = bid_prices[1]
                else:
                    bid_wall = best_bid

                if len(ask_prices) > 1 and sell_orders[ask_prices[1]] > 0.77*sell_orders[best_ask]:
                    ask_wall = ask_prices[1]
                else:
                    ask_wall = best_ask

                fair = (bid_wall + ask_wall) / 2

                LIMIT = self.POSITION_LIMIT[product]

                for ask, ask_vol in sell_orders.items():
                    if ask < fair and position < LIMIT:
                        vol = min(-ask_vol, LIMIT - position)
                        orders.append(Order(product, ask, vol))
                        position += vol

                for bid, bid_vol in buy_orders.items():
                    if bid > fair and position > -LIMIT:
                        vol = min(bid_vol, LIMIT + position)
                        orders.append(Order(product, bid, -vol))
                        position -= vol

                if position < LIMIT:
                    orders.append(Order(product, best_bid + 1, LIMIT - position))
                if position > -LIMIT:
                    orders.append(Order(product, best_ask - 1, -LIMIT - position))

            result[product] = orders

        traderData = ""
        conversions = 0
        return result, conversions, traderData