"""
Monte Carlo pricing for AETHER_CRYSTAL options under zero-drift GBM.

    sigma = 2.51 (annualized)
    grid  = 4 steps per trading day
    week  = 5 trading days
    year  = 252 trading days
    r     = 0   (so price = E[payoff], no discounting)

A "Solvenarian Day" is a calendar day. With 5 trading days per week:
    21 Solvenarian Days = 3 weeks = 15 trading days
    14 Solvenarian Days = 2 weeks = 10 trading days

Options (T listed in trading days):
    AC_50_P    vanilla put,   K=50, T=15
    AC_50_C    vanilla call,  K=50, T=15
    AC_35_P    vanilla put,   K=35, T=15
    AC_40_P    vanilla put,   K=40, T=15
    AC_60_C    vanilla call,  K=60, T=15
    AC_50_P_2  vanilla put,   K=50, T=10
    AC_50_C_2  vanilla call,  K=50, T=10
    AC_50_CO   chooser, K=50: at day 10, auto-converts to whichever side
               is in-the-money; expires at day 15 as that side.
    AC_40_BP   binary put,    K=40, T=15, pays 10 if S_T<40 else 0
    AC_45_KO   knock-out put, K=45, barrier=35, T=15:
               pays max(45-S_T,0) if path never goes below 35, else 0.
"""

from math import erf, sqrt as msqrt
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


SIGMA = 2.51
STEPS_PER_DAY = 4
DAYS_PER_YEAR = 252
S0 = 50.0
N_PATHS = 1_000_000
SEED = 42
PLOT_PATH = Path(__file__).parent / "aether_options_mc.png"
PAYOFF_PLOT_PATH = Path(__file__).parent / "aether_options_payoffs.png"
PAYOFF_DIST_NAMES = ("AC_50_P", "AC_50_C", "AC_50_P_2", "AC_50_C_2", "AC_50_CO")


def simulate_paths(s0: float, days: int, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    """Return shape (n_paths, days*STEPS_PER_DAY); column k is S after step k+1."""
    n_steps = days * STEPS_PER_DAY
    dt = 1.0 / DAYS_PER_YEAR / STEPS_PER_DAY
    drift = -0.5 * SIGMA**2 * dt
    diffusion = SIGMA * np.sqrt(dt)
    z = rng.standard_normal((n_paths, n_steps))
    log_inc = drift + diffusion * z
    log_path = np.log(s0) + np.cumsum(log_inc, axis=1)
    return np.exp(log_path)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / msqrt(2.0)))


