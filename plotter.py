import json
import io
import pandas as pd
import plotly.graph_objects as go
import plotly.subplots as _ps
make_subplots = _ps.make_subplots
import ipywidgets as widgets
import re
import os

class Plotter:

    def __init__(self, prices_path, trades_path=None):
        # If trades_path is given, load CSV files directly (single path or list)
        if trades_path is not None:
            if isinstance(prices_path, list):
                price_frames = []
                trade_frames = []
                cumulative_offset = 0
                for p, t in zip(prices_path, trades_path):
                    df_p = pd.read_csv(p, delimiter=";")
                    df_t = pd.read_csv(t, delimiter=";")
                    day_max = int(df_p["timestamp"].max()) if "timestamp" in df_p.columns and len(df_p) else 0
                    df_p["timestamp"] = df_p["timestamp"] + cumulative_offset
                    df_t["timestamp"] = df_t["timestamp"] + cumulative_offset
                    price_frames.append(df_p)
                    trade_frames.append(df_t)
                    cumulative_offset += day_max + 100
                self.prices = pd.concat(price_frames, ignore_index=True)
                self.trades = pd.concat(trade_frames, ignore_index=True).rename(columns={"symbol": "product"})
            else:
                self.prices = pd.read_csv(prices_path, delimiter=";")
                self.trades = pd.read_csv(trades_path, delimiter=";").rename(columns={
                    "symbol": "product"
                })
            self.products = list(self.prices["product"].unique())
            return

        # Otherwise treat prices_path as a directory and auto-discover files
        directory_path = prices_path
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
            deduped_ob = curr_order_book.drop_duplicates("timestamp")
            bid_series = deduped_ob.set_index("timestamp")["bid_price_1"]
            ask_series = deduped_ob.set_index("timestamp")["ask_price_1"]
            colors = curr_trades.apply(lambda row: "green" if row["timestamp"] in ask_series.index and row["price"] >= ask_series.at[row["timestamp"]] else "red", axis=1)
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
    def __init__(self, log_path):
        """
        Parses a competition .log file (JSON) containing 'logs' and 'tradeHistory'.
        """
        data = self._load_data(log_path)

        ob_records = []
        market_trades = []

        # 1. Parse the order book and positions from lambdaLog
        for log_entry in data.get('logs', []):
            lambda_log_str = log_entry.get('lambdaLog', '')
            if not lambda_log_str:
                continue

            for line in lambda_log_str.strip().split('\n'):
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    
                    # Normalize ask volumes to positive numbers
                    for i in range(1, 4):
                        k = f"ask_volume_{i}"
                        if k in row and row[k] is not None:
                            row[k] = abs(row[k])
                    
                    ob_records.append(row)

                    for mt in row.get('market_trades', []):
                        if len(mt) >= 2:
                            market_trades.append({
                                'timestamp': row['timestamp'],
                                'product': row['product'],
                                'price': mt[0],
                                'quantity': abs(mt[1])
                            })
                except json.JSONDecodeError:
                    continue

        self.prices = pd.DataFrame(ob_records)
        self.market_trades = pd.DataFrame(market_trades)

        # 2. Parse own trades from tradeHistory
        own_trades = []
        for t in data.get('tradeHistory', []):
            is_buyer = (t.get('buyer') == 'SUBMISSION')
            is_seller = (t.get('seller') == 'SUBMISSION')
            
            if is_buyer or is_seller:
                own_trades.append({
                    'timestamp': t['timestamp'],
                    'product': t.get('symbol'),
                    'price': t['price'],
                    'quantity': t['quantity'],
                    'side': 'BUY' if is_buyer else 'SELL'
                })
                
        self.trades = pd.DataFrame(own_trades)

        # 3. Extract unique products
        if not self.prices.empty and "product" in self.prices.columns:
            self.products = sorted(self.prices["product"].dropna().unique())
        else:
            self.products = []

        # 4. Reconstruct Algorithm State & Metrics
        if not self.prices.empty:
            self._compute_metrics()

    def _load_data(self, log_path):
        """Load a competition submission log as {'logs': [...], 'tradeHistory': [...]}."""
        with open(log_path, 'r') as f:
            return json.load(f)

    def _compute_metrics(self):
        """
        Reverse-engineers the intermediate values from trader.py based on the 
        parsed order book and positions, appending them as columns.
        """
        for col in ["fair", "prior_fair", "linreg_fair", "aa_ceiling", "excess_position"]:
            self.prices[col] = None
            
        for product in self.products:
            mask = self.prices["product"] == product
            df_prod = self.prices[mask].sort_values("timestamp")
            
            fairs, prior_fairs, linreg_fairs, aa_ceilings, excesses = [], [], [], [], []
            
            if product == "ASH_COATED_OSMIUM":
                base_fair = 10000
                alpha = 0.075
                recent_mid = base_fair
                
                for _, row in df_prod.iterrows():
                    pos = row.get("position", 0)
                    pos = 0 if pd.isna(pos) else pos
                    
                    fair = 0.70 * base_fair + 0.30 * recent_mid - alpha * pos
                    
                    fairs.append(round(fair, 2))
                    prior_fairs.append(None)
                    linreg_fairs.append(None)
                    aa_ceilings.append(None)
                    excesses.append(None)
                    
                    bid = row.get("bid_price_1")
                    ask = row.get("ask_price_1")
                    if pd.notna(bid) and pd.notna(ask):
                        recent_mid = (bid + ask) / 2
                        
            elif product == "INTARIAN_PEPPER_ROOT":
                initial_fair = None
                for _, row in df_prod.iterrows():
                    bid = row.get("bid_price_1")
                    ask = row.get("ask_price_1")
                    if pd.notna(bid) and pd.notna(ask):
                        initial_fair = round(((bid + ask) / 2) / 1000) * 1000
                        break
                        
                n = 0
                sx = 0.0; sy = 0.0; sxx = 0.0; sxy = 0.0
                core_target = 80 - 8 
                
                for _, row in df_prod.iterrows():
                    ts = row["timestamp"]
                    pos = row.get("position", 0)
                    pos = 0 if pd.isna(pos) else pos
                    
                    prior_fair = 0.1 * (ts / 100) + initial_fair if initial_fair is not None else None
                    prior_fairs.append(round(prior_fair, 2) if prior_fair else None)
                    
                    bid = row.get("bid_price_1")
                    ask = row.get("ask_price_1")
                    linreg_fair = None
                    
                    if pd.notna(bid) and pd.notna(ask):
                        actual_mid = (bid + ask) / 2
                        x = float(n)
                        n += 1
                        sx += x
                        sy += actual_mid
                        sxx += x * x
                        sxy += actual_mid * x
                        
                    if n >= 2:
                        denom = n * sxx - sx * sx
                        if denom == 0:
                            linreg_fair = sy / n
                        else:
                            b = (n * sxy - sx * sy) / denom
                            a = (sy - b * sx) / n
                            linreg_fair = a + b * n 
                    linreg_fairs.append(round(linreg_fair, 2) if linreg_fair else None)
                    
                    fair_base = linreg_fair if linreg_fair is not None else prior_fair
                    if fair_base is not None:
                        excess = max(0, pos - core_target)
                        fair = fair_base - 0.1 * excess
                        aa_ceiling = fair + 8
                    else:
                        excess = None
                        fair = None
                        aa_ceiling = None
                        
                    fairs.append(round(fair, 2) if fair else None)
                    excesses.append(excess)
                    aa_ceilings.append(round(aa_ceiling, 2) if aa_ceiling else None)
                    
            else:
                fairs = [None] * len(df_prod)
                prior_fairs = [None] * len(df_prod)
                linreg_fairs = [None] * len(df_prod)
                aa_ceilings = [None] * len(df_prod)
                excesses = [None] * len(df_prod)
                
            self.prices.loc[mask, "fair"] = fairs
            self.prices.loc[mask, "prior_fair"] = prior_fairs
            self.prices.loc[mask, "linreg_fair"] = linreg_fairs
            self.prices.loc[mask, "aa_ceiling"] = aa_ceilings
            self.prices.loc[mask, "excess_position"] = excesses

    def _plot_interval(self, product, t0, t1, renderer=None, ymin=None, ymax=None):
        ob = self.prices[self.prices["product"] == product].copy()
        curr_order_book = ob[(ob["timestamp"] >= t0) & (ob["timestamp"] <= t1)]

        if curr_order_book.empty:
            print(f"No order book data for {product} in this interval.")
            return

        idx = curr_order_book["timestamp"]
        fig = go.Figure()

        # --- Base Order Book Traces ---
        if "mid_price" in curr_order_book.columns:
            fig.add_trace(go.Scattergl(
                x=idx, y=curr_order_book["mid_price"],
                name="Mid Price", line=dict(width=2, color="blue")
            ))

        # --- Dynamic Computed Metrics ---
        if "fair" in curr_order_book.columns and curr_order_book["fair"].notna().any():
            fig.add_trace(go.Scattergl(
                x=idx, y=curr_order_book["fair"],
                name="Fair Value", line=dict(width=3, color="darkorange", dash="dash")
            ))

        # Add position and custom metrics to the hover tooltip as invisible traces
        custom_metrics = ["position", "prior_fair", "linreg_fair", "aa_ceiling", "excess_position"]
        for col in custom_metrics:
            if col in curr_order_book.columns and curr_order_book[col].notna().any():
                fig.add_trace(go.Scattergl(
                    x=idx, y=curr_order_book[col],
                    name=col.replace("_", " ").title(),
                    mode="lines",
                    line=dict(width=0), # Invisible line, purely for the unified hover
                    showlegend=False,
                    hoverinfo="y+name"
                ))

        # --- Bids ---
        for i in range(1, 4):
            if f"bid_price_{i}" in curr_order_book.columns:
                fig.add_trace(go.Scattergl(
                    x=idx, y=curr_order_book[f"bid_price_{i}"],
                    name=f"Bid {i}", customdata=curr_order_book[[f"bid_volume_{i}"]],
                    hovertemplate="%{y} (Vol: %{customdata[0]})<extra></extra>",
                    line=dict(color="green", dash="dot" if i > 1 else "solid"), opacity=1.0 - (i * 0.2)
                ))

        # --- Asks ---
        for i in range(1, 4):
            if f"ask_price_{i}" in curr_order_book.columns:
                fig.add_trace(go.Scattergl(
                    x=idx, y=curr_order_book[f"ask_price_{i}"],
                    name=f"Ask {i}", customdata=curr_order_book[[f"ask_volume_{i}"]],
                    hovertemplate="%{y} (Vol: %{customdata[0]})<extra></extra>",
                    line=dict(color="red", dash="dot" if i > 1 else "solid"), opacity=1.0 - (i * 0.2)
                ))

        # --- Own Trades ---
        if not self.trades.empty:
            curr_trades = self.trades[self.trades["product"] == product].copy()
            curr_trades = curr_trades[(curr_trades["timestamp"] >= t0) & (curr_trades["timestamp"] <= t1)]
            
            if not curr_trades.empty:
                deduped_ob = curr_order_book.drop_duplicates("timestamp")[["timestamp", "position"]]
                curr_trades = curr_trades.merge(deduped_ob, on="timestamp", how="left")
                
                # The position logged at a timestamp is the position BEFORE the trades happen
                curr_trades["pos_before"] = curr_trades["position"].fillna("Unknown")
                
                # Calculate the position AFTER this specific trade execution
                def calc_after(row):
                    if row["pos_before"] == "Unknown":
                        return "Unknown"
                    return row["pos_before"] + (row["quantity"] if row["side"] == "BUY" else -row["quantity"])
                
                curr_trades["pos_after"] = curr_trades.apply(calc_after, axis=1)

                for side, color, symbol, name in [("BUY", "lime", "triangle-up", "MY BUY"), ("SELL", "red", "triangle-down", "MY SELL")]:
                    subset = curr_trades[curr_trades["side"] == side]
                    if not subset.empty:
                        max_qty = subset["quantity"].max()
                        max_qty = max_qty if max_qty > 0 else 1
                        
                        # Scaled down the marker sizes
                        sizes = 6 + 10 * (subset["quantity"] / max_qty) 
                        
                        fig.add_trace(go.Scattergl(
                            x=subset["timestamp"], y=subset["price"],
                            mode="markers", name=name,
                            customdata=subset[["quantity", "pos_before", "pos_after"]],
                            marker=dict(symbol=symbol, size=sizes, color=color, line=dict(width=1, color="black")),
                            hovertemplate="<b>" + name + "</b><br>Price: %{y}<br>Vol: %{customdata[0]}<br>Pos Before: %{customdata[1]}<br>Pos After: %{customdata[2]}<extra></extra>"
                        ))

        # --- Layout formatting ---
        layout_kwargs = dict(
            title=f"{product} Order Book & Trades",
            xaxis_title="Timestamp",
            yaxis_title="Price",
            legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
            margin=dict(r=150),
            hovermode="x unified" 
        )
        if ymin is not None or ymax is not None:
            layout_kwargs["yaxis_range"] = [ymin, ymax]
        fig.update_layout(**layout_kwargs)
        fig.show(renderer=renderer)

    def visualize_orderbook(self, product=None, t0=None, t1=None, renderer=None, ymin=None, ymax=None):
        def plot(product):
            ob = self.prices[self.prices["product"] == product]
            if ob.empty: return
            start = t0 if t0 is not None else ob["timestamp"].min()
            end = t1 if t1 is not None else ob["timestamp"].max()
            self._plot_interval(product, start, end, renderer=renderer, ymin=ymin, ymax=ymax)

        if product is not None:
            plot(product)
        else:
            if not self.products: return
            widgets.interact(plot, product=widgets.Dropdown(options=self.products, description="Product:"))


