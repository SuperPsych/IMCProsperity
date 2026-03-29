"""
grid_search.py
==============
Grid-search hyperparameters for a prosperity4bt trader.
Dependencies: seaborn, matplotlib, pandas (for heatmap only).
 
The original trader.py is never modified — all runs use a temp copy.
 
Usage from a notebook
---------------------
from grid_search import grid_search
 
results = grid_search(
    trader_file="trader.py",
    round_num=0,
    product="TOMATOES",
    param_grid={
        "TOMATOES_POSITION_LIMIT":       [30, 40, 50, 60],
        "TOMATOES_SPIKE_THRESHOLD":      [3, 5, 7, 10],
        "TOMATOES_SPIKE_POSITION_GUARD": [5],   # single value = fixed
    },
    top_n=5,
)
"""
 
import re
import ast
import os
import subprocess
import itertools
import tempfile
from pathlib import Path
from typing import Any
 
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
 
 
# ── 1. Param injection ────────────────────────────────────────────────────────
 
_PARAMS_RE = re.compile(r"(PARAMS\s*=\s*)(\{[^{}]*\})", re.DOTALL)
 
def _inject_params(source: str, overrides: dict) -> str:
    """Return a new source string with PARAMS updated — original untouched."""
    match = _PARAMS_RE.search(source)
    if not match:
        raise ValueError("Could not find 'PARAMS = {...}' block in trader source.")
    existing = ast.literal_eval(match.group(2))
    existing.update(overrides)
    new_block = match.group(1) + repr(existing)
    return source[: match.start()] + new_block + source[match.end():]
 
 
# ── 2. Backtester runner ──────────────────────────────────────────────────────
 
_PNL_RE = re.compile(r"^([A-Z_]+):\s*([\d,]+)", re.MULTILINE)
 
def _run_backtest(trader_path: Path, round_num: int) -> dict[str, int]:
    proc = subprocess.run(
        ["prosperity4bt", str(trader_path), str(round_num)],
        capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    pnl: dict[str, int] = {}
    for m in _PNL_RE.finditer(output):
        product, value = m.group(1), m.group(2)
        pnl[product] = pnl.get(product, 0) + int(value.replace(",", ""))
    if not pnl:
        raise RuntimeError(
            f"Could not parse PnL from backtester.\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return pnl
 
 
# ── 3. Seaborn heatmap ────────────────────────────────────────────────────────
 
def _plot_heatmap(results: list[dict], x_key: str, y_key: str, product: str) -> None:
    df = pd.DataFrame(results)
    pivot = df.pivot(index=y_key, columns=x_key, values="pnl")
 
    fig, ax = plt.subplots(figsize=(max(6, len(pivot.columns) * 1.2),
                                    max(4, len(pivot.index) * 0.9)))
    sns.heatmap(
        pivot,
        ax=ax,
        annot=True,
        fmt=".0f",
        cmap="RdYlGn",
        linewidths=0.4,
        linecolor="white",
        cbar_kws={"label": f"{product} PnL"},
    )
    ax.set_title(f"{product} PnL grid search", fontsize=13, pad=12)
    ax.set_xlabel(x_key)
    ax.set_ylabel(y_key)
    plt.tight_layout()
    plt.show()
 
 
def _plot_bar(results: list[dict], key: str, product: str) -> None:
    df = pd.DataFrame(results).sort_values(key)
    fig, ax = plt.subplots(figsize=(max(6, len(df) * 0.8), 4))
    colors = ["#2ecc71" if v == df["pnl"].max() else "#3498db" for v in df["pnl"]]
    ax.bar(df[key].astype(str), df["pnl"], color=colors, edgecolor="white")
    ax.set_xlabel(key)
    ax.set_ylabel(f"{product} PnL")
    ax.set_title(f"{product} PnL vs {key}")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    plt.tight_layout()
    plt.show()
 
 
# ── 4. Grid search ────────────────────────────────────────────────────────────
 
def grid_search(
    trader_file: str,
    round_num: int,
    product: str,
    param_grid: dict[str, list[Any]],
    top_n: int = 5,
) -> list[dict]:
    trader_path = Path(trader_file).resolve()
    original_source = trader_path.read_text()   # read once, never write back
 
    keys   = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    print(f"Grid search: {len(combos)} combos | product={product} | round={round_num}\n")
 
    results = []
 
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, dir=trader_path.parent
    ) as tmp:
        tmp_path = Path(tmp.name)
 
    try:
        for i, combo in enumerate(combos, 1):
            overrides = dict(zip(keys, combo))
            tmp_path.write_text(_inject_params(original_source, overrides))
 
            try:
                pnl = _run_backtest(tmp_path, round_num).get(product, 0)
            except Exception as e:
                print(f"  [{i}/{len(combos)}] {overrides}  →  ERROR: {e}")
                pnl = float("nan")
 
            results.append({**overrides, "pnl": pnl})
            print(f"  [{i}/{len(combos)}] {overrides}  →  {product} PnL = {pnl:,}")
 
    finally:
        tmp_path.unlink(missing_ok=True)
 
    results.sort(key=lambda r: r["pnl"] if r["pnl"] == r["pnl"] else float("-inf"), reverse=True)
 
    # Plot
    varied = [k for k in keys if len(param_grid[k]) > 1]
    if len(varied) >= 2:
        _plot_heatmap(results, varied[0], varied[1], product)
    elif len(varied) == 1:
        _plot_bar(results, varied[0], product)
 
    # Top-N
    print(f"{'─'*50}\nTop {top_n} for {product}:\n{'─'*50}")
    for rank, r in enumerate(results[:top_n], 1):
        param_str = ", ".join(f"{k}={r[k]}" for k in keys)
        print(f"  #{rank:<2}  PnL={r['pnl']:>10,.0f}   {param_str}")
    print(f"{'─'*50}\n")
 
    return results