# IMC Prosperity 2026 — Trading Bot

IMC Prosperity is an algorithmic trading competition where participants submit a `Trader` class with a `run(state: TradingState)` method. Each timestep the engine calls `run`, passes the current market state, and expects a dict of `{product: [Order, ...]}` back. The goal is to maximize PnL across simulated trading rounds.

## Project Structure

| Path | Purpose |
|------|---------|
| `TradingAlgorithms/` | All trader code and the competition-provided datamodel |
| `TradingAlgorithms/trader.py` | Main submission file |
| `TradingAlgorithms/datamodel.py` | Market data structures (read-only, competition-provided) |
| `data/` | Historical order book and trade CSVs |
| `backtests/` | Competition log files from past runs |
| `DataExploration/` | Jupyter notebooks and analysis scripts |
| `grid_search.py` | Generic hyperparameter optimizer (runs backtests in parallel) |
| `plotter.py` | Post-trade visualization using Plotly |

## Key Data Structures (datamodel.py)

```python
Order(symbol, price, quantity)           # positive qty = buy, negative = sell
OrderDepth.buy_orders  -> {price: qty}   # highest price first
OrderDepth.sell_orders -> {price: qty}   # lowest price first
TradingState.position  -> {product: int} # net inventory per product
TradingState.order_depths -> {product: OrderDepth}
```

## Backtesting

Uses the external `prosperity4bt` CLI (installed in the project venv):
```bash
prosperity4bt ALGORITHM DAYS...

# DAYS formats:
#   <round>          → all days in a round  (e.g. 0)
#   <round>-<day>    → single day           (e.g. 0-1)
#   multiple days    → e.g. 0-1 0-2 0-3

prosperity4bt TradingAlgorithms/trader.py 0          # full round 0
prosperity4bt TradingAlgorithms/trader.py 0-1        # round 0, day 1 only
prosperity4bt TradingAlgorithms/trader.py 0-1 0-2    # round 0, days 1 and 2
```

Key options:
- `--print` — print trader stdout while running
- `--merge-pnl` — merge PnL across days into one total
- `--no-out` — skip saving a log file
- `--out FILE` — save log to a specific path (default: `backtests/<timestamp>.log`)
- `--match-trades [all|worse|none]` — how to fill orders against market trades (default: `all`)
- `--no-progress` — suppress progress bars (useful in scripts/grid search)

## Hyperparameter Tuning

`grid_search.py` patches a `PARAMS` dict in the trader via regex, runs `prosperity4bt` for each parameter combination (parallelized via `ThreadPoolExecutor`), and parses PnL output to find optimal settings.

## Visualization

`plotter.py` has two classes:
- `Plotter`: Interactive order book viewer from CSV files in `data/`
- `LogVisualizer`: Parses competition JSON logs from `backtests/` → plots orderbook, position, PnL, spread
