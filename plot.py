import plotly.graph_objects as go

def plot_interval(order_book, trades, t0, t1):
    curr_order_book = order_book.iloc[t0:t1]
    idx = curr_order_book["timestamp"]

    t_min = idx.min()
    t_max = idx.max()

    # filter trades to same time window
    curr_trades = trades[
        (trades["timestamp"] >= t_min) &
        (trades["timestamp"] <= t_max)
    ]

    fig = go.Figure()

    # --- mid ---
    fig.add_trace(go.Scatter(
        x=idx, y=curr_order_book["mid_price"],
        name="mid",
        line=dict(width=3)
    ))

    # --- bids ---
    fig.add_trace(go.Scatter(x=idx, y=curr_order_book["bid_price_1"], name="bid_price_1"))
    fig.add_trace(go.Scatter(x=idx, y=curr_order_book["bid_price_2"], name="bid_price_2"))
    fig.add_trace(go.Scatter(x=idx, y=curr_order_book["bid_price_3"], name="bid_price_3"))

    # --- asks ---
    fig.add_trace(go.Scatter(
        x=idx, y=curr_order_book["ask_price_1"],
        name="ask_price_1",
        line=dict(dash="dash")
    ))
    fig.add_trace(go.Scatter(
        x=idx, y=curr_order_book["ask_price_2"],
        name="ask_price_2",
        line=dict(dash="dash")
    ))
    fig.add_trace(go.Scatter(
        x=idx, y=curr_order_book["ask_price_3"],
        name="ask_price_3",
        line=dict(dash="dash")
    ))

    # --- trades ---
    # --- trades ---
    if not curr_trades.empty:
        mid_series = curr_order_book.set_index("timestamp")["mid_price"]

        # align mid prices to trade timestamps (positional)
        trade_mid = mid_series.reindex(curr_trades["timestamp"], method="nearest").to_numpy()

        trade_prices = curr_trades["price"].to_numpy()

        # infer direction
        colors = ["green" if p > m else "red" for p, m in zip(trade_prices, trade_mid)]

        # scale sizes
        sizes = curr_trades["quantity"].to_numpy()
        sizes = 5 + 15 * (sizes / sizes.max())

        fig.add_trace(go.Scatter(
            x=curr_trades["timestamp"],
            y=curr_trades["price"],
            mode="markers",
            name="trades",
            customdata=curr_trades["quantity"],
            marker=dict(
                size=sizes,
                color=colors,
                opacity=0.6,
                line=dict(width=1)
            ),
            hovertemplate=
                "Price: %{y}<br>" +
                "Quantity: %{customdata}<br>" +
                "Time: %{x}<extra></extra>"
        ))

    fig.update_layout(
        title="orderbook + trades (size encoded)",
        xaxis_title="timestamp",
        yaxis_title="price",
        legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
        margin=dict(r=150)
    )

    fig.show()

    # --- spread plot ---
    spread_fig = go.Figure()
    spread = curr_order_book["ask_price_1"] - curr_order_book["bid_price_1"]

    spread_fig.add_trace(go.Scatter(
        x=idx, y=spread,
        name="bid-ask spread",
        line=dict(width=2)
    ))

    spread_fig.update_layout(
        title="bid-ask spread over interval",
        xaxis_title="timestamp",
        yaxis_title="spread"
    )

    spread_fig.show()