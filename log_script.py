import csv
import json
import pandas as pd
from io import StringIO

def plot(log_filename):

    json_file = None
    with open("log_filename", "r") as f:
        json_file = json.load(f)
        

    df = pd.read_csv(StringIO(json_file['activitiesLog']), delimiter = ';')


    # order book dataframe
    # df columns include: timestamp, product, ...

    # trades is a list of dicts
    trades_df = pd.DataFrame(json_file['tradeHistory'])

    # keep only your own trades
    # buy by SUBMISSION => positive
    # sell by SUBMISSION => negative
    trades_df["signed_qty"] = 0
    trades_df.loc[trades_df["buyer"] == "SUBMISSION", "signed_qty"] += trades_df["quantity"]
    trades_df.loc[trades_df["seller"] == "SUBMISSION", "signed_qty"] -= trades_df["quantity"]

    # aggregate net trade quantity per timestamp and product
    pos_changes = (
        trades_df.groupby(["timestamp", "symbol"], as_index=False)["signed_qty"]
        .sum()
        .rename(columns={"symbol": "product"})
    )

    # merge into order book df
    df = df.merge(pos_changes, on=["timestamp", "product"], how="left")

    # fill missing with 0, then cumulative sum by product
    df["signed_qty"] = df["signed_qty"].fillna(0)
    df["position"] = df.groupby("product")["signed_qty"].cumsum()

    # optional: drop helper column
    df = df.drop(columns=["signed_qty"])

    import pandas as pd
    import plotly.graph_objects as go

    def plot_orderbook_and_trades(df, trades, product=None):
        df_plot = df.copy()

        if product is not None:
            df_plot = df_plot[df_plot["product"] == product].copy()

        df_plot = df_plot.sort_values("timestamp")

        trades_df = pd.DataFrame(trades)
        if trades_df.empty:
            trades_df = pd.DataFrame(columns=["timestamp", "buyer", "seller", "symbol", "price", "quantity"])

        if product is not None and not trades_df.empty:
            trades_df = trades_df[trades_df["symbol"] == product].copy()

        if not trades_df.empty:
            trades_df = trades_df.sort_values("timestamp")

            def trade_side(row):
                if row.get("buyer") == "SUBMISSION":
                    return "BUY"
                elif row.get("seller") == "SUBMISSION":
                    return "SELL"
                return "OTHER"

            trades_df["side"] = trades_df.apply(trade_side, axis=1)

        fig = go.Figure()

        # --- bid prices ---
        for col in ["bid_price_1", "bid_price_2", "bid_price_3"]:
            if col in df_plot.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_plot["timestamp"],
                        y=df_plot[col],
                        mode="lines+markers",
                        name=col,
                        connectgaps=False,
                        hovertemplate=f"timestamp=%{{x}}<br>{col}=%{{y}}<extra>{col}</extra>"
                    )
                )

        # --- ask prices ---
        for col in ["ask_price_1", "ask_price_2", "ask_price_3"]:
            if col in df_plot.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_plot["timestamp"],
                        y=df_plot[col],
                        mode="lines+markers",
                        name=col,
                        connectgaps=False,
                        hovertemplate=f"timestamp=%{{x}}<br>{col}=%{{y}}<extra>{col}</extra>"
                    )
                )

        # --- mid price ---
        if "mid_price" in df_plot.columns:
            fig.add_trace(
                go.Scatter(
                    x=df_plot["timestamp"],
                    y=df_plot["mid_price"],
                    mode="lines",
                    name="mid_price",
                    hovertemplate="timestamp=%{x}<br>mid_price=%{y}<extra>mid_price</extra>"
                )
            )

        # --- profit and loss ---
        if "profit_and_loss" in df_plot.columns:
            fig.add_trace(
                go.Scatter(
                    x=df_plot["timestamp"],
                    y=df_plot["profit_and_loss"],
                    mode="lines",
                    name="profit_and_loss",
                    yaxis="y2",
                    hovertemplate="timestamp=%{x}<br>profit_and_loss=%{y}<extra>profit_and_loss</extra>"
                )
            )

        # --- position ---
        if "position" in df_plot.columns:
            fig.add_trace(
                go.Scatter(
                    x=df_plot["timestamp"],
                    y=df_plot["position"],
                    mode="lines",
                    name="position",
                    yaxis="y2",
                    hovertemplate="timestamp=%{x}<br>position=%{y}<extra>position</extra>"
                )
            )

        # --- trades ---
        if not trades_df.empty:
            side_to_symbol = {
                "BUY": "triangle-up",
                "SELL": "triangle-down",
                "OTHER": "circle"
            }

            side_to_color = {
                "BUY": None,
                "SELL": None,
                "OTHER": "red"
            }

            for side in ["BUY", "SELL", "OTHER"]:
                curr = trades_df[trades_df["side"] == side]
                if curr.empty:
                    continue

                marker_dict = {
                    "symbol": side_to_symbol[side],
                    "size": 14
                }

                if side_to_color[side] is not None:
                    marker_dict["color"] = side_to_color[side]

                fig.add_trace(
                    go.Scatter(
                        x=curr["timestamp"],
                        y=curr["price"],
                        mode="markers",
                        name=f"trades_{side.lower()}",
                        marker=marker_dict,
                        customdata=curr[["quantity", "buyer", "seller", "symbol"]].values,
                        hovertemplate=(
                            "timestamp=%{x}<br>"
                            "price=%{y}<br>"
                            "qty=%{customdata[0]}<br>"
                            "buyer=%{customdata[1]}<br>"
                            "seller=%{customdata[2]}<br>"
                            "symbol=%{customdata[3]}"
                            "<extra>" + side + "</extra>"
                        )
                    )
                )

        title = "Order Book and Trades"
        if product is not None:
            title += f" - {product}"

        fig.update_layout(
            title=title,
            xaxis_title="timestamp",
            yaxis_title="price",
            yaxis2=dict(
                title="position / profit_and_loss",
                overlaying="y",
                side="right"
            ),
            hovermode="x unified",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0
            )
        )

        return fig


    fig = plot_orderbook_and_trades(df, json_file['tradeHistory'], product="TOMATOES")
    fig.show(renderer="browser")