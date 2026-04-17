import math

import matplotlib.pyplot as plt
import numpy as np
from scipy.special import lambertw

BUDGET = 50_000
COST_PER_PCT = BUDGET / 100
C = 14_000 / math.log(101)


def optimal_research_scale(sp, m):
    B = 100 - sp
    if B <= 0:
        return 0.0, 0.0
    r = (B + 1) / float(lambertw(math.e * (B + 1)).real) - 1
    s = B - r
    if m * C * s * math.log(1 + r) <= 500 * B:
        return 0.0, 0.0
    return float(r), float(s)


def pnl(r, s, sp, m):
    return C * m * s * math.log(1 + r) - COST_PER_PCT * (r + s + sp)


speeds = np.arange(0, 101, 5)
multipliers = np.round(np.arange(0.10, 0.9001, 0.05), 2)

Z = np.zeros((len(multipliers), len(speeds)))
R_opt = np.zeros_like(Z)
S_opt = np.zeros_like(Z)

for i, m in enumerate(multipliers):
    for j, sp in enumerate(speeds):
        r, s = optimal_research_scale(int(sp), float(m))
        Z[i, j] = pnl(r, s, sp, m)
        R_opt[i, j] = r
        S_opt[i, j] = s

vmax = np.abs(Z).max()
fig, ax = plt.subplots(figsize=(18, 9))
im = ax.imshow(
    Z,
    aspect="auto",
    origin="lower",
    cmap="RdBu",
    vmin=-vmax, vmax=vmax,
)

ax.set_xticks(range(len(speeds)))
ax.set_xticklabels(speeds)
ax.set_yticks(range(len(multipliers)))
ax.set_yticklabels([f"{m:.2f}" for m in multipliers])
ax.set_xlabel("Speed investment (%)")
ax.set_ylabel("Speed multiplier")
ax.set_title("Optimal allocation per (speed invest, multiplier)\n"
             "cell label: R=research%  S=scale%  (sp=speed%)  PnL in color")

for i in range(len(multipliers)):
    for j in range(len(speeds)):
        r, s, p = R_opt[i, j], S_opt[i, j], Z[i, j]
        color = "white" if abs(p) > 0.55 * vmax else "black"
        ax.text(
            j, i,
            f"R:{r:.0f}\nS:{s:.0f}\n{p/1000:+.0f}k",
            ha="center", va="center", fontsize=7, color=color,
        )

cbar = fig.colorbar(im, ax=ax)
cbar.set_label("PnL (XIRECs)")

out = "/home/utkarsh/Documents/codebase/IMCProsperity_2026/IMCProsperity/manual/invest_expand_heatmap_annot.png"
fig.tight_layout()
fig.savefig(out, dpi=130)
print(f"Saved: {out}")
plt.show()
