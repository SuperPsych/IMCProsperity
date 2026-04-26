"""
Portfolio PnL Monte Carlo for AETHER_CRYSTAL spot + options.

Calibration matches aether_options_mc.py:
    sigma = 2.51 (annualized)
    grid  = 4 steps per trading day
    year  = 252 trading days
    S0    = 50, r = 0

Nested MC: simulate `n_outer` batches of `n_inner` paths each.
Returns mean PnL, variance, and a histogram of the `n_outer` batch means.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


SIGMA = 2.51
STEPS_PER_DAY = 4
DAYS_PER_YEAR = 252
S0 = 50.0

# 21 Solvenarian Days = 15 trading days; 14 Solvenarian Days = 10 trading days
DAYS_LONG = 15
DAYS_SHORT = 10
KO_BARRIER = 35
BP_PAYOUT = 10.0
K_CO = 50

# Top-of-book bid/ask from the screenshot.
# Long position pays the ask; short position receives the bid.
# AC spot has no quote in the screenshot — defaults to S0; pass overrides if needed.
DEFAULT_BID = {
    "AC":        49.975,
    "AC_50_P":   12.00,
    "AC_50_C":   12.00,
    "AC_35_P":   4.33,
    "AC_40_P":   6.50,
    "AC_45_P":   9.05,
    "AC_60_C":   8.80,
    "AC_50_P_2": 9.70,
    "AC_50_C_2": 9.70,
    "AC_50_CO":  22.20,
    "AC_40_BP":  5.00,
    "AC_45_KO":  0.15,
}

DEFAULT_ASK = {
    "AC":        50.025,
    "AC_50_P":   12.05,
    "AC_50_C":   12.05,
    "AC_35_P":   4.35,
    "AC_40_P":   6.55,
    "AC_45_P":   9.10,
    "AC_60_C":   8.85,
    "AC_50_P_2": 9.75,
    "AC_50_C_2": 9.75,
    "AC_50_CO":  22.30,
    "AC_40_BP":  5.10,
    "AC_45_KO":  0.175,
}

# Max absolute position per instrument (from the size column in the screenshot).
# AC spot limit unknown — left as None (no check).
POSITION_LIMITS = {
    "AC":        200,
    "AC_50_P":   50,
    "AC_50_C":   50,
    "AC_35_P":   50,
    "AC_40_P":   50,
    "AC_45_P":   50,
    "AC_60_C":   50,
    "AC_50_P_2": 50,
    "AC_50_C_2": 50,
    "AC_50_CO":  50,
    "AC_40_BP":  50,
    "AC_45_KO":  500,
}

PLOT_PATH = Path(__file__).parent / "portfolio_pnl_mc.png"
TERMINAL_PLOT_PATH = Path(__file__).parent / "portfolio_pnl_terminal.png"


def simulate_paths(n_paths: int, rng: np.random.Generator) -> np.ndarray:
    """Return shape (n_paths, DAYS_LONG*STEPS_PER_DAY) of GBM paths from S0."""
    n_steps = DAYS_LONG * STEPS_PER_DAY
    dt = 1.0 / DAYS_PER_YEAR / STEPS_PER_DAY
    drift = -0.5 * SIGMA**2 * dt
    diffusion = SIGMA * np.sqrt(dt)
    z = rng.standard_normal((n_paths, n_steps))
    log_path = np.log(S0) + np.cumsum(drift + diffusion * z, axis=1)
    return np.exp(log_path)


def per_unit_payoffs(paths: np.ndarray) -> dict[str, np.ndarray]:
    """Terminal payoff per unit for every instrument, vectorised over paths."""
    S_T = paths[:, -1]
    S_choice = paths[:, DAYS_SHORT * STEPS_PER_DAY - 1]
    path_min = paths.min(axis=1)
    chooser = np.where(
        S_choice >= K_CO,
        np.maximum(S_T - K_CO, 0.0),
        np.maximum(K_CO - S_T, 0.0),
    )
    return {
        "AC":        S_T,
        "AC_50_P":   np.maximum(50 - S_T, 0.0),
        "AC_50_C":   np.maximum(S_T - 50, 0.0),
        "AC_35_P":   np.maximum(35 - S_T, 0.0),
        "AC_40_P":   np.maximum(40 - S_T, 0.0),
        "AC_45_P":   np.maximum(45 - S_T, 0.0),
        "AC_60_C":   np.maximum(S_T - 60, 0.0),
        "AC_50_P_2": np.maximum(50 - S_choice, 0.0),
        "AC_50_C_2": np.maximum(S_choice - 50, 0.0),
        "AC_50_CO":  chooser,
        "AC_40_BP":  np.where(S_T < 40, BP_PAYOUT, 0.0),
        "AC_45_KO":  np.where(path_min >= KO_BARRIER, np.maximum(45 - S_T, 0.0), 0.0),
    }


def simulate_portfolio_pnl(
    positions: dict[str, float],
    bid_prices: dict[str, float] | None = None,
    ask_prices: dict[str, float] | None = None,
    n_inner: int = 100,
    n_outer: int = 10_000,
    seed: int = 42,
    chunk: int = 500,
    plot_path: Path | str = PLOT_PATH,
    show: bool = False,
):
    """
    positions     signed quantities, e.g. {"AC_50_P": -10, "AC_45_KO": 100, "AC": 5}
                  positive = long  (you cross the ask),
                  negative = short (you cross the bid).
    bid_prices    overrides for DEFAULT_BID
    ask_prices    overrides for DEFAULT_ASK
    n_inner       paths per outer batch.
    n_outer       number of outer batches (also points in the histogram).
    chunk         outer batches per simulated block (memory knob).

    Returns (expected_pnl, var_batch_means, batch_means).
    """
    bid = {**DEFAULT_BID, **(bid_prices or {})}
    ask = {**DEFAULT_ASK, **(ask_prices or {})}
    unknown = set(positions) - set(DEFAULT_BID)
    if unknown:
        raise ValueError(f"unknown instruments: {sorted(unknown)}")
    breached = [
        f"{n} (pos={q}, limit=+/-{POSITION_LIMITS[n]})"
        for n, q in positions.items()
        if POSITION_LIMITS.get(n) is not None and abs(q) > POSITION_LIMITS[n]
    ]
    if breached:
        raise ValueError("position limit exceeded for: " + "; ".join(breached))

    rng = np.random.default_rng(seed)
    batch_means = np.empty(n_outer)
    sumsq_dev = 0.0
    grand_sum = 0.0
    total = n_outer * n_inner

    for start in range(0, n_outer, chunk):
        size = min(chunk, n_outer - start)
        paths = simulate_paths(size * n_inner, rng)
        po = per_unit_payoffs(paths)

        pnl = np.zeros(size * n_inner)
        for name, qty in positions.items():
            if qty == 0:
                continue
            entry = ask[name] if qty > 0 else bid[name]
            pnl += qty * (po[name] - entry)

        block = pnl.reshape(size, n_inner)
        batch_means[start:start + size] = block.mean(axis=1)
        grand_sum += pnl.sum()
        sumsq_dev += ((pnl - pnl.mean()) ** 2).sum() + size * n_inner * (pnl.mean()) ** 2

    expected_pnl = grand_sum / total
    # per-trade variance across all n_inner*n_outer single-path PnLs
    var_trade = sumsq_dev / total - expected_pnl ** 2
    var_batch_means = batch_means.var(ddof=1)
    std_err = np.sqrt(var_batch_means / n_outer)

    print(f"positions:           {positions}")
    print(f"paths simulated:     {total:,}  ({n_outer:,} batches x {n_inner})")
    print(f"E[PnL]               = {expected_pnl:+.4f}  +/- {std_err:.4f}")
    print(f"Var(per-trade PnL)   = {var_trade:.4f}    (std {np.sqrt(var_trade):.4f})")
    print(f"Var(batch-mean PnL)  = {var_batch_means:.4f}    (std {np.sqrt(var_batch_means):.4f})")
    print(f"P(batch loss)        = {(batch_means < 0).mean():.3%}")
    print(f"5th / 95th pct batch = {np.quantile(batch_means, 0.05):+.3f} / "
          f"{np.quantile(batch_means, 0.95):+.3f}")

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.hist(batch_means, bins=80, color="steelblue", alpha=0.85, edgecolor="white")
    ax.axvline(expected_pnl, color="red", linestyle="--",
               label=f"E[PnL] = {expected_pnl:+.3f}")
    ax.axvline(0, color="black", linestyle=":", linewidth=1)
    pos_str = ", ".join(f"{k}:{v:+g}" for k, v in positions.items() if v)
    ax.set_title(
        f"Batch-mean PnL distribution  ({n_outer:,} batches x {n_inner} paths)\n"
        f"positions: {pos_str}\n"
        f"sigma_batch = {np.sqrt(var_batch_means):.3f}    "
        f"sigma_trade = {np.sqrt(var_trade):.3f}"
    )
    ax.set_xlabel("batch-mean PnL (XIRECs)")
    ax.set_ylabel("count")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(plot_path, dpi=120)
    print(f"plot saved to {plot_path}")
    if show:
        plt.show()
    plt.close(fig)

    return expected_pnl, var_batch_means, batch_means

def _terminal_payoff_per_unit(name: str, S: np.ndarray, ko_alive: bool) -> np.ndarray:
    """Per-unit terminal payoff vs final price S, assuming S_choice = S_T."""
    if name == "AC":         return S
    if name == "AC_50_P":    return np.maximum(50 - S, 0.0)
    if name == "AC_50_C":    return np.maximum(S - 50, 0.0)
    if name == "AC_35_P":    return np.maximum(35 - S, 0.0)
    if name == "AC_40_P":    return np.maximum(40 - S, 0.0)
    if name == "AC_45_P":    return np.maximum(45 - S, 0.0)
    if name == "AC_60_C":    return np.maximum(S - 60, 0.0)
    if name == "AC_50_P_2":  return np.maximum(50 - S, 0.0)
    if name == "AC_50_C_2":  return np.maximum(S - 50, 0.0)
    if name == "AC_50_CO":   return np.abs(S - K_CO)
    if name == "AC_40_BP":   return np.where(S < 40, BP_PAYOUT, 0.0)
    if name == "AC_45_KO":
        return np.maximum(45 - S, 0.0) if ko_alive else np.zeros_like(S)
    raise ValueError(f"unknown instrument: {name}")


def plot_terminal_pnl(
    positions: dict[str, float],
    bid_prices: dict[str, float] | None = None,
    ask_prices: dict[str, float] | None = None,
    S_min: float = 0.0,
    S_max: float = 100.0,
    n_points: int = 401,
    plot_path: Path | str = TERMINAL_PLOT_PATH,
    show: bool = False,
):
    """
    Plot total portfolio PnL as a function of final underlying price S_T,
    for the two AC_45_KO barrier scenarios:
        - KO alive (path_min >= 35): KO put pays max(45 - S_T, 0)
        - Knocked out (path_min < 35): KO put pays 0
    Path-dependent S_choice instruments are evaluated with S_choice = S_T,
    which collapses AC_50_P_2/AC_50_C_2 to vanilla 50P/50C and AC_50_CO to
    a 50-strike straddle.
    """
    bid = {**DEFAULT_BID, **(bid_prices or {})}
    ask = {**DEFAULT_ASK, **(ask_prices or {})}
    unknown = set(positions) - set(DEFAULT_BID)
    if unknown:
        raise ValueError(f"unknown instruments: {sorted(unknown)}")

    S = np.linspace(S_min, S_max, n_points)
    scenarios = [
        ("KO alive  (path_min >= 35)", True),
        ("Knocked out  (path_min < 35)", False),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, (title, ko_alive) in zip(axes, scenarios):
        total = np.zeros_like(S)
        for name, qty in positions.items():
            if qty == 0:
                continue
            entry = ask[name] if qty > 0 else bid[name]
            leg = qty * (_terminal_payoff_per_unit(name, S, ko_alive) - entry)
            ax.plot(S, leg, alpha=0.45, linewidth=1, label=f"{name} ({qty:+g})")
            total += leg

        ax.plot(S, total, color="black", linewidth=2.2, label="Portfolio")
        ax.axhline(0, color="grey", linewidth=0.7)
        ax.axvline(S0, color="grey", linewidth=0.7, linestyle=":")
        ax.set_title(title)
        ax.set_xlabel("Final underlying price S_T")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")
        breakeven_idx = np.where(np.diff(np.sign(total)))[0]
        for i in breakeven_idx:
            ax.axvline(S[i], color="red", linewidth=0.6, alpha=0.5)
    axes[0].set_ylabel("PnL (XIRECs)")
    pos_str = ", ".join(f"{k}:{v:+g}" for k, v in positions.items() if v)
    fig.suptitle(
        f"Terminal portfolio PnL vs S_T   (S_choice = S_T assumed)\n"
        f"positions: {pos_str}"
    )
    fig.tight_layout()
    fig.savefig(plot_path, dpi=120)
    print(f"terminal-payoff plot saved to {plot_path}")
    if show:
        plt.show()
    plt.close(fig)


# fix underlying
if __name__ == "__main__":
    # Example: long 100 cheap KO puts, short 10 chooser, long 5 spot
    example_positions = {
        "AC_50_P":   0,
        "AC_50_C":   0,
        "AC_50_C_2": 50,
        "AC_50_P_2": 50,
        "AC_50_CO": -50,
        # "AC_40_BP": -50,
        #"AC_45_P": 50,
    }
    simulate_portfolio_pnl(example_positions)
    plot_terminal_pnl(example_positions)
