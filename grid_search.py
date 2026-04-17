"""
grid_search.py
==============
Grid-search hyperparameters for a prosperity4btest trader.
Dependencies: seaborn, matplotlib, pandas.

Usage from a notebook
---------------------
from grid_search import grid_search

results = grid_search(
    trader_file="trader.py",
    days="1",          # Can be an int, string ("1-2"), or list (["1-1", "1-2"])
    param_grid={
        "POSITION_LIMIT": [30, 40, 50],
        "SPIKE_THRESHOLD": [3, 5, 7],
    },
    top_n=5,
    final_pnl=1.0,           # kwargs for your cost/score function
    sharpe_ratio=100.0,
    max_drawdown_pct=-100.0  # Penalize drawdowns
)
"""

import re
import ast
import subprocess
import itertools
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

_METRIC_RE = re.compile(r"^\s+([a-z_]+):\s*([\d\.,\-inf]+)", re.MULTILINE)

def _normalise_days(days: str | int | list) -> list[str]:
    """Accept int, str, or list and return a list of day strings for the CLI."""
    if isinstance(days, list):
        return [str(d) for d in days]
    return [str(days)]

def _run_backtest(trader_path: Path, days: str | int | list) -> dict[str, float]:
    """Runs prosperity4btest and parses the Risk metrics block."""
    proc = subprocess.run(
        ["prosperity4bt", str(trader_path), "--no-progress", "--no-out",
         *_normalise_days(days)],
        capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr

    metrics_idx = output.find("Risk metrics (full trading period):")
    if metrics_idx == -1:
        raise RuntimeError(
            f"Could not find 'Risk metrics' block in backtester output.\n"
            f"Output:\n{output}"
        )
    
    metrics_block = output[metrics_idx:]
    metrics: dict[str, float] = {}
    
    for m in _METRIC_RE.finditer(metrics_block):
        key = m.group(1)
        val_str = m.group(2).replace(",", "")
        metrics[key] = float(val_str)
        
    if not metrics:
        raise RuntimeError(f"Could not parse any metrics from block:\n{metrics_block}")
        
    return metrics


# ── 3. Visualization ──────────────────────────────────────────────────────────

def _plot_heatmap(
    results: list[dict],
    x_key: str,
    y_key: str,
    z_key: str | None,
) -> None:
    df = pd.DataFrame(results)

    z_vals = [None] if z_key is None else sorted(df[z_key].unique())
    ncols = len(z_vals)
    cell_w = max(6, len(df[x_key].unique()) * 1.2)
    cell_h = max(4, len(df[y_key].unique()) * 0.9)
    
    fig, axes = plt.subplots(1, ncols, figsize=(cell_w * ncols, cell_h), squeeze=False)
    vmin, vmax = df["score"].min(), df["score"].max()

    for col, z_val in enumerate(z_vals):
        ax = axes[0][col]
        subset = df if z_val is None else df[df[z_key] == z_val]
        pivot = subset.pivot(index=y_key, columns=x_key, values="score")
        sns.heatmap(
            pivot, ax=ax, annot=True, fmt=".2f", cmap="RdYlGn",
            vmin=vmin, vmax=vmax, linewidths=0.4, linecolor="white",
            cbar=(col == ncols - 1), cbar_kws={"label": "Weighted Score"}
        )
        title = "Score Landscape" if z_val is None else f"{z_key}={z_val}"
        ax.set_title(title, fontsize=11)
        ax.set_xlabel(x_key)
        ax.set_ylabel(y_key if col == 0 else "")

    fig.suptitle("Hyperparameter Score Grid Search", fontsize=13, y=1.02)
    plt.tight_layout()
    plt.show()


def _plot_bar(results: list[dict], key: str) -> None:
    df = pd.DataFrame(results).sort_values(key)
    fig, ax = plt.subplots(figsize=(max(6, len(df) * 0.8), 4))
    colors = ["#2ecc71" if v == df["score"].max() else "#3498db" for v in df["score"]]
    
    ax.bar(df[key].astype(str), df["score"], color=colors, edgecolor="white")
    ax.set_xlabel(key)
    ax.set_ylabel("Weighted Score")
    ax.set_title(f"Score vs {key}")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.2f}"))
    
    plt.tight_layout()
    plt.show()


