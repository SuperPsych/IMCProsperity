from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional
import math


UNDERLYING = "VELVETFRUIT_EXTRACT"

LONG_LEG = "VEV_5400"
SHORT_LEG = "VEV_5300"
STRIKES = {LONG_LEG: 5400, SHORT_LEG: 5300}
LIMIT = 300

TTE_DAYS_AT_T0 = 5.0
TICKS_PER_DAY = 1_000_000


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def iv_call(price: float, S: float, K: float, T: float, r: float = 0.0,
            tol: float = 1e-6, max_iter: int = 60) -> Optional[float]:
    intrinsic = max(S - K * math.exp(-r * T), 0.0)
    if price is None or price <= intrinsic or S <= 0 or K <= 0 or T <= 0:
        return None
    lo, hi = 1e-6, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if bs_call(S, K, T, mid, r) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def mid_of(depth: OrderDepth) -> Optional[float]:
    if not depth.buy_orders or not depth.sell_orders:
        return None
    return (max(depth.buy_orders) + min(depth.sell_orders)) / 2


class Trader:
    def run(self, state: TradingState):
        orders: Dict[str, List[Order]] = {}

        und = state.order_depths.get(UNDERLYING)
        S = mid_of(und) if und is not None else None
        tte_years = max(0.0, TTE_DAYS_AT_T0 - state.timestamp / TICKS_PER_DAY) / 365.0

        ivs: Dict[str, Optional[float]] = {}
        for sym in (LONG_LEG, SHORT_LEG):
            d = state.order_depths.get(sym)
            mid = mid_of(d) if d is not None else None
            ivs[sym] = iv_call(mid, S, STRIKES[sym], tte_years) if (S is not None and mid is not None) else None

        iv_long, iv_short = ivs[LONG_LEG], ivs[SHORT_LEG]
        should_trade = (
            iv_long is not None
            and iv_short is not None
            and iv_long < iv_short
        )

        targets = {
            LONG_LEG: +LIMIT if should_trade else 0,
            SHORT_LEG: -LIMIT if should_trade else 0,
        }

        for sym, target in targets.items():
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            pos = state.position.get(sym, 0)
            delta = target - pos
            if delta > 0 and depth.sell_orders:
                orders[sym] = [Order(sym, min(depth.sell_orders), delta)]
            elif delta < 0 and depth.buy_orders:
                orders[sym] = [Order(sym, max(depth.buy_orders), delta)]

        return orders, 0, ""
