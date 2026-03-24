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
        "TOMATOES": 80
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        logger.print("timestamp:", state.timestamp)
        logger.print("positions:", state.position)

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            position = state.position.get(product, 0)

            if product == "EMERALDS":
                fair = 10000
                best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
                best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]
                if best_ask == fair and position<0:
                    orders.append(Order(product, best_ask, position))

                elif best_bid == fair and position>0:
                    orders.append(Order(product, best_bid, position))

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