def bs_call(s0: float, k: float, t: float, sigma: float) -> float:
    if t <= 0:
        return max(s0 - k, 0.0)
    d1 = (np.log(s0 / k) + 0.5 * sigma**2 * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    return s0 * norm_cdf(d1) - k * norm_cdf(d2)


def bs_put(s0: float, k: float, t: float, sigma: float) -> float:
    if t <= 0:
        return max(k - s0, 0.0)
    d1 = (np.log(s0 / k) + 0.5 * sigma**2 * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    return k * norm_cdf(-d2) - s0 * norm_cdf(-d1)


def main() -> None:
    rng = np.random.default_rng(SEED)

    # 21 Solvenarian Days = 3 weeks = 15 trading days
    # 14 Solvenarian Days = 2 weeks = 10 trading days
    days_long, days_short = 15, 10
    paths = simulate_paths(S0, days_long, N_PATHS, rng)  # (N, 60)
    S_T = paths[:, -1]
    S_choice = paths[:, days_short * STEPS_PER_DAY - 1]
    path_min = paths.min(axis=1)

    K_CO = 50
    chooser_payoff = np.where(
        S_choice >= K_CO,
        np.maximum(S_T - K_CO, 0.0),
        np.maximum(K_CO - S_T, 0.0),
    )
    binary_payoff = np.where(S_T < 40, 10.0, 0.0)
    ko_payoff = np.where(path_min >= 35, np.maximum(45 - S_T, 0.0), 0.0)

    options = [
        ("AC_50_P",   "put",         50, days_long,  np.maximum(50 - S_T, 0.0)),
        ("AC_50_C",   "call",        50, days_long,  np.maximum(S_T - 50, 0.0)),
        ("AC_35_P",   "put",         35, days_long,  np.maximum(35 - S_T, 0.0)),
        ("AC_40_P",   "put",         40, days_long,  np.maximum(40 - S_T, 0.0)),
        ("AC_60_C",   "call",        60, days_long,  np.maximum(S_T - 60, 0.0)),
        ("AC_50_P_2", "put",         50, days_short, np.maximum(50 - S_choice, 0.0)),
        ("AC_50_C_2", "call",        50, days_short, np.maximum(S_choice - 50, 0.0)),
        ("AC_50_CO",  "chooser",     50, days_long,  chooser_payoff),
        ("AC_40_BP",  "binary put",  40, days_long,  binary_payoff),
        ("AC_45_KO",  "knock-out p", 45, days_long,  ko_payoff),
    ]

    print(f"S0={S0}  sigma={SIGMA}  paths={N_PATHS:,}  steps/day={STEPS_PER_DAY}\n")
    header = f"{'option':<10} {'type':<14} {'K':>4} {'days':>5} {'mc price':>11} {'std err':>10} {'analytic':>11}"
    print(header)
    print("-" * len(header))
    rows = []
    for name, typ, k, days, payoff in options:
        price = float(payoff.mean())
        se = float(payoff.std(ddof=1) / np.sqrt(N_PATHS))
        t = days / DAYS_PER_YEAR
        if typ == "call":
            analytic = f"{bs_call(S0, k, t, SIGMA):.4f}"
        elif typ == "put":
            analytic = f"{bs_put(S0, k, t, SIGMA):.4f}"
        else:
            analytic = "—"
        print(f"{name:<10} {typ:<14} {k:>4} {days:>5} {price:>11.4f} {se:>10.4f} {analytic:>11}")
        rows.append((name, price, se))

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    names = [r[0] for r in rows]
    prices = [r[1] for r in rows]
    ses = [r[2] for r in rows]

    ax = axes[0]
    bars = ax.bar(names, prices, yerr=ses, capsize=4, color="steelblue", alpha=0.85)
    for b, p in zip(bars, prices):
        ax.text(b.get_x() + b.get_width() / 2, p, f"{p:.2f}",
                ha="center", va="bottom", fontsize=9)
    ax.set_title(f"AETHER_CRYSTAL option prices  (S0={S0}, σ={SIGMA}, paths={N_PATHS:,})")
    ax.set_ylabel("price (XIRECs)")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(axis="y", linestyle=":", alpha=0.5)

    ax = axes[1]
    clip = float(np.quantile(S_T, 0.99))
    ax.hist(np.clip(S_T, None, clip), bins=200, color="seagreen", alpha=0.7)
    strikes = [35, 40, 45, 50, 60]
    colors = plt.cm.tab10(np.linspace(0, 1, len(strikes)))
    for k, c in zip(strikes, colors):
        ax.axvline(k, color=c, linestyle="--", label=f"K={k}")
    ax.axvline(S0, color="black", linestyle="-", linewidth=1.2, label=f"S0={S0}")
    ax.axvline(35, color="red", linestyle=":", linewidth=1.5, alpha=0.8,
               label="KO barrier=35")
    ax.set_title(f"S_T at 21d — strikes & barrier overlaid (clipped at 99th pct = {clip:.1f})")
    ax.set_xlabel("S_T")
    ax.set_ylabel("count")
    ax.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(PLOT_PATH, dpi=120)
    print(f"\nplot saved to {PLOT_PATH}")

    payoff_lookup = {opt[0]: opt[4] for opt in options}
    n = len(PAYOFF_DIST_NAMES)
    fig2, axes2 = plt.subplots(1, n, figsize=(4.2 * n, 5), sharey=False)
    for ax, name in zip(axes2, PAYOFF_DIST_NAMES):
        payoff = payoff_lookup[name]
        p_zero = float((payoff == 0).mean())
        nonzero = payoff[payoff > 0]
        mean = float(payoff.mean())
        if nonzero.size > 0:
            clip = float(np.quantile(nonzero, 0.99))
            ax.hist(np.clip(nonzero, None, clip), bins=80,
                    color="steelblue", alpha=0.85)
            ax.set_xlabel(f"payoff (clipped at 99th pct = {clip:.1f})")
        else:
            ax.set_xlabel("payoff")
        ax.axvline(mean, color="red", linestyle="--",
                   label=f"E[payoff] = {mean:.2f}")
        ax.set_title(
            f"{name}\nP(payoff=0) = {p_zero:.1%}   "
            f"nonzero count = {nonzero.size:,}"
        )
        ax.set_ylabel("count (nonzero payoffs only)")
        ax.legend()

    fig2.suptitle(
        f"Payoff distributions  (S0={S0}, σ={SIGMA}, paths={N_PATHS:,}, "
        "zero-payoff bar omitted; see P(payoff=0))"
    )
    fig2.tight_layout()
    fig2.savefig(PAYOFF_PLOT_PATH, dpi=120)
    print(f"payoff distribution plot saved to {PAYOFF_PLOT_PATH}")


if __name__ == "__main__":
    main()
