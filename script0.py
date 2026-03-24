from plot import plot_interval
import pandas as pd

order_book = pd.read_csv("prices_round_0_day_-2.csv", sep=";")
trades = pd.read_csv("trades_round_0_day_-2.csv", sep=";")
print(order_book)
print(trades)
plot_interval(order_book, trades, 1, 100)