#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


LIMIT_EXCEEDED_PATTERNS = [
    re.compile(r"Orders for product TOMATOES exceeded limit", re.IGNORECASE),
    re.compile(r"position limit", re.IGNORECASE),
]

GRID_METRIC_PATTERN = re.compile(
    r"GRID_METRIC\|(?:timestamp=(?P<timestamp>-?\d+)\|)?pnl=(?P<pnl>-?\d+(?:\.\d+)?)"
)


@dataclass
class RunResult:
    tomatoes_limit: int
    spike_threshold: int
    final_pnl: float | None
    max_drawdown: float | None
    valid: bool
    note: str = ""


@dataclass
class ActivitySeries:
    source: str
    series: pd.Series


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grid search TOMATOES position limit and spike acceptance threshold for prosperity4bt."
    )
    parser.add_argument("--trader", default="utkarsh_trader.py", help="Path to the trader file.")
    parser.add_argument("--round", default="0", help="Round argument passed to prosperity4bt.")
    parser.add_argument("--limit-min", type=int, default=10)
    parser.add_argument("--limit-max", type=int, default=80)
    parser.add_argument("--limit-step", type=int, default=1)
    parser.add_argument("--threshold-min", type=int, default=0)
    parser.add_argument("--threshold-max", type=int, default=30)
    parser.add_argument("--threshold-step", type=int, default=1)
    parser.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 4) // 2)))
    parser.add_argument("--outdir", default="gridsearch_tomatoes_results")
    parser.add_argument(
        "--keep-temp-files",
        action="store_true",
        help="Keep per-run temp directories for debugging failed runs.",
    )
    return parser.parse_args()


def patch_trader_source(source: str, tomatoes_limit: int, spike_threshold: int) -> str:
    patched = source

    limit_pattern = re.compile(r'(POSITION_LIMIT\s*=\s*\{.*?"TOMATOES"\s*:\s*)(\d+)', re.DOTALL)
    patched, n_limit = limit_pattern.subn(rf'\g<1>{tomatoes_limit}', patched, count=1)
    if n_limit != 1:
        raise ValueError("Could not patch TOMATOES position limit.")

    if 'if position > -5:' in patched:
        patched = patched.replace('if position > -5:', f'if position > -{spike_threshold}:', 1)
    else:
        patched, n_bid = re.subn(r'if\s+position\s*>\s*-\d+\s*:', f'if position > -{spike_threshold}:', patched, count=1)
        if n_bid != 1:
            raise ValueError("Could not patch negative spike threshold.")

    if 'if position < 5:' in patched:
        patched = patched.replace('if position < 5:', f'if position < {spike_threshold}:', 1)
    else:
        patched, n_ask = re.subn(r'if\s+position\s*<\s*\d+\s*:', f'if position < {spike_threshold}:', patched, count=1)
        if n_ask != 1:
            raise ValueError("Could not patch positive spike threshold.")

    helper = r'''

def __grid_metric_update_and_print(self, state):
    if not hasattr(self, "_grid_cash"):
        self._grid_cash = 0.0
        self._grid_seen_trade_keys = set()

    own_trades = getattr(state, "own_trades", {}) or {}
    for product, trades in own_trades.items():
        for trade in trades:
            symbol = getattr(trade, "symbol", None) or getattr(trade, "product", None) or product
            key = (
                getattr(trade, "timestamp", None),
                symbol,
                getattr(trade, "price", None),
                getattr(trade, "quantity", None),
                getattr(trade, "buyer", None),
                getattr(trade, "seller", None),
            )
            if key in self._grid_seen_trade_keys:
                continue
            self._grid_seen_trade_keys.add(key)

            try:
                price = float(getattr(trade, "price", 0.0))
                quantity = int(getattr(trade, "quantity", 0))
            except Exception:
                continue

            buyer = getattr(trade, "buyer", None)
            seller = getattr(trade, "seller", None)
            if buyer == "SUBMISSION":
                self._grid_cash -= price * quantity
            elif seller == "SUBMISSION":
                self._grid_cash += price * quantity
            else:
                self._grid_cash -= price * quantity

    pnl = float(self._grid_cash)
    positions = getattr(state, "position", {}) or {}
    order_depths = getattr(state, "order_depths", {}) or {}

    for product, pos in positions.items():
        order_depth = order_depths.get(product)
        if order_depth is None:
            continue

        buy_orders = getattr(order_depth, "buy_orders", {}) or {}
        sell_orders = getattr(order_depth, "sell_orders", {}) or {}

        if buy_orders and sell_orders:
            best_bid = max(buy_orders.keys())
            best_ask = min(sell_orders.keys())
            mid = (best_bid + best_ask) / 2.0
        elif buy_orders:
            mid = float(max(buy_orders.keys()))
        elif sell_orders:
            mid = float(min(sell_orders.keys()))
        else:
            mid = 0.0

        pnl += float(pos) * mid

    print(f"GRID_METRIC|timestamp={getattr(state, 'timestamp', 0)}|pnl={pnl}")
'''

    if "def __grid_metric_update_and_print(self, state):" not in patched:
        patched += helper

    patched, n_return = re.subn(
        r'(?m)^(\s*)return\s+result\s*,\s*conversions\s*,\s*traderData\s*$',
        r'\1__grid_metric_update_and_print(self, state)\n\1return result, conversions, traderData',
        patched,
        count=1,
    )
    if n_return != 1:
        raise ValueError("Could not inject GRID_METRIC call before return.")

    return patched


