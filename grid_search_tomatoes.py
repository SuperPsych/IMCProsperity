#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
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

SUMMARY_PNL_PATTERNS = [
    re.compile(r"(?:final\s+)?p(?:rofit)?\s*&?\s*l(?:oss)?\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\bPnL\b\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE),
]


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
        help="Keep per-run temp directories for debugging failed parses.",
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
            raise ValueError("Could not patch bid spike threshold.")

    if 'if position < 5:' in patched:
        patched = patched.replace('if position < 5:', f'if position < {spike_threshold}:', 1)
    else:
        patched, n_ask = re.subn(r'if\s+position\s*<\s*\d+\s*:', f'if position < {spike_threshold}:', patched, count=1)
        if n_ask != 1:
            raise ValueError("Could not patch ask spike threshold.")

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


def parse_semicolon_activity(source: str, text: str) -> Optional[ActivitySeries]:
    rows: list[tuple[int, str, float]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ";" not in line:
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 4:
            continue
        try:
            timestamp = int(float(parts[1]))
            pnl = float(parts[-1])
        except ValueError:
            continue
        product = parts[2]
        if not product:
            continue
        rows.append((timestamp, product, pnl))

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["timestamp", "product", "pnl"])
    df = df.groupby(["timestamp", "product"], as_index=False)["pnl"].last()
    total = df.groupby("timestamp")["pnl"].sum().sort_index()
    if total.empty:
        return None
    return ActivitySeries(source=source, series=total)


def parse_json_activity(source: str, text: str) -> Optional[ActivitySeries]:
    rows: list[tuple[int, str, float]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if "timestamp" not in obj or "product" not in obj:
            continue
        pnl = obj.get("profit_and_loss", obj.get("pnl"))
        if pnl is None:
            continue
        try:
            timestamp = int(obj["timestamp"])
            product = str(obj["product"])
            pnl = float(pnl)
        except (ValueError, TypeError):
            continue
        rows.append((timestamp, product, pnl))

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["timestamp", "product", "pnl"])
    df = df.groupby(["timestamp", "product"], as_index=False)["pnl"].last()
    total = df.groupby("timestamp")["pnl"].sum().sort_index()
    if total.empty:
        return None
    return ActivitySeries(source=source, series=total)


def choose_best_activity(texts: Iterable[tuple[str, str]]) -> Optional[ActivitySeries]:
    candidates: list[ActivitySeries] = []
    for source, text in texts:
        for parser in (parse_semicolon_activity, parse_json_activity):
            parsed = parser(source, text)
            if parsed is not None:
                candidates.append(parsed)

    if not candidates:
        return None
    candidates.sort(key=lambda item: (len(item.series), item.series.index.nunique()), reverse=True)
    return candidates[0]


def summary_pnl_fallback(texts: Iterable[tuple[str, str]]) -> Optional[float]:
    for _, text in texts:
        for pattern in SUMMARY_PNL_PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
    return None


def compute_max_drawdown(series: pd.Series) -> float:
    running_max = series.cummax()
    drawdowns = running_max - series
    return float(drawdowns.max())


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

    cmd = ["prosperity4bt", temp_trader.name, str(round_arg)]
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
            stderr_preview = next((t for s, t in texts if s == "stderr" and t.strip()), "")
            if stderr_preview:
                note += f" | {stderr_preview.splitlines()[-1][:200]}"
        return RunResult(tomatoes_limit, spike_threshold, None, None, False, note)

    limit_error = contains_limit_error(texts)
    if limit_error is not None:
        result = RunResult(tomatoes_limit, spike_threshold, None, None, False, limit_error)
    else:
        activity = choose_best_activity(texts)
        if activity is not None:
            final_pnl = float(activity.series.iloc[-1])
            max_drawdown = compute_max_drawdown(activity.series)
            result = RunResult(tomatoes_limit, spike_threshold, final_pnl, max_drawdown, True, activity.source)
        else:
            fallback_pnl = summary_pnl_fallback(texts)
            if fallback_pnl is not None:
                result = RunResult(tomatoes_limit, spike_threshold, fallback_pnl, math.nan, True, "summary regex fallback")
            else:
                result = RunResult(tomatoes_limit, spike_threshold, None, None, False, "could not parse activity log or summary pnl")

    if keep_temp_files:
        debug_dir = Path.cwd() / "gridsearch_debug_runs"
        debug_dir.mkdir(exist_ok=True)
        target = debug_dir / run_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(run_dir, target)

    tmpdir_obj.cleanup()
    return result


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

    build_heatmap(
        valid_df,
        "final_pnl",
        "TOMATOES grid search: final PnL",
        outdir / "pnl_heatmap.png",
    )

    if valid_df["max_drawdown"].notna().any():
        build_heatmap(
            valid_df,
            "max_drawdown",
            "TOMATOES grid search: max drawdown",
            outdir / "max_drawdown_heatmap.png",
        )
    else:
        print("Warning: max drawdown could not be computed from parsed logs for any valid run.")

    best_pnl_row = valid_df.sort_values("final_pnl", ascending=False).iloc[0]
    print("Best final PnL:")
    print(best_pnl_row[["tomatoes_limit", "spike_threshold", "final_pnl", "max_drawdown", "note"]].to_string())

    if valid_df["max_drawdown"].notna().any():
        best_dd_row = valid_df.sort_values("max_drawdown", ascending=True).iloc[0]
        print("\nLowest max drawdown:")
        print(best_dd_row[["tomatoes_limit", "spike_threshold", "final_pnl", "max_drawdown", "note"]].to_string())

    print(f"\nSaved results to: {outdir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
