import math

import numpy as np
import plotly.graph_objects as go
from scipy.special import lambertw

BUDGET = 50_000
COST_PER_PCT = BUDGET / 100
C = 14_000 / math.log(101)  # research(r) * scale(s) = C * s * ln(1+r)


def optimal_research_scale(speed_pct, speed_multiplier):
    B = 100 - speed_pct
    if B <= 0:
        return 0.0, 0.0
    r = (B + 1) / float(lambertw(math.e * (B + 1)).real) - 1
    s = B - r
    if speed_multiplier * C * s * math.log(1 + r) <= 500 * B:
        return 0.0, 0.0
    return float(r), float(s)


def pnl(r, s, sp, m):
    return C * m * s * math.log(1 + r) - COST_PER_PCT * (r + s + sp)


speeds = np.arange(0, 101, 1)
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

# customdata: (r, s, total_pct, budget_used_xirec) per cell
custom = np.stack(
    [
        R_opt,
        S_opt,
        R_opt + S_opt + speeds[np.newaxis, :],
        (R_opt + S_opt + speeds[np.newaxis, :]) * COST_PER_PCT,
    ],
    axis=-1,
)

hover = (
    "<b>Speed invest:</b> %{x}%<br>"
    "<b>Speed multiplier:</b> %{y:.2f}<br>"
    "<b>PnL:</b> %{z:,.0f} XIRECs<br>"
    "<b>Research:</b> %{customdata[0]:.1f}%<br>"
    "<b>Scale:</b> %{customdata[1]:.1f}%<br>"
    "<b>Total used:</b> %{customdata[2]:.1f}%  (%{customdata[3]:,.0f} XIRECs)"
    "<extra></extra>"
)

# High-contrast diverging colorscale centered at 0
zmin, zmax = float(Z.min()), float(Z.max())
abs_max = max(abs(zmin), abs(zmax))
colorscale = [
    [0.0, "#67001f"],
    [(abs_max + zmin) / (2 * abs_max) * 0.5, "#d6604d"],
    [0.5 * (abs_max + zmin) / abs_max + 1e-9, "#f7f7f7"],
    [0.5 * (abs_max + zmin) / abs_max + 0.25, "#92c5de"],
    [0.5 * (abs_max + zmin) / abs_max + 0.5, "#2166ac"],
    [1.0, "#053061"],
]
# simpler: let plotly do the centering
fig = go.Figure(
    go.Heatmap(
        x=speeds,
        y=multipliers,
        z=Z,
        customdata=custom,
        hovertemplate=hover,
        colorscale="RdBu",
        zmid=0,
        colorbar=dict(title="PnL (XIRECs)"),
    )
)

fig.update_layout(
    title="Invest & Expand — optimal PnL (hover or click a cell for allocation)",
    xaxis_title="Speed investment (%)",
    yaxis_title="Speed multiplier",
    xaxis=dict(dtick=5),
    yaxis=dict(tickvals=multipliers, dtick=0.05),
    width=1100,
    height=650,
)

# JS click handler: show allocation in an on-plot annotation
click_js = """
<script>
  const gd = document.getElementsByClassName('plotly-graph-div')[0];
  gd.on('plotly_click', function(ev){
    const p = ev.points[0];
    const cd = p.customdata;
    const txt =
      'Speed invest: ' + p.x + '%<br>' +
      'Speed mult: ' + p.y.toFixed(2) + '<br>' +
      'Research: ' + cd[0].toFixed(1) + '%<br>' +
      'Scale: ' + cd[1].toFixed(1) + '%<br>' +
      'Total: ' + cd[2].toFixed(1) + '% (' + cd[3].toLocaleString(undefined,{maximumFractionDigits:0}) + ' XIRECs)<br>' +
      'PnL: ' + p.z.toLocaleString(undefined,{maximumFractionDigits:0}) + ' XIRECs';
    Plotly.relayout(gd, {
      'annotations': [{
        x: 0.01, y: 0.99, xref: 'paper', yref: 'paper',
        xanchor: 'left', yanchor: 'top',
        text: txt, showarrow: false, align: 'left',
        bgcolor: 'rgba(255,255,255,0.9)',
        bordercolor: 'black', borderwidth: 1, borderpad: 6,
        font: { size: 13, family: 'monospace' }
      }]
    });
  });
</script>
"""

import os
import tempfile
import webbrowser

out_html = os.path.join(tempfile.gettempdir(), "invest_expand_interactive.html")
fig.write_html(out_html, include_plotlyjs=True, post_script=click_js, auto_open=False)
print(f"Saved: {out_html}")
webbrowser.open("file://" + out_html)

# Sanity check
r, s = optimal_research_scale(0, 0.10)
print(f"sp=0, m=0.10 -> r={r:.2f}, s={s:.2f}, pnl={pnl(r, s, 0, 0.10):.0f}")
