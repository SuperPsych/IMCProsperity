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
    days="0",          # full round 0  (or "0-1" for a single day, or ["0-1", "0-2"] for multiple)
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

def _normalise_days(days: str | int | list) -> list[str]:
    """Accept int, str, or list and return a list of day strings for the CLI."""
    if isinstance(days, list):
        return [str(d) for d in days]
    return [str(days)]

def _run_backtest(trader_path: Path, days: str | int | list) -> dict[str, int]:
    proc = subprocess.run(
        ["prosperity4bt", str(trader_path), "--no-progress", "--no-out",
         *_normalise_days(days)],
        capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr

    # Truncate at "Profit summary:" so we only see per-product per-day lines,
    # not the summary totals (which would double-count)
    cutoff = output.find("Profit summary:")
    if cutoff == -1:
        raise RuntimeError(
            f"Could not find \'Profit summary:\' in backtester output.\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    per_day_output = output[:cutoff]

    pnl: dict[str, int] = {}
    for m in _PNL_RE.finditer(per_day_output):
        product, value = m.group(1), m.group(2)
        pnl[product] = pnl.get(product, 0) + int(value.replace(",", ""))
    if not pnl:
        raise RuntimeError(
            f"Could not parse any per-day PnL lines.\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return pnl


# ── 3. Seaborn heatmap ────────────────────────────────────────────────────────

def _plot_heatmap(
    results: list[dict],
    x_key: str,
    y_key: str,
    z_key: str | None,
    product: str,
) -> None:
    df = pd.DataFrame(results)

    if z_key is None:
        z_vals = [None]
    else:
        z_vals = sorted(df[z_key].unique())

    ncols = len(z_vals)
    cell_w = max(6, len(df[x_key].unique()) * 1.2)
    cell_h = max(4, len(df[y_key].unique()) * 0.9)
    fig, axes = plt.subplots(1, ncols, figsize=(cell_w * ncols, cell_h),
                             squeeze=False)

    vmin, vmax = df["pnl"].min(), df["pnl"].max()

    for col, z_val in enumerate(z_vals):
        ax = axes[0][col]
        subset = df if z_val is None else df[df[z_key] == z_val]
        pivot = subset.pivot(index=y_key, columns=x_key, values="pnl")
        sns.heatmap(
            pivot,
            ax=ax,
            annot=True,
            fmt=".0f",
            cmap="RdYlGn",
            vmin=vmin,
            vmax=vmax,
            linewidths=0.4,
            linecolor="white",
            cbar=(col == ncols - 1),  # only one colorbar on the right
            cbar_kws={"label": f"{product} PnL"},
        )
        title = f"{product} PnL" if z_val is None else f"{z_key}={z_val}"
        ax.set_title(title, fontsize=11)
        ax.set_xlabel(x_key)
        ax.set_ylabel(y_key if col == 0 else "")

    fig.suptitle(f"{product} PnL grid search", fontsize=13, y=1.02)
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
    days: str | int | list,
    product: str,
    param_grid: dict[str, list[Any]],
    top_n: int = 5,
) -> list[dict]:
    """
    Parameters
    ----------
    trader_file : path to the trader .py file
    days        : day(s) to backtest — int/str for a single spec (e.g. 0 or "0-1"),
                  or a list for multiple (e.g. ["0-1", "0-2"]).
                  Formats mirror the prosperity4bt CLI: <round> or <round>-<day>.
    product     : product name to extract PnL for
    param_grid  : dict of param_name → list of values to search
    top_n       : how many top results to print
    """
    trader_path = Path(trader_file).resolve()
    original_source = trader_path.read_text()   # read once, never write back

    day_specs = _normalise_days(days)

    # Snapshot the baseline PARAMS from the file right now.
    # We print it so you can verify the non-searched params are what you expect.
    baseline_match = _PARAMS_RE.search(original_source)
    if not baseline_match:
        raise ValueError("Could not find PARAMS = {...} in trader source.")
    baseline_params = ast.literal_eval(baseline_match.group(2))
    print(f"Baseline PARAMS (non-searched keys held fixed):")
    for k, v in baseline_params.items():
        marker = "  [SEARCHING]" if k in param_grid else ""
        print(f"  {k}: {v}{marker}")
    print()

    keys   = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    print(f"Grid search: {len(combos)} combos | product={product} | days={' '.join(day_specs)}\n")

    results = []

    # Create a temp dir named trader.py inside it (same filename = same module
    # name). Symlink everything else in the parent dir into the temp dir so
    # local imports like datamodel resolve identically to a normal run.
    import tempfile, shutil
    tmp_dir = Path(tempfile.mkdtemp(dir=trader_path.parent))
    tmp_path = tmp_dir / trader_path.name
    try:
        for item in trader_path.parent.iterdir():
            if item != tmp_dir and item.name != trader_path.name:
                (tmp_dir / item.name).symlink_to(item.resolve())

        for i, combo in enumerate(combos, 1):
            overrides = dict(zip(keys, combo))
            tmp_path.write_text(_inject_params(original_source, overrides))

            try:
                pnl = _run_backtest(tmp_path, day_specs).get(product, 0)
            except Exception as e:
                print(f"  [{i}/{len(combos)}] {overrides}  →  ERROR: {e}")
                pnl = float("nan")

            results.append({**overrides, "pnl": pnl})
            print(f"  [{i}/{len(combos)}] {overrides}  →  {product} PnL = {pnl:,}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    results.sort(key=lambda r: r["pnl"] if r["pnl"] == r["pnl"] else float("-inf"), reverse=True)

    # Plot
    varied = [k for k in keys if len(param_grid[k]) > 1]
    if len(varied) >= 2:
        x_key, y_key = varied[0], varied[1]
        z_key = varied[2] if len(varied) >= 3 else None
        _plot_heatmap(results, x_key, y_key, z_key, product)
    elif len(varied) == 1:
        _plot_bar(results, varied[0], product)

    # Top-N
    print(f"{'─'*50}\nTop {top_n} for {product}:\n{'─'*50}")
    for rank, r in enumerate(results[:top_n], 1):
        param_str = ", ".join(f"{k}={r[k]}" for k in keys)
        print(f"  #{rank:<2}  PnL={r['pnl']:>10,.0f}   {param_str}")
    print(f"{'─'*50}\n")

    return results