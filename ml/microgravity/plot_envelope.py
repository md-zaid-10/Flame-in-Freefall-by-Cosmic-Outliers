"""Flammability map for PMMA rods: BASS-II runs (O2 vs flow) + cited limits + habitat O2.

Usage (repo root):  python ml/microgravity/plot_envelope.py
Writes ml/figures/flammability_map_pmma_rod.png (light) and _dark.png, plus the
plotted points as a CSV (the table view of the chart).
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.transforms import blended_transform_factory
import matplotlib.ticker

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))
from microgravity import flammability as f          # noqa: E402
from gravity_bounds import baselines as b           # noqa: E402

OUT = ML / "figures"
LOW_FLOW_X = 0.6        # where the "<1 cm/s" bucket is drawn

THEMES = {
    "light": dict(surface="#fcfcfb", text="#0b0b0b", muted="#52514e", grid="#e4e3df",
                  burn="#2a78d6", noburn="#eb6834", band="#d6d5d0", hatch="#b9b8b2"),
    "dark": dict(surface="#1a1a19", text="#f0efec", muted="#c3c2b7", grid="#33332f",
                 burn="#3987e5", noburn="#d95926", band="#45443f", hatch="#5d5c56"),
}


def points():
    d = f.load_training().copy()
    rng = np.random.default_rng(1)
    x = d["flow_cm_s"].where(d["flow_cm_s"] >= 1.0, LOW_FLOW_X)
    d["x"] = x * np.exp(rng.uniform(-0.06, 0.06, len(d)))        # small jitter, log space
    d["y_plot"] = d["o2_pct"] + rng.uniform(-0.08, 0.08, len(d))
    return d


def draw(theme: str):
    t = THEMES[theme]
    d = points()
    lim = f.limiting_o2()
    g1 = b.PMMA_ROD["normal_gravity_bracket"]
    moon = b.HABITAT["moon_base_o2_min"]

    plt.rcParams.update({"font.family": "sans-serif", "font.size": 10})
    fig, ax = plt.subplots(figsize=(11, 6.2), dpi=200)
    fig.patch.set_facecolor(t["surface"]); ax.set_facecolor(t["surface"])
    fig.subplots_adjust(left=0.07, right=0.69, top=0.80, bottom=0.12)
    margin = blended_transform_factory(ax.transAxes, ax.transData)   # x: axes, y: data

    def label(y, text, va="center", color=None, weight="normal", size=9):
        ax.text(1.02, y, text, transform=margin, ha="left", va=va, fontsize=size,
                color=color or t["text"], fontweight=weight, clip_on=False)

    # untested O2 region (above tested range)
    ax.axhspan(f.TESTED_O2_RANGE[1], 32, facecolor="none", edgecolor=t["hatch"],
               hatch="//", linewidth=0, zorder=0)
    label(26, "Not tested on the ISS\n(above 22.2% O\u2082)", color=t["muted"])

    # habitat lines
    ax.axhline(moon, color=t["text"], linewidth=1.8, zorder=2)
    label(moon, "Moon base / pressurized rover\n\u226530% O\u2082 (planned)", weight="bold",
          size=9.5)
    ax.axhline(b.HABITAT["earth_air_o2"], color=t["muted"], linewidth=1, linestyle=":",
               zorder=2)
    label(b.HABITAT["earth_air_o2"], "Earth air / ISS cabin 20.9%", color=t["muted"])

    # cited 1 g value and our microgravity bracket
    ax.axhline(g1["high"], color=t["muted"], linestyle="--", linewidth=1.2, zorder=2)
    label(g1["high"] + 0.1, f"1 g: same rods burn at {g1['high']:.0f}%, blow off at "
          f"{g1['low']:.0f}%\n(Marcum, Olson & Ferkul 2016)", va="bottom", color=t["muted"],
          size=8.5)
    ax.axhspan(lim["low"], lim["high"], color=t["band"], zorder=1, linewidth=0)
    label(lim["low"] - 0.1, f"Microgravity limit {lim['low']:.1f}\u2013{lim['high']:.1f}%\n"
          "(BASS-II runs; published 13.6%)", va="top", size=8.5)

    # data: burned vs not (shape + color, never color alone)
    burn, nob = d[d["y"] == 1], d[d["y"] == 0]
    ax.scatter(burn["x"], burn["y_plot"], s=34, marker="o", color=t["burn"],
               edgecolor=t["surface"], linewidth=0.8, zorder=4,
               label=f"Kept burning ({burn['run_id'].nunique()} runs)")
    ax.scatter(nob["x"], nob["y_plot"], s=46, marker="X", color=t["noburn"],
               edgecolor=t["surface"], linewidth=0.8, zorder=5,
               label=f"Went out / no ignition ({nob['run_id'].nunique()} runs)")

    ax.set_xscale("log")
    ax.set_xlim(0.42, 42)
    ax.set_ylim(12.5, 32)
    ax.set_xticks([LOW_FLOW_X, 1, 2, 5, 10, 20, 40])
    ax.set_xticklabels(["<1", "1", "2", "5", "10", "20", "40"])
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xlabel("Air flow past the sample (cm/s)", color=t["text"])
    ax.set_ylabel("Oxygen (% by volume)", color=t["text"])
    ax.tick_params(colors=t["muted"], length=0)
    ax.grid(True, axis="y", color=t["grid"], linewidth=0.6, zorder=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.axvline(0.8, color=t["grid"], linewidth=0.8, zorder=0)

    fig.text(0.07, 0.95, "In microgravity, PMMA rods burned down to ~13.6% O\u2082, where the same rods go out on Earth (14%)",
             color=t["text"], fontsize=12.5, fontweight="bold", va="top")
    fig.text(0.07, 0.905, "A 30% O\u2082 Moon base is far above every condition where "
             "these samples already burned.", color=t["muted"], fontsize=10.5, va="top")
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(0.065, 0.875),
               ncol=2, frameon=False, labelcolor=t["text"], fontsize=9.5, handletextpad=0.3,
               columnspacing=1.5)
    fig.text(0.07, 0.02,
             "Data: NASA PSI BASS-II (PSI-25, DOI 10.60555/4qc4-de67). Each point is one flow "
             "step of an ISS run; outcomes labeled from run notes with LLM assistance.\n"
             "Flows <1 cm/s are fan-pot estimates. Points jittered slightly. 1 g and published "
             "13.6% values: Marcum, Olson & Ferkul 2016, NASA NTRS 20160012691.",
             color=t["muted"], fontsize=7, va="bottom")
    OUT.mkdir(exist_ok=True)
    suffix = "" if theme == "light" else "_dark"
    path = OUT / f"flammability_map_pmma_rod{suffix}.png"
    fig.savefig(path, facecolor=t["surface"])
    plt.close(fig)
    return path, d


if __name__ == "__main__":
    for th in THEMES:
        p, d = draw(th)
        print("wrote", p.relative_to(ML.parent))
    table = d[["run_id", "o2_pct", "flow_cm_s", "outcome", "confidence"]]
    tp = OUT / "flammability_map_pmma_rod_points.csv"
    table.to_csv(tp, index=False)
    print("wrote", tp.relative_to(ML.parent))
