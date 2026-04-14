import json
import io
import pandas as pd
import plotly.graph_objects as go
import plotly.subplots as _ps
make_subplots = _ps.make_subplots
import ipywidgets as widgets
import re
import os

class Plotter():

    def __init__(self, prices_path, trades_path):
        self.prices = pd.read_csv(prices_path, delimiter=";")
        self.trades = pd.read_csv(trades_path, delimiter=";").rename(columns={
            "symbol" : "product"
        })
        self.products = list(self.prices["product"].unique())

class Plotter:

    def __init__(self, directory_path):
        # Regex patterns to match files and extract the day number
        price_pattern = re.compile(r"prices_round_\d+_day_(-?\d+)\.csv$")
        trade_pattern = re.compile(r"trades_round_\d+_day_(-?\d+)\.csv$")

        price_files = {}
        trade_files = {}

        # Discover files and map them by day
        for filename in os.listdir(directory_path):
            price_match = price_pattern.match(filename)
            trade_match = trade_pattern.match(filename)

            if price_match:
                day = int(price_match.group(1))
                price_files[day] = os.path.join(directory_path, filename)
            elif trade_match:
                day = int(trade_match.group(1))
                trade_files[day] = os.path.join(directory_path, filename)

        # Sort all unique days present in either prices or trades
        days_sorted = sorted(set(price_files.keys()) | set(trade_files.keys()))

        prices_dfs = []
        trades_dfs = []
        cumulative_offset = 0

        for day in days_sorted:
            # --- Load prices for the day ---
            day_max_timestamp = 0
            if day in price_files:
                df_prices = pd.read_csv(price_files[day], delimiter=";")
                df_prices["timestamp"] += cumulative_offset
                prices_dfs.append(df_prices)

                # Determine the max timestamp for this day
                if "timestamp" in df_prices.columns:
                    # Subtract the offset to get the original max timestamp
                    day_max_timestamp = (
                        df_prices["timestamp"].max() - cumulative_offset
                    )

            # --- Load trades for the day ---
            if day in trade_files:
                df_trades = pd.read_csv(trade_files[day], delimiter=";")
                if "symbol" in df_trades.columns:
                    df_trades = df_trades.rename(columns={"symbol": "product"})
                df_trades["timestamp"] += cumulative_offset
                trades_dfs.append(df_trades)

            # Update the cumulative offset for the next day
            # Add 100 because timestamps increase in increments of 100
            cumulative_offset += day_max_timestamp + 100

        # Concatenate all dataframes
        self.prices = (
            pd.concat(prices_dfs, ignore_index=True)
            if prices_dfs else pd.DataFrame()
        )
        self.trades = (
            pd.concat(trades_dfs, ignore_index=True)
            if trades_dfs else pd.DataFrame()
        )

        # Extract unique products
        if not self.prices.empty and "product" in self.prices.columns:
            self.products = sorted(self.prices["product"].unique())
        else:
            self.products = []

    def _plot_interval(self, product, t0, t1, renderer=None, ymin=None, ymax=None):
        # --- filter by product ---
        ob = self.prices[(self.prices["product"] == product) & (self.prices["mid_price"]) != 0]
        tr = self.trades[self.trades["product"] == product]

        # --- filter by timestamp ---
        curr_order_book = ob[
            (ob["timestamp"] >= t0) &
            (ob["timestamp"] <= t1)
        ]

        if curr_order_book.empty:
            print("No data in this interval")
            return

        idx = curr_order_book["timestamp"]

        curr_trades = tr[
            (tr["timestamp"] >= t0) &
            (tr["timestamp"] <= t1)
        ]

        fig = go.Figure()

        # --- mid ---
        fig.add_trace(go.Scattergl(
            x=idx,
            y=curr_order_book["mid_price"],
            name="mid",
            line=dict(width=3)
        ))

        # --- bids ---
        for i in range(1, 4):
            fig.add_trace(go.Scattergl(
                x=idx,
                y=curr_order_book[f"bid_price_{i}"],
                name=f"bid_price_{i}",
                customdata=curr_order_book[[f"bid_volume_{i}"]],
                hovertemplate=
                    f"Bid Level {i}<br>" +
                    "Price: %{y}<br>" +
                    "Volume: %{customdata[0]}<br>" +
                    "Time: %{x}<extra></extra>"
            ))

        # --- asks ---
        for i in range(1, 4):
            fig.add_trace(go.Scattergl(
                x=idx,
                y=curr_order_book[f"ask_price_{i}"],
                name=f"ask_price_{i}",
                customdata=curr_order_book[[f"ask_volume_{i}"]],
                hovertemplate=
                    f"Ask Level {i}<br>" +
                    "Price: %{y}<br>" +
                    "Volume: %{customdata[0]}<br>" +
                    "Time: %{x}<extra></extra>"
            ))

        # --- trades ---
        if not curr_trades.empty:
            bid_series = curr_order_book.set_index("timestamp")["bid_price_1"]
            ask_series = curr_order_book.set_index("timestamp")["ask_price_1"]
            colors = curr_trades.apply(lambda row : "green" if row["timestamp"] in ask_series.index and row["price"] >= ask_series.loc[row["timestamp"]] else "red", axis=1)
            trade_prices = curr_trades["price"].to_numpy()
            sizes = curr_trades["quantity"].to_numpy()
            sizes = 5 + 15 * (sizes / sizes.max())

            fig.add_trace(go.Scattergl(
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

        layout_kwargs = dict(
            title=f"{product} orderbook + trades",
            xaxis_title="timestamp",
            yaxis_title="price",
            legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
            margin=dict(r=150),
        )
        if ymin is not None or ymax is not None:
            layout_kwargs["yaxis_range"] = [ymin, ymax]
        fig.update_layout(**layout_kwargs)

        fig.show(renderer=renderer)

        # --- spread ---
        spread = curr_order_book["ask_price_1"] - curr_order_book["bid_price_1"]

        spread_fig = go.Figure()
        spread_fig.add_trace(go.Scattergl(
            x=idx,
            y=spread,
            name="spread",
            line=dict(width=2)
        ))

        spread_fig.update_layout(
            title=f"{product} spread",
            xaxis_title="timestamp",
            yaxis_title="spread"
        )

        spread_fig.show(renderer=renderer)

    def visualize_orderbook(self, product=None, t0=None, t1=None, renderer=None,
                            ymin=None, ymax=None):
        """
        Parameters
        ----------
        product    : str, optional — plot a single product directly.
                     If None, shows an interactive dropdown.
        t0, t1     : int, optional — timestamp range. Defaults to full range.
        renderer   : str, optional — plotly renderer, e.g. "browser" to open
                     in a browser tab, "notebook" for inline, etc.
        ymin, ymax : float, optional — price axis range for the orderbook chart.
        """
        def plot(product):
            ob = self.prices[self.prices["product"] == product]
            start = t0 if t0 is not None else ob["timestamp"].min()
            end = t1 if t1 is not None else ob["timestamp"].max()
            self._plot_interval(product, start, end, renderer=renderer,
                                ymin=ymin, ymax=ymax)

        if product is not None:
            plot(product)
        else:
            dropdown = widgets.Dropdown(
                options=self.products,
                description="Product:"
            )
            widgets.interact(plot, product=dropdown)


 
class LogVisualizer:
    """
    Parses and visualizes trading competition logs.
 
    Log format expected
    -------------------
    Outer JSON:
      "logs"          : list of blocks, each with a "lambdaLog" multiline string
      "activitiesLog" : optional CSV string with profit_and_loss per (timestamp, product)
 
    Each lambdaLog line is a JSON object with:
      timestamp, product,
      bid_price_{1-3}, bid_volume_{1-3},
      ask_price_{1-3}, ask_volume_{1-3},
      mid_price,
      own_trades    : [[price, quantity, ts], ...]   (quantity > 0 = buy, < 0 = sell)
      market_trades : [[price, quantity, ts], ...]
      position      : int
      log           : str  (free-form debug text)
 
    Visualisation — one unified figure per product with panels:
    ─────────────────────────────────────────────────────────────
    1. Order book  — mid price, bid/ask levels 1-3, spread band
                     own trades: ▲ green = buy, ▼ red = sell (sized by qty)
                     market trades: ● circle (green above mid, red below, sized by qty)
    2. Position    — net inventory over time
    3. PnL         — profit_and_loss (only if activitiesLog present)
    4. Spread      — best ask minus best bid
    """
 
    def __init__(self, log_path=None):
        self.df        = None   # order-book rows
        self.own_df    = None   # own trades
        self.market_df = None   # market trades
 
        if log_path is not None:
            self.parse_logs(log_path)
 
    # ------------------------------------------------------------------ #
    #  Parsing                                                             #
    # ------------------------------------------------------------------ #
 
    def parse_logs(self, filepath):
        """
        Parse a competition log file.
 
        Returns
        -------
        df         : pd.DataFrame — order book (one row per product × timestamp)
        own_df     : pd.DataFrame — own trades with 'side' column ('buy' / 'sell')
        market_df  : pd.DataFrame — market trades
        """
        with open(filepath, "r") as f:
            outer = json.load(f)
 
        rows          = []
        own_trades    = []
        market_trades = []
 
        for block in outer.get("logs", []):
            # ---- order book + market trades from lambdaLog -------------
            lambda_log = block.get("lambdaLog", "")
            if not lambda_log:
                continue
 
            for line in lambda_log.split("\n"):
                line = line.strip()
                if not line:
                    continue
 
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
 
                product = obj.get("product")
                rows.append(obj)
 
                for t in obj.get("market_trades", []):
                    if not isinstance(t, list) or len(t) < 3:
                        continue
                    price, quantity, ts = t[0], t[1], t[2]
                    market_trades.append({
                        "timestamp": ts,
                        "product":   product,
                        "price":     price,
                        "quantity":  abs(quantity),
                    })
 
        # ---- own trades from top-level tradeHistory --------------------
        for entry in outer.get("tradeHistory", []):
            buyer  = entry.get("buyer", "")
            seller = entry.get("seller", "")
            if buyer != "SUBMISSION" and seller != "SUBMISSION":
                continue
            own_trades.append({
                "timestamp": entry["timestamp"],
                "product":   entry["symbol"],
                "price":     entry["price"],
                "quantity":  entry["quantity"],
                "side":      "buy" if buyer == "SUBMISSION" else "sell",
            })
 
        df = pd.DataFrame(rows)
 
        # Competition stores ask volumes as negative — normalise to positive
        for i in range(1, 4):
            col = f"ask_volume_{i}"
            if col in df.columns:
                df[col] = df[col].abs()
 
        # ---- merge PnL from activitiesLog if present -------------------
        if "activitiesLog" in outer:
            act = pd.read_csv(io.StringIO(outer["activitiesLog"]), sep=";")
            act = act.drop_duplicates(subset=["timestamp", "product"])
            df = df.merge(
                act[["timestamp", "product", "profit_and_loss"]],
                on=["timestamp", "product"],
                how="left",
            )
 
        df = df.sort_values(["product", "timestamp"]).reset_index(drop=True)
 
        own_df = pd.DataFrame(own_trades)
        if not own_df.empty:
            own_df = own_df.sort_values("timestamp").reset_index(drop=True)
 
        market_df = pd.DataFrame(market_trades)
        if not market_df.empty:
            market_df = market_df.sort_values("timestamp").reset_index(drop=True)
 
        self.df        = df
        self.own_df    = own_df
        self.market_df = market_df
 
        products = sorted(df["product"].dropna().unique().tolist())
        print(
            f"Parsed {len(df)} order-book rows | "
            f"{len(own_df)} own trades | "
            f"{len(market_df)} market trades | "
            f"products: {products}"
        )
        return df, own_df, market_df
 
    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #
 
    @staticmethod
    def _mid_series(ob):
        """Deduplicated mid-price series indexed by timestamp."""
        return (
            ob.drop_duplicates("timestamp")
            .set_index("timestamp")["mid_price"]
            .sort_index()
        )
 
    @staticmethod
    def _color_vs_mid(prices, timestamps, mid_ser):
        """Green if price >= nearest mid, red otherwise."""
        aligned = mid_ser.reindex(timestamps, method="nearest").to_numpy()
        return ["#2ca02c" if p >= m else "#d62728"
                for p, m in zip(prices, aligned)]
 
    # ------------------------------------------------------------------ #
    #  Core plot                                                           #
    # ------------------------------------------------------------------ #
 
    def _plot_interval(self, product, t0, t1):
        ob = self.df[self.df["product"] == product].copy()
        ob = ob[(ob["timestamp"] >= t0) & (ob["timestamp"] <= t1)].sort_values("timestamp")
 
        if ob.empty:
            print(f"No order-book data for {product} in [{t0}, {t1}]")
            return
 
        has_pnl      = ("profit_and_loss" in ob.columns and
                        ob["profit_and_loss"].notna().any())
        has_position = "position" in ob.columns
 
        idx     = ob["timestamp"]
        mid_ser = self._mid_series(ob)
 
        # ═══════════════════════════════════════════════════════════════ #
        #  Figure 1 — order book + trades                                 #
        # ═══════════════════════════════════════════════════════════════ #
        fig = go.Figure()
 
        # mid
        fig.add_trace(go.Scatter(
            x=idx,
            y=ob["mid_price"],
            name="mid",
            line=dict(width=3)
        ))
 
        # bids
        for i in range(1, 4):
            fig.add_trace(go.Scatter(
                x=idx,
                y=ob[f"bid_price_{i}"],
                name=f"bid_price_{i}",
                customdata=ob[[f"bid_volume_{i}"]],
                hovertemplate=(
                    f"Bid Level {i}<br>"
                    "Price: %{y}<br>"
                    "Volume: %{customdata[0]}<br>"
                    "Time: %{x}<extra></extra>"
                )
            ))
 
        # asks
        for i in range(1, 4):
            fig.add_trace(go.Scatter(
                x=idx,
                y=ob[f"ask_price_{i}"],
                name=f"ask_price_{i}",
                customdata=ob[[f"ask_volume_{i}"]],
                hovertemplate=(
                    f"Ask Level {i}<br>"
                    "Price: %{y}<br>"
                    "Volume: %{customdata[0]}<br>"
                    "Time: %{x}<extra></extra>"
                )
            ))
 
        # market trades
        if self.market_df is not None and not self.market_df.empty:
            mkt = self.market_df[self.market_df["product"] == product]
            mkt = mkt[(mkt["timestamp"] >= t0) & (mkt["timestamp"] <= t1)]
 
            if not mkt.empty:
                colors = self._color_vs_mid(mkt["price"], mkt["timestamp"], mid_ser)
                sizes  = 5 + 15 * (mkt["quantity"] / mkt["quantity"].max())
 
                fig.add_trace(go.Scatter(
                    x=mkt["timestamp"],
                    y=mkt["price"],
                    mode="markers",
                    name="market trades",
                    customdata=mkt["quantity"],
                    marker=dict(
                        symbol="circle",
                        size=sizes,
                        color=colors,
                        opacity=0.6,
                        line=dict(width=1)
                    ),
                    hovertemplate=(
                        "Market Trade<br>"
                        "Price: %{y}<br>"
                        "Quantity: %{customdata}<br>"
                        "Time: %{x}<extra></extra>"
                    )
                ))
 
        # own trades — buys (triangle-up) and sells (triangle-down)
        if self.own_df is not None and not self.own_df.empty:
            own = self.own_df[self.own_df["product"] == product].copy()
            own = own[(own["timestamp"] >= t0) & (own["timestamp"] <= t1)]
 
            if not own.empty:
                # Own trade timestamps match ob exactly — join directly.
                ob_indexed = (
                    ob.drop_duplicates("timestamp")
                    .set_index("timestamp")
                    .sort_index()
                )
 
                if has_position:
                    own["position_after"] = (
                        ob_indexed["position"]
                        .reindex(own["timestamp"])
                        .values
                    ) + own.apply(
                        lambda r: r["quantity"] if r["side"] == "buy" else -r["quantity"],
                        axis=1
                    ).values
 
                if has_pnl:
                    own["pnl_after"] = (
                        ob_indexed["profit_and_loss"]
                        .reindex(own["timestamp"])
                        .values
                    )
 
                max_qty = own["quantity"].abs().max()
 
                for side, symbol, color, label in [
                    ("buy",  "triangle-up",   "green", "own buy"),
                    ("sell", "triangle-down", "red",   "own sell"),
                ]:
                    side_df = own[own["side"] == side]
                    if side_df.empty:
                        continue
 
                    sizes = 8 + 14 * (side_df["quantity"].abs() / max_qty)
 
                    cd_cols = ["quantity"]
                    hover = (
                        f"{label.title()}<br>"
                        "Price: %{y}<br>"
                        "Quantity: %{customdata[0]}<br>"
                    )
                    col_idx = 1
                    if has_position:
                        cd_cols += ["position_after"]
                        hover += f"Position after: %{{customdata[{col_idx}]}}<br>"
                        col_idx += 1
                    hover += "Time: %{x}<extra></extra>"
 
                    fig.add_trace(go.Scatter(
                        x=side_df["timestamp"],
                        y=side_df["price"],
                        mode="markers",
                        name=label,
                        customdata=side_df[cd_cols],
                        marker=dict(
                            symbol=symbol,
                            size=sizes,
                            color=color,
                            line=dict(width=1)
                        ),
                        hovertemplate=hover
                    ))
 
        fig.update_layout(
            title=f"{product} orderbook + trades",
            xaxis_title="timestamp",
            yaxis_title="price",
            legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
            margin=dict(r=150)
        )
        fig.show()
 
        # ═══════════════════════════════════════════════════════════════ #
        #  Figure 2 — position                                            #
        # ═══════════════════════════════════════════════════════════════ #
        if has_position:
            pos_fig = go.Figure()
            pos = ob.drop_duplicates("timestamp")
            pos_fig.add_trace(go.Scatter(
                x=pos["timestamp"],
                y=pos["position"],
                name="position",
                line=dict(width=2)
            ))
            pos_fig.update_layout(
                title=f"{product} position",
                xaxis_title="timestamp",
                yaxis_title="position"
            )
            pos_fig.show()
 
        # ═══════════════════════════════════════════════════════════════ #
        #  Figure 3 — PnL                                                 #
        # ═══════════════════════════════════════════════════════════════ #
        if has_pnl:
            pnl_fig = go.Figure()
            pnl = ob.drop_duplicates("timestamp")
            pnl_fig.add_trace(go.Scatter(
                x=pnl["timestamp"],
                y=pnl["profit_and_loss"],
                name="PnL",
                line=dict(width=2)
            ))
            pnl_fig.update_layout(
                title=f"{product} PnL",
                xaxis_title="timestamp",
                yaxis_title="profit and loss"
            )
            pnl_fig.show()
 
        # ═══════════════════════════════════════════════════════════════ #
        #  Figure 4 — spread                                              #
        # ═══════════════════════════════════════════════════════════════ #
        spread_fig = go.Figure()
        spread_fig.add_trace(go.Scatter(
            x=idx,
            y=ob["ask_price_1"] - ob["bid_price_1"],
            name="spread",
            line=dict(width=2)
        ))
        spread_fig.update_layout(
            title=f"{product} spread",
            xaxis_title="timestamp",
            yaxis_title="spread"
        )
        spread_fig.show()
 
    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #
 
    def visualize(self, log_path=None, t0=None, t1=None):
        """
        Load (if needed) and launch an interactive product selector widget.
 
        Parameters
        ----------
        log_path : str, optional
            Path to the log JSON file.  If omitted the last parsed data is used.
        t0, t1 : int, optional
            Timestamp range to display.  Defaults to full range per product.
 
        Examples
        --------
        viz = LogVisualizer("round1.json")
        viz.visualize()                              # full range
        viz.visualize(t0=100_000, t1=200_000)       # slice
        viz.visualize("round2.json")                # load new file and visualize
        """
        if log_path is not None:
            self.parse_logs(log_path)
 
        if self.df is None:
            raise RuntimeError(
                "No data loaded — pass a log_path or call parse_logs() first."
            )
 
        products = sorted(self.df["product"].dropna().unique())
        dropdown = widgets.Dropdown(options=products, description="Product:")
 
        def plot(product):
            ob    = self.df[self.df["product"] == product]
            start = t0 if t0 is not None else int(ob["timestamp"].min())
            end   = t1 if t1 is not None else int(ob["timestamp"].max())
            self._plot_interval(product, start, end)
 
        widgets.interact(plot, product=dropdown)
 
    def summary(self):
        """
        Print a per-product summary of own-trade activity.
        Useful for a quick sanity-check after parsing.
        """
        if self.own_df is None or self.own_df.empty:
            print("No own trades parsed yet.")
            return
 
        for product, grp in self.own_df.groupby("product"):
            buys  = grp[grp["side"] == "buy"]
            sells = grp[grp["side"] == "sell"]
            print(f"\n{'─' * 44}")
            print(f"  {product}")
            print(f"{'─' * 44}")
            print(f"  Total trades  : {len(grp)}")
            if not buys.empty:
                print(f"  Buys          : {len(buys)}  "
                      f"| avg px {buys['price'].mean():.2f}  "
                      f"| total vol {buys['quantity'].sum():.0f}")
            else:
                print("  Buys          : 0")
            if not sells.empty:
                print(f"  Sells         : {len(sells)}  "
                      f"| avg px {sells['price'].mean():.2f}  "
                      f"| total vol {sells['quantity'].abs().sum():.0f}")
            else:
                print("  Sells         : 0")
            print(f"  Gross volume  : {grp['quantity'].abs().sum():.0f}")