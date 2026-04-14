import pandas as pd
import numpy as np
import plotly.graph_objects as go


def load_activity_log(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")

    df.columns = [c.strip() for c in df.columns]

    numeric_cols = [
        "day", "timestamp",
        "bid_price_1", "bid_volume_1",
        "bid_price_2", "bid_volume_2",
        "bid_price_3", "bid_volume_3",
        "ask_price_1", "ask_volume_1",
        "ask_price_2", "ask_volume_2",
        "ask_price_3", "ask_volume_3",
        "mid_price", "profit_and_loss"
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "product" in df.columns:
        df["product"] = df["product"].astype(str).str.strip()

    df = df.sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    return df


def preprocess_product(df: pd.DataFrame, product: str) -> pd.DataFrame:
    book = df[df["product"] == product].copy()
    book = book.sort_values(["day", "timestamp"]).reset_index(drop=True)

    for level in [1, 2, 3]:
        for side in ["bid", "ask"]:
            pcol = f"{side}_price_{level}"
            vcol = f"{side}_volume_{level}"
            if pcol not in book.columns:
                book[pcol] = np.nan
            if vcol not in book.columns:
                book[vcol] = np.nan

    if "mid_price" not in book.columns:
        book["mid_price"] = (book["bid_price_1"] + book["ask_price_1"]) / 2

    book["spread"] = book["ask_price_1"] - book["bid_price_1"]
    book["microprice"] = (
        book["ask_price_1"] * book["bid_volume_1"] +
        book["bid_price_1"] * book["ask_volume_1"]
    ) / (book["bid_volume_1"] + book["ask_volume_1"])

    book["bid_depth_top3"] = (
        book["bid_volume_1"].fillna(0) +
        book["bid_volume_2"].fillna(0) +
        book["bid_volume_3"].fillna(0)
    )
    book["ask_depth_top3"] = (
        book["ask_volume_1"].fillna(0) +
        book["ask_volume_2"].fillna(0) +
        book["ask_volume_3"].fillna(0)
    )
    book["imbalance"] = (
        (book["bid_depth_top3"] - book["ask_depth_top3"]) /
        (book["bid_depth_top3"] + book["ask_depth_top3"]).replace(0, np.nan)
    )

    book["mid_change"] = book["mid_price"].diff()
    book["spread_change"] = book["spread"].diff()
    book["pnl_change"] = book["profit_and_loss"].diff()

    book["bid_v1_change"] = book["bid_volume_1"].diff()
    book["ask_v1_change"] = book["ask_volume_1"].diff()

    pnl_thresh = book["pnl_change"].abs().quantile(0.90)
    if pd.isna(pnl_thresh) or pnl_thresh == 0:
        pnl_thresh = 0.01

    book["likely_fill"] = book["pnl_change"].abs() >= pnl_thresh

    book["likely_buy_fill"] = (
        book["likely_fill"] &
        (
            (book["ask_volume_1"] < book["ask_volume_1"].shift(1)) |
            (book["mid_change"] > 0)
        )
    )

    book["likely_sell_fill"] = (
        book["likely_fill"] &
        (
            (book["bid_volume_1"] < book["bid_volume_1"].shift(1)) |
            (book["mid_change"] < 0)
        )
    )

    return book


def plot_interval(book: pd.DataFrame, t0=None, t1=None, renderer="browser"):
    curr = book.copy()

    if t0 is not None:
        curr = curr[curr["timestamp"] >= t0]
    if t1 is not None:
        curr = curr[curr["timestamp"] <= t1]

    curr = curr.reset_index(drop=True)
    idx = curr["timestamp"]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=idx, y=curr["mid_price"],
        name="mid",
        line=dict(width=3)
    ))

    for level in [1, 2, 3]:
        bp = f"bid_price_{level}"
        ap = f"ask_price_{level}"

        if bp in curr.columns:
            fig.add_trace(go.Scatter(
                x=idx, y=curr[bp],
                name=bp,
                mode="lines"
            ))

        if ap in curr.columns:
            fig.add_trace(go.Scatter(
                x=idx, y=curr[ap],
                name=ap,
                mode="lines",
                line=dict(dash="dash")
            ))

    buy_marks = curr[curr["likely_buy_fill"]]
    sell_marks = curr[curr["likely_sell_fill"]]
    other_marks = curr[curr["likely_fill"] & ~(curr["likely_buy_fill"] | curr["likely_sell_fill"])]

    if not buy_marks.empty:
        fig.add_trace(go.Scatter(
            x=buy_marks["timestamp"],
            y=buy_marks["ask_price_1"].fillna(buy_marks["mid_price"]),
            mode="markers",
            name="likely buy fill",
            marker=dict(size=10, symbol="triangle-up", opacity=0.8),
            customdata=np.stack([
                buy_marks["profit_and_loss"].fillna(0),
                buy_marks["pnl_change"].fillna(0),
                buy_marks["spread"].fillna(0)
            ], axis=1),
            hovertemplate=(
                "Time: %{x}<br>"
                "Price ref: %{y}<br>"
                "PnL: %{customdata[0]:.2f}<br>"
                "ΔPnL: %{customdata[1]:.2f}<br>"
                "Spread: %{customdata[2]:.2f}<extra></extra>"
            )
        ))

    if not sell_marks.empty:
        fig.add_trace(go.Scatter(
            x=sell_marks["timestamp"],
            y=sell_marks["bid_price_1"].fillna(sell_marks["mid_price"]),
            mode="markers",
            name="likely sell fill",
            marker=dict(size=10, symbol="triangle-down", opacity=0.8),
            customdata=np.stack([
                sell_marks["profit_and_loss"].fillna(0),
                sell_marks["pnl_change"].fillna(0),
                sell_marks["spread"].fillna(0)
            ], axis=1),
            hovertemplate=(
                "Time: %{x}<br>"
                "Price ref: %{y}<br>"
                "PnL: %{customdata[0]:.2f}<br>"
                "ΔPnL: %{customdata[1]:.2f}<br>"
                "Spread: %{customdata[2]:.2f}<extra></extra>"
            )
        ))

    if not other_marks.empty:
        fig.add_trace(go.Scatter(
            x=other_marks["timestamp"],
            y=other_marks["mid_price"],
            mode="markers",
            name="likely fill (unclear side)",
            marker=dict(size=8, symbol="circle", opacity=0.6),
            customdata=np.stack([
                other_marks["profit_and_loss"].fillna(0),
                other_marks["pnl_change"].fillna(0)
            ], axis=1),
            hovertemplate=(
                "Time: %{x}<br>"
                "Mid: %{y}<br>"
                "PnL: %{customdata[0]:.2f}<br>"
                "ΔPnL: %{customdata[1]:.2f}<extra></extra>"
            )
        ))

    fig.update_layout(
        title="Order book with inferred execution markers",
        xaxis_title="timestamp",
        yaxis_title="price",
        legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
        margin=dict(r=180),
        hovermode="x unified"
    )
    fig.show(renderer=renderer)

    spread_fig = go.Figure()
    spread_fig.add_trace(go.Scatter(
        x=idx, y=curr["spread"],
        name="spread",
        line=dict(width=2)
    ))
    spread_fig.update_layout(
        title="Bid-ask spread",
        xaxis_title="timestamp",
        yaxis_title="spread"
    )
    spread_fig.show(renderer=renderer)

    pnl_fig = go.Figure()
    pnl_fig.add_trace(go.Scatter(
        x=idx, y=curr["profit_and_loss"],
        name="PnL",
        line=dict(width=2)
    ))
    pnl_fig.add_trace(go.Scatter(
        x=idx, y=curr["pnl_change"],
        name="ΔPnL",
        yaxis="y2",
        line=dict(dash="dot")
    ))
    pnl_fig.update_layout(
        title="PnL and PnL change",
        xaxis_title="timestamp",
        yaxis=dict(title="PnL"),
        yaxis2=dict(
            title="ΔPnL",
            overlaying="y",
            side="right"
        ),
        legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
        margin=dict(r=120)
    )
    pnl_fig.show(renderer=renderer)

    micro_fig = go.Figure()
    micro_fig.add_trace(go.Scatter(
        x=idx, y=curr["mid_price"],
        name="mid"
    ))
    micro_fig.add_trace(go.Scatter(
        x=idx, y=curr["microprice"],
        name="microprice",
        line=dict(dash="dash")
    ))
    micro_fig.update_layout(
        title="Mid vs microprice",
        xaxis_title="timestamp",
        yaxis_title="price"
    )
    micro_fig.show(renderer=renderer)

    imb_fig = go.Figure()
    imb_fig.add_trace(go.Scatter(
        x=idx, y=curr["imbalance"],
        name="imbalance"
    ))
    imb_fig.update_layout(
        title="Top-3 depth imbalance",
        xaxis_title="timestamp",
        yaxis_title="imbalance"
    )
    imb_fig.show(renderer=renderer)


def summarize_inferred_fills(book: pd.DataFrame) -> pd.DataFrame:
    events = book[book["likely_fill"]].copy()

    if events.empty:
        return pd.DataFrame(columns=[
            "timestamp", "mid_price", "bid_price_1", "ask_price_1",
            "profit_and_loss", "pnl_change", "inferred_side"
        ])

    events["inferred_side"] = np.select(
        [events["likely_buy_fill"], events["likely_sell_fill"]],
        ["BUY", "SELL"],
        default="UNCLEAR"
    )

    cols = [
        "timestamp", "mid_price", "bid_price_1", "ask_price_1",
        "profit_and_loss", "pnl_change", "spread", "inferred_side"
    ]
    return events[cols].reset_index(drop=True)


# -------------------------
# Example usage
# -------------------------

df = load_activity_log("18229.log")

tomatoes = preprocess_product(df, "TOMATOES")
emeralds = preprocess_product(df, "EMERALDS")

plot_interval(tomatoes, t0=3000, t1=12000, renderer="browser")
plot_interval(emeralds, t0=0, t1=12000, renderer="browser")

print(summarize_inferred_fills(tomatoes).head(20))
print(summarize_inferred_fills(emeralds).head(20))