class SubmissionLogVisualizer(LogVisualizer):
    """
    Visualizer for logs produced by pepper_holder_v7-style traders, where each
    row already carries flattened internal_state fields (fair, fair_raw, linreg_*, ...).

    On top of LogVisualizer:
      - 'fair' (unified from internal_state) is always plotted and shown in hover.
      - A SelectMultiple dropdown lets you overlay any internal_state column on click.
    """

    BASE_COLS = {
        'timestamp', 'product', 'mid_price', 'position', 'log',
        'own_trades', 'market_trades', 'fair',
        'bid_price_1', 'bid_price_2', 'bid_price_3',
        'bid_volume_1', 'bid_volume_2', 'bid_volume_3',
        'ask_price_1', 'ask_price_2', 'ask_price_3',
        'ask_volume_1', 'ask_volume_2', 'ask_volume_3',
    }

    def _load_data(self, log_path):
        """Accept both IMC submission JSON and prosperity4bt sectioned output."""
        with open(log_path, 'r') as f:
            text = f.read()

        stripped = text.lstrip()
        if stripped.startswith('{'):
            return json.loads(text)

        # prosperity4bt sectioned format: "Sandbox logs:" / "Activities log:" / "Trade History:"
        sandbox_section = text.split("Activities log:", 1)[0]
        sandbox_section = sandbox_section.split("Sandbox logs:\n", 1)[-1]

        decoder = json.JSONDecoder()
        logs = []
        idx = 0
        while idx < len(sandbox_section):
            while idx < len(sandbox_section) and sandbox_section[idx].isspace():
                idx += 1
            if idx >= len(sandbox_section):
                break
            obj, end = decoder.raw_decode(sandbox_section, idx)
            logs.append(obj)
            idx = end

        trades = []
        if "Trade History:" in text:
            trade_section = text.split("Trade History:", 1)[1]
            # prosperity4bt emits trailing commas; strip them for strict json
            trade_section = re.sub(r',\s*([}\]])', r'\1', trade_section)
            trades = json.loads(trade_section)

        return {"logs": logs, "tradeHistory": trades}

    def _compute_metrics(self):
        # Don't re-simulate fair — the rows already carry internal_state.
        # Unify: pepper logs fair_final, osmium logs fair. Coalesce to a 'fair' column.
        if 'fair_final' in self.prices.columns:
            if 'fair' not in self.prices.columns:
                self.prices['fair'] = pd.NA
            mask = self.prices['fair_final'].notna()
            self.prices.loc[mask, 'fair'] = self.prices.loc[mask, 'fair_final']

        # Columns available for overlay selection.
        self.internal_state_cols = sorted(
            c for c in self.prices.columns if c not in self.BASE_COLS
        )

    def _available_cols(self, product):
        df = self.prices[self.prices["product"] == product]
        return tuple(
            c for c in self.internal_state_cols
            if c in df.columns and df[c].notna().any()
        )

    def _plot_interval(self, product, t0, t1, renderer=None,
                       ymin=None, ymax=None, extra_cols=None):
        extra_cols = list(extra_cols or [])
        ob = self.prices[self.prices["product"] == product].copy()
        curr_order_book = ob[(ob["timestamp"] >= t0) & (ob["timestamp"] <= t1)]

        if curr_order_book.empty:
            print(f"No order book data for {product} in this interval.")
            return

        idx = curr_order_book["timestamp"]
        fig = go.Figure()

        # Mid
        if "mid_price" in curr_order_book.columns:
            fig.add_trace(go.Scattergl(
                x=idx, y=curr_order_book["mid_price"],
                name="Mid Price", line=dict(width=2, color="blue"),
                hovertemplate="Mid: %{y}<extra></extra>",
            ))

        # Fair (from internal_state, unified)
        if 'fair' in curr_order_book.columns and curr_order_book['fair'].notna().any():
            fair_series = pd.to_numeric(curr_order_book['fair'], errors='coerce')
            fig.add_trace(go.Scattergl(
                x=idx, y=fair_series,
                name='Fair', line=dict(width=3, color="darkorange", dash="dash"),
                hovertemplate="Fair: %{y:.3f}<extra></extra>",
            ))

        # Bids
        for i in range(1, 4):
            col = f"bid_price_{i}"
            if col in curr_order_book.columns:
                fig.add_trace(go.Scattergl(
                    x=idx, y=curr_order_book[col],
                    name=f"Bid {i}", customdata=curr_order_book[[f"bid_volume_{i}"]],
                    hovertemplate="%{y} (Vol: %{customdata[0]})<extra></extra>",
                    line=dict(color="green", dash="dot" if i > 1 else "solid"),
                    opacity=1.0 - (i * 0.2),
                ))
        # Asks
        for i in range(1, 4):
            col = f"ask_price_{i}"
            if col in curr_order_book.columns:
                fig.add_trace(go.Scattergl(
                    x=idx, y=curr_order_book[col],
                    name=f"Ask {i}", customdata=curr_order_book[[f"ask_volume_{i}"]],
                    hovertemplate="%{y} (Vol: %{customdata[0]})<extra></extra>",
                    line=dict(color="red", dash="dot" if i > 1 else "solid"),
                    opacity=1.0 - (i * 0.2),
                ))

        # User-selected internal_state overlays
        for col in extra_cols:
            if col not in curr_order_book.columns:
                continue
            s = curr_order_book[col]
            numeric = pd.to_numeric(s, errors="coerce")
            if numeric.notna().any():
                fig.add_trace(go.Scattergl(
                    x=idx, y=numeric, name=col,
                    line=dict(width=1.5),
                    hovertemplate=col + ": %{y}<extra></extra>",
                ))
            elif s.notna().any():
                # Non-numeric (e.g. skipped_reason, mm_bid_synth) — hover-only trace
                fig.add_trace(go.Scattergl(
                    x=idx, y=[None] * len(s), name=col,
                    mode="lines", line=dict(width=0), showlegend=True,
                    text=s.astype(str),
                    hovertemplate=col + ": %{text}<extra></extra>",
                ))

        # Own trades
        if not self.trades.empty:
            curr_trades = self.trades[self.trades["product"] == product].copy()
            curr_trades = curr_trades[
                (curr_trades["timestamp"] >= t0) & (curr_trades["timestamp"] <= t1)
            ]
            if not curr_trades.empty:
                deduped_ob = curr_order_book.drop_duplicates("timestamp")[["timestamp", "position"]]
                curr_trades = curr_trades.merge(deduped_ob, on="timestamp", how="left")
                curr_trades["pos_before"] = curr_trades["position"].fillna("Unknown")

                def calc_after(row):
                    if row["pos_before"] == "Unknown":
                        return "Unknown"
                    return row["pos_before"] + (row["quantity"] if row["side"] == "BUY" else -row["quantity"])

                curr_trades["pos_after"] = curr_trades.apply(calc_after, axis=1)

                for side, color, symbol, name in [
                    ("BUY", "lime", "triangle-up", "MY BUY"),
                    ("SELL", "red", "triangle-down", "MY SELL"),
                ]:
                    subset = curr_trades[curr_trades["side"] == side]
                    if subset.empty:
                        continue
                    max_qty = max(subset["quantity"].max(), 1)
                    sizes = 6 + 10 * (subset["quantity"] / max_qty)
                    fig.add_trace(go.Scattergl(
                        x=subset["timestamp"], y=subset["price"],
                        mode="markers", name=name,
                        customdata=subset[["quantity", "pos_before", "pos_after"]],
                        marker=dict(symbol=symbol, size=sizes, color=color,
                                    line=dict(width=1, color="black")),
                        hovertemplate="<b>" + name + "</b><br>Price: %{y}<br>"
                                      "Vol: %{customdata[0]}<br>"
                                      "Pos Before: %{customdata[1]}<br>"
                                      "Pos After: %{customdata[2]}<extra></extra>",
                    ))

        layout_kwargs = dict(
            title=f"{product} Order Book & Trades",
            xaxis_title="Timestamp",
            yaxis_title="Price",
            legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
            margin=dict(r=150),
            hovermode="x unified",
        )
        if ymin is not None or ymax is not None:
            layout_kwargs["yaxis_range"] = [ymin, ymax]
        fig.update_layout(**layout_kwargs)
        fig.show(renderer=renderer)

    def visualize_orderbook(self, product=None, t0=None, t1=None,
                            renderer=None, ymin=None, ymax=None):
        def plot(product, extra_cols):
            ob = self.prices[self.prices["product"] == product]
            if ob.empty:
                return
            start = t0 if t0 is not None else ob["timestamp"].min()
            end = t1 if t1 is not None else ob["timestamp"].max()
            self._plot_interval(product, start, end, renderer=renderer,
                                ymin=ymin, ymax=ymax, extra_cols=list(extra_cols))

        if product is not None:
            opts = self._available_cols(product)
            sm = widgets.SelectMultiple(
                options=opts, value=(), description="State:",
                rows=min(14, max(len(opts), 1)),
                layout=widgets.Layout(width="60%"),
            )
            widgets.interact(plot, product=widgets.fixed(product), extra_cols=sm)
        else:
            if not self.products:
                return
            dd_product = widgets.Dropdown(options=self.products, description="Product:")
            sm = widgets.SelectMultiple(
                options=self._available_cols(self.products[0]),
                value=(), description="State:",
                rows=14, layout=widgets.Layout(width="60%"),
            )

            def _on_product_change(change):
                sm.options = self._available_cols(change["new"])
                sm.value = ()

            dd_product.observe(_on_product_change, names="value")
            widgets.interact(plot, product=dd_product, extra_cols=sm)