# ── 4. Grid search ────────────────────────────────────────────────────────────

def grid_search(
    trader_file: str,
    days: str | int | list,
    param_grid: dict[str, list[Any]],
    top_n: int = 5,
    **metric_weights: float
) -> list[dict]:
    """
    Grid search utilizing weighted risk metrics.
    
    Parameters
    ----------
    trader_file    : Path to the trader .py file.
    days           : Days to backtest (e.g. 1, "1-2", ["1-1", "1-2"]).
    param_grid     : Dict of param_name -> list of values to search.
    top_n          : How many top results to print.
    metric_weights : Keyword args mapping metric names to their coefficient weight.
                     (e.g., final_pnl=1.0, sharpe_ratio=50.0). Defaults to 0 if omitted.
    """
    if not metric_weights:
        raise ValueError(
            "You must provide at least one metric coefficient via keyword arguments "
            "(e.g., final_pnl=1.0, sharpe_ratio=10.0)."
        )

    trader_path = Path(trader_file).resolve()
    original_source = trader_path.read_text()

    day_specs = _normalise_days(days)

    baseline_match = _PARAMS_RE.search(original_source)
    if not baseline_match:
        raise ValueError("Could not find PARAMS = {...} in trader source.")
    
    baseline_params = ast.literal_eval(baseline_match.group(2))
    print("Baseline PARAMS (non-searched keys held fixed):")
    for k, v in baseline_params.items():
        marker = "  [SEARCHING]" if k in param_grid else ""
        print(f"  {k}: {v}{marker}")
    
    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    print(f"\nGrid search: {len(combos)} combos | days={' '.join(day_specs)}")
    print(f"Objective Function Weights: {metric_weights}\n")

    results = []

    import tempfile, shutil
    tmp_dir = Path(tempfile.mkdtemp(dir=trader_path.parent))
    tmp_path = tmp_dir / trader_path.name
    
    try:
        # Symlink environment
        for item in trader_path.parent.iterdir():
            if item != tmp_dir and item.name != trader_path.name:
                (tmp_dir / item.name).symlink_to(item.resolve())

        for i, combo in enumerate(combos, 1):
            overrides = dict(zip(keys, combo))
            tmp_path.write_text(_inject_params(original_source, overrides))

            try:
                metrics = _run_backtest(tmp_path, day_specs)
                # Calculate weighted score (default to 0 for missing metrics)
                score = sum(metrics.get(m, 0.0) * w for m, w in metric_weights.items())
            except Exception as e:
                print(f"  [{i}/{len(combos)}] {overrides}  →  ERROR: {e}")
                score = float("-inf")
                metrics = {}

            results.append({**overrides, "score": score, "metrics": metrics})
            print(f"  [{i}/{len(combos)}] {overrides}  →  Score = {score:,.2f}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Sort descending by score (assuming you want to maximize the combined metrics)
    results.sort(key=lambda r: r["score"], reverse=True)

    # Visualization
    varied = [k for k in keys if len(param_grid[k]) > 1]
    if len(varied) >= 2:
        x_key, y_key = varied[0], varied[1]
        z_key = varied[2] if len(varied) >= 3 else None
        _plot_heatmap(results, x_key, y_key, z_key)
    elif len(varied) == 1:
        _plot_bar(results, varied[0])

    # Top-N Output
    print(f"{'─'*60}\nTop {top_n} Configurations:\n{'─'*60}")
    for rank, r in enumerate(results[:top_n], 1):
        param_str = ", ".join(f"{k}={r[k]}" for k in keys)
        print(f"  #{rank:<2}  Score: {r['score']:>12,.2f}  |  {param_str}")
        
        # Optionally print the underlying metrics that made up the score
        if r['metrics']:
            metric_str = ", ".join(f"{m}={r['metrics'].get(m, 0):.2f}" for m in metric_weights)
            print(f"       ({metric_str})")
            
    print(f"{'─'*60}\n")

    return results