def extract_text_candidates(run_dir: Path, stdout: str, stderr: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if stdout.strip():
        candidates.append(("stdout", stdout))
    if stderr.strip():
        candidates.append(("stderr", stderr))

    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".log", ".txt", ".csv", ".json", ".out"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if text.strip():
            candidates.append((str(path.relative_to(run_dir)), text))
    return candidates


def contains_limit_error(texts: Iterable[tuple[str, str]]) -> Optional[str]:
    for source, text in texts:
        for pattern in LIMIT_EXCEEDED_PATTERNS:
            if pattern.search(text):
                return f"limit exceeded detected in {source}"
        if "Traceback" in text:
            return f"traceback found in {source}"
    return None


def parse_grid_metric_series(texts: Iterable[tuple[str, str]]) -> Optional[ActivitySeries]:
    for source, text in texts:
        values: list[float] = []
        for line in text.splitlines():
            match = GRID_METRIC_PATTERN.search(line)
            if match:
                values.append(float(match.group("pnl")))
        if values:
            series = pd.Series(values, index=pd.RangeIndex(start=0, stop=len(values), step=1), dtype=float)
            return ActivitySeries(source=source, series=series)
    return None


def compute_max_drawdown(series: pd.Series) -> float:
    running_max = series.cummax()
    drawdowns = running_max - series
    return float(drawdowns.max())


def maybe_copy_debug_run(run_dir: Path) -> None:
    debug_dir = Path.cwd() / "gridsearch_debug_runs"
    debug_dir.mkdir(exist_ok=True)
    target = debug_dir / run_dir.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(run_dir, target)


def run_single_combination(
    trader_path: str,
    round_arg: str,
    tomatoes_limit: int,
    spike_threshold: int,
    keep_temp_files: bool,
) -> RunResult:
    trader_source = Path(trader_path).read_text(encoding="utf-8")
    patched_source = patch_trader_source(trader_source, tomatoes_limit, spike_threshold)

    tmpdir_obj = tempfile.TemporaryDirectory(prefix=f"grid_bt_{tomatoes_limit}_{spike_threshold}_")
    run_dir = Path(tmpdir_obj.name)
    temp_trader = run_dir / Path(trader_path).name
    temp_trader.write_text(patched_source, encoding="utf-8")
    # copy local dependency files the trader imports
    for dep in ["datamodel.py"]:
        dep_path = Path(trader_path).resolve().parent / dep
        if dep_path.exists():
            shutil.copy2(dep_path, run_dir / dep)
    cmd = ["prosperity4bt", str(temp_trader), str(round_arg), "--print"]
    try:
        completed = subprocess.run(
            cmd,
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        return RunResult(tomatoes_limit, spike_threshold, None, None, False, "prosperity4bt command not found")
    except subprocess.TimeoutExpired:
        return RunResult(tomatoes_limit, spike_threshold, None, None, False, "backtest timed out")

    texts = extract_text_candidates(run_dir, completed.stdout, completed.stderr)

    if completed.returncode != 0:
        note = f"backtester exited with code {completed.returncode}"
        if texts:
            nonempty = next((t for _, t in texts if t.strip()), "")
            if nonempty:
                note += f" | {nonempty.splitlines()[-1][:220]}"
        if keep_temp_files:
            maybe_copy_debug_run(run_dir)
        tmpdir_obj.cleanup()
        return RunResult(tomatoes_limit, spike_threshold, None, None, False, note)

    limit_error = contains_limit_error(texts)
    if limit_error is not None:
        if keep_temp_files:
            maybe_copy_debug_run(run_dir)
        tmpdir_obj.cleanup()
        return RunResult(tomatoes_limit, spike_threshold, None, None, False, limit_error)

    activity = parse_grid_metric_series(texts)
    if activity is None:
        preview = next((text for _, text in texts if text.strip()), "")
        note = "could not parse GRID_METRIC lines"
        if preview:
            note += f" | preview: {preview.splitlines()[-1][:220]}"
        if keep_temp_files:
            maybe_copy_debug_run(run_dir)
        tmpdir_obj.cleanup()
        return RunResult(tomatoes_limit, spike_threshold, None, None, False, note)

    final_pnl = float(activity.series.iloc[-1])
    max_drawdown = compute_max_drawdown(activity.series)

    if keep_temp_files:
        maybe_copy_debug_run(run_dir)
    tmpdir_obj.cleanup()
    return RunResult(tomatoes_limit, spike_threshold, final_pnl, max_drawdown, True, activity.source)


def build_heatmap(df: pd.DataFrame, value_col: str, title: str, outpath: Path) -> None:
    pivot = df.pivot(index="spike_threshold", columns="tomatoes_limit", values=value_col).sort_index().sort_index(axis=1)

    plt.figure(figsize=(max(8, 0.25 * len(pivot.columns) + 4), max(6, 0.25 * len(pivot.index) + 3)))
    masked = np.ma.masked_invalid(pivot.to_numpy(dtype=float))
    im = plt.imshow(masked, aspect="auto", origin="lower")
    cbar = plt.colorbar(im)
    cbar.set_label(value_col)
    plt.xticks(range(len(pivot.columns)), pivot.columns)
    plt.yticks(range(len(pivot.index)), pivot.index)
    plt.xlabel("TOMATOES position limit")
    plt.ylabel("Spike acceptance threshold")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()


def main() -> int:
    args = parse_args()

    trader_path = Path(args.trader)
    if not trader_path.exists():
        print(f"Trader file not found: {trader_path}", file=sys.stderr)
        return 1

    limits = list(range(args.limit_min, args.limit_max + 1, args.limit_step))
    thresholds = list(range(args.threshold_min, args.threshold_max + 1, args.threshold_step))
    combos = [(limit, threshold) for limit in limits for threshold in thresholds]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(combos)} backtests...")

    results: list[RunResult] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                run_single_combination,
                str(trader_path),
                args.round,
                limit,
                threshold,
                args.keep_temp_files,
            ): (limit, threshold)
            for limit, threshold in combos
        }

        for i, future in enumerate(cf.as_completed(futures), start=1):
            limit, threshold = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = RunResult(limit, threshold, None, None, False, f"unexpected error: {exc}")
            results.append(result)
            if i % 25 == 0 or i == len(combos):
                print(f"Completed {i}/{len(combos)}")

    df = pd.DataFrame(asdict(r) for r in results)
    df = df.sort_values(["spike_threshold", "tomatoes_limit"]).reset_index(drop=True)
    df.to_csv(outdir / "grid_search_results.csv", index=False)

    valid_df = df[df["valid"]].copy()
    if valid_df.empty:
        print("No valid runs parsed. Check grid_search_results.csv for failure notes.", file=sys.stderr)
        return 2

    build_heatmap(valid_df, "final_pnl", "TOMATOES grid search: final PnL", outdir / "pnl_heatmap.png")
    build_heatmap(valid_df, "max_drawdown", "TOMATOES grid search: max drawdown", outdir / "max_drawdown_heatmap.png")

    best_pnl_row = valid_df.sort_values("final_pnl", ascending=False).iloc[0]
    print("Best final PnL:")
    print(best_pnl_row[["tomatoes_limit", "spike_threshold", "final_pnl", "max_drawdown", "note"]].to_string())

    best_dd_row = valid_df.sort_values("max_drawdown", ascending=True).iloc[0]
    print("\nLowest max drawdown:")
    print(best_dd_row[["tomatoes_limit", "spike_threshold", "final_pnl", "max_drawdown", "note"]].to_string())

    print(f"\nSaved results to: {outdir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
