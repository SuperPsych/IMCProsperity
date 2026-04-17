import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

BUDGET = 50_000
COST_PER_PCT = BUDGET / 100
LN_101 = np.log(101)


def research(r):
    return 200_000 * np.log(1 + r) / LN_101


def scale(s):
    return 7 * s / 100


def optimal_rs(sp, m):
    max_rs = 100 - sp
    rs = np.arange(0, max_rs + 1)
    R, S = np.meshgrid(rs, rs, indexing="ij")
    valid = (R + S) <= max_rs
    gross = research(R) * scale(S) * m
    cost = (R + S + sp) * COST_PER_PCT
    pnl = np.where(valid, gross - cost, -np.inf)
    idx = np.unravel_index(np.argmax(pnl), pnl.shape)
    return pnl[idx], int(R[idx]), int(S[idx])


speeds = np.arange(0, 101, 1)
multipliers = np.round(np.arange(0.10, 0.9001, 0.05), 2)

Z = np.zeros((len(multipliers), len(speeds)))
R_opt = np.zeros_like(Z, dtype=int)
S_opt = np.zeros_like(Z, dtype=int)

for i, m in enumerate(multipliers):
    for j, sp in enumerate(speeds):
        p, r, s = optimal_rs(int(sp), float(m))
        Z[i, j] = p
        R_opt[i, j] = r
        S_opt[i, j] = s

# Sanity check against the provided example
p0, r0, s0 = optimal_rs(0, 0.10)
print(f"Example check: sp=0, m=0.10 -> r={r0}, s={s0}, profit={p0:.0f}")

fig, axes = plt.subplots(1, 3, figsize=(22, 7))

im0 = axes[0].imshow(
    Z,
    aspect="auto",
    origin="lower",
    extent=[speeds.min() - 0.5, speeds.max() + 0.5,
            multipliers.min() - 0.025, multipliers.max() + 0.025],
    cmap="viridis",
)
axes[0].set_title("Optimal PnL")
axes[0].set_xlabel("Speed investment (%)")
axes[0].set_ylabel("Speed multiplier")
axes[0].set_yticks(multipliers)
fig.colorbar(im0, ax=axes[0], label="PnL (XIRECs)")

im1 = axes[1].imshow(
    R_opt,
    aspect="auto",
    origin="lower",
    extent=[speeds.min() - 0.5, speeds.max() + 0.5,
            multipliers.min() - 0.025, multipliers.max() + 0.025],
    cmap="plasma",
    vmin=0, vmax=100,
)
axes[1].set_title("Optimal Research %")
axes[1].set_xlabel("Speed investment (%)")
axes[1].set_ylabel("Speed multiplier")
axes[1].set_yticks(multipliers)
fig.colorbar(im1, ax=axes[1], label="Research %")

im2 = axes[2].imshow(
    S_opt,
    aspect="auto",
    origin="lower",
    extent=[speeds.min() - 0.5, speeds.max() + 0.5,
            multipliers.min() - 0.025, multipliers.max() + 0.025],
    cmap="cividis",
    vmin=0, vmax=100,
)
axes[2].set_title("Optimal Scale %")
axes[2].set_xlabel("Speed investment (%)")
axes[2].set_ylabel("Speed multiplier")
axes[2].set_yticks(multipliers)
fig.colorbar(im2, ax=axes[2], label="Scale %")

fig.suptitle(
    "Invest & Expand: best (Research, Scale) for each (Speed investment, Speed multiplier)",
    fontsize=14,
)
fig.tight_layout()

out_heat = "/home/utkarsh/Documents/codebase/IMCProsperity_2026/IMCProsperity/manual/invest_expand_heatmap.png"
fig.savefig(out_heat, dpi=120)
print(f"Saved: {out_heat}")

fig2, ax2 = plt.subplots(figsize=(12, 7))
cmap = plt.get_cmap("viridis")
for i, m in enumerate(multipliers):
    color = cmap(i / max(1, len(multipliers) - 1))
    ax2.plot(speeds, Z[i], color=color, label=f"m={m:.2f}")
ax2.axhline(0, color="k", lw=0.8, ls="--")
ax2.set_xlabel("Speed investment (%)")
ax2.set_ylabel("Optimal PnL (XIRECs)")
ax2.set_title("Optimal PnL vs Speed investment, per Speed multiplier")
ax2.grid(True, alpha=0.3)
ax2.legend(loc="upper right", ncol=2, fontsize=9)

out_lines = "/home/utkarsh/Documents/codebase/IMCProsperity_2026/IMCProsperity/manual/invest_expand_lines.png"
fig2.tight_layout()
fig2.savefig(out_lines, dpi=120)
print(f"Saved: {out_lines}")

best_i, best_j = np.unravel_index(np.argmax(Z), Z.shape)
print(
    f"Global best in grid: sp={speeds[best_j]}, m={multipliers[best_i]:.2f}, "
    f"r={R_opt[best_i, best_j]}, s={S_opt[best_i, best_j]}, pnl={Z[best_i, best_j]:.0f}"
)

plt.close("all")
