"""
Monte Carlo for AETHER_CRYSTAL price under GBM with zero risk-neutral drift.

    sigma  = 2.51 (annualized)
    grid   = 4 steps per trading day
    year   = 252 trading days

Reports mean and stdev of S_T after 2 weeks (10 days) and 3 weeks (15 days).
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


SIGMA = 2.51
STEPS_PER_DAY = 4
DAYS_PER_YEAR = 252
S0 = 100.0
N_PATHS = 1_000_000
SEED = 42
PLOT_PATH = Path(__file__).parent / "aether_crystal_mc.png"


def simulate(s0: float, days: int, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    n_steps = days * STEPS_PER_DAY
    dt = 1.0 / DAYS_PER_YEAR / STEPS_PER_DAY
    drift = -0.5 * SIGMA**2 * dt
    diffusion = SIGMA * np.sqrt(dt)
    z = rng.standard_normal((n_paths, n_steps))
    log_returns = drift + diffusion * z
    log_st = np.log(s0) + log_returns.sum(axis=1)
    return np.exp(log_st)


def analytic_moments(s0: float, days: int) -> tuple[float, float]:
    t = days / DAYS_PER_YEAR
    mean = s0
    var = s0**2 * (np.exp(SIGMA**2 * t) - 1.0)
    return mean, np.sqrt(var)


def plot_terminal_distributions(samples: dict[str, np.ndarray], path: Path) -> None:
    fig, axes = plt.subplots(len(samples), 2, figsize=(12, 4 * len(samples)))
    if len(samples) == 1:
        axes = axes[np.newaxis, :]

    for row, (label, st) in enumerate(samples.items()):
        mean, median, std = st.mean(), float(np.median(st)), st.std(ddof=1)

        # linear-scale histogram, clipped to 99th percentile so the bulk is visible
        clip = float(np.quantile(st, 0.99))
        ax = axes[row, 0]
        ax.hist(np.clip(st, None, clip), bins=200, color="steelblue", alpha=0.85)
        ax.axvline(mean, color="red", linestyle="--", label=f"mean = {mean:.2f}")
        ax.axvline(median, color="orange", linestyle="--", label=f"median = {median:.2f}")
        ax.set_title(f"{label} — linear (clipped at 99th pct = {clip:.1f})")
        ax.set_xlabel("S_T")
        ax.set_ylabel("count")
        ax.legend()

        # log-scale histogram on log10(S_T) — natural view for GBM
        ax = axes[row, 1]
        ax.hist(np.log10(st), bins=200, color="seagreen", alpha=0.85)
        ax.axvline(np.log10(mean), color="red", linestyle="--", label=f"log10(mean) = {np.log10(mean):.2f}")
        ax.axvline(np.log10(median), color="orange", linestyle="--", label=f"log10(median) = {np.log10(median):.2f}")
        ax.set_title(f"{label} — log10(S_T)   stdev = {std:.2f}")
        ax.set_xlabel("log10(S_T)")
        ax.set_ylabel("count")
        ax.legend()

    fig.suptitle(f"AETHER_CRYSTAL terminal price distribution  (S0={S0}, σ={SIGMA}, paths={N_PATHS:,})")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    print(f"\nplot saved to {path}")


def main() -> None:
    rng = np.random.default_rng(SEED)
    horizons = {"2 weeks (10 trading days)": 10, "3 weeks (15 trading days)": 15}

    print(f"S0={S0}  sigma={SIGMA}  paths={N_PATHS:,}  steps/day={STEPS_PER_DAY}\n")
    header = f"{'horizon':<28} {'mc mean':>12} {'mc stdev':>12} {'mc median':>12} {'analytic mean':>16} {'analytic stdev':>16}"
    print(header)
    print("-" * len(header))

    samples: dict[str, np.ndarray] = {}
    for label, days in horizons.items():
        st = simulate(S0, days, N_PATHS, rng)
        a_mean, a_std = analytic_moments(S0, days)
        print(
            f"{label:<28} {st.mean():>12.4f} {st.std(ddof=1):>12.4f} "
            f"{np.median(st):>12.4f} {a_mean:>16.4f} {a_std:>16.4f}"
        )
        samples[label] = st

    plot_terminal_distributions(samples, PLOT_PATH)


if __name__ == "__main__":
    main()
