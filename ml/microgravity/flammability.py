"""Empirical microgravity flammability envelope for PMMA rods, from BASS-II (PSI-25).

Why empirical, not a fitted curve
---------------------------------
In BASS-II the operators stepped airflow down to ~0 in nearly every run, so low-flow
extinctions happen at every O2 level (15-21 %) and carry no information about O2. Only one
run (O12, 13.6 % O2, no ignition) sits below the limit. A regression cannot identify an O2
effect from that (it returned an O2 slope of ~0 and a limit of -78 %). So we report what
the ISS runs directly show, with honest uncertainty:

- predict(): observed burn fraction in the (O2 band, flow band) cell containing the query,
  counted per RUN (steps within a run are not independent), with a 95 % Jeffreys interval.
- boundary(): limiting O2 bracketed between the highest non-burning and lowest burning O2
  inside the 1-10 cm/s window; outside that window the boundary is "not determined".

Data rules: flows below 1 cm/s come from fan-pot settings with no reliable calibration,
so they form one "<1 cm/s" band. Only PMMA rods have enough runs; other materials return
NaN with a status. O2 above the tested range uses the top band as a lower bound (assumes
more O2 never makes burning less likely); below the range returns NaN.

Caveats for the pitch: ISS cabin pressure assumed (no pressure column); microgravity only;
labels are LLM-assisted (see notes column in bass2_labels.csv).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta

HERE = Path(__file__).resolve().parent
LABELS = HERE / "bass2_labels.csv"

SUPPORTED = ["pmma_rod"]
TESTED_O2_RANGE = (13.6, 22.2)
O2_EDGES = [13.5, 14.5, 16.0, 18.0, 22.3]          # first band isolates the no-ignition run
FLOW_EDGES = [0.0, 1.0, 10.0 + 1e-9, np.inf]
FLOW_LABELS = ["<1", "1-10", ">10"]
BURN_WINDOW = (1.0, 10.0)                           # flow window used for the O2 limit
POSITIVE = {"burn"}
NEGATIVE = {"extinguish", "blowoff", "no_ignition"}
INSUFFICIENT = "insufficient data: only PMMA rods have enough BASS-II runs"
NAN3 = {"p_burn": float("nan"), "low": float("nan"), "high": float("nan")}


def material_class(material: str, thickness_mm: float | None = None) -> str:
    m = str(material).lower().replace(" ", "_")
    if "sibal" in m:
        return "sibal"
    if "rod" in m:
        return "pmma_rod"
    if "film" in m:
        return "pmma_film"
    if "slab" in m:
        return "pmma_slab"
    if "pmma" in m and thickness_mm is not None and not np.isnan(thickness_mm):
        return "pmma_film" if thickness_mm <= 0.5 else "pmma_slab"
    return "other"


def is_supported(material: str) -> bool:
    return material_class(material) in SUPPORTED


def is_extrapolation(o2_pct: float) -> bool:
    return not (TESTED_O2_RANGE[0] <= o2_pct <= TESTED_O2_RANGE[1])


def _o2_band(o2):
    return pd.cut(np.atleast_1d(o2), O2_EDGES, right=False)


def _flow_band(flow):
    return pd.cut(np.atleast_1d(flow), FLOW_EDGES, labels=FLOW_LABELS, right=False)


# ---------------- data ----------------
def load_training(path: Path = LABELS) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["outcome"] = d["outcome"].fillna("").str.strip().str.lower()
    d["mclass"] = d["material"].map(material_class)
    d = d[d["outcome"].isin(POSITIVE | NEGATIVE) & d["mclass"].isin(SUPPORTED)]
    d = d[d["flow_cm_s"].notna() & d["o2_pct"].notna()].copy()
    d["y"] = d["outcome"].isin(POSITIVE).astype(int)
    d["o2_band"] = _o2_band(d["o2_pct"].values)
    d["flow_band"] = _flow_band(d["flow_cm_s"].values)
    return d.reset_index(drop=True)


@lru_cache(maxsize=1)
def envelope() -> pd.DataFrame:
    """Per (O2 band, flow band): runs, burn fraction (per run) and 95 % Jeffreys interval."""
    d = load_training()
    per_run = d.groupby(["o2_band", "flow_band", "run_id"], observed=True)["y"].mean()
    cells = per_run.groupby(level=[0, 1], observed=True).agg(k="sum", n="size").reset_index()
    cells["p_burn"] = cells["k"] / cells["n"]
    a, b = cells["k"] + 0.5, cells["n"] - cells["k"] + 0.5
    cells["low"] = np.where(cells["k"] == 0, 0.0, beta.ppf(0.025, a, b))
    cells["high"] = np.where(cells["k"] == cells["n"], 1.0, beta.ppf(0.975, a, b))
    runs = d.groupby(["o2_band", "flow_band"], observed=True)["run_id"].apply(
        lambda s: ",".join(sorted(s.unique())))
    return cells.merge(runs.rename("runs").reset_index(), on=["o2_band", "flow_band"])


@lru_cache(maxsize=1)
def limiting_o2(material: str = "pmma_rod") -> dict:
    """Bracket for the lowest O2 that sustained burning inside the 1-10 cm/s window."""
    if not is_supported(material):
        return {"o2": float("nan"), "low": float("nan"), "high": float("nan"),
                "evidence": INSUFFICIENT}
    d = load_training()
    w = d[d["flow_cm_s"].between(*BURN_WINDOW)]
    burn = w[w["y"] == 1].nsmallest(1, "o2_pct").iloc[0]
    below = w[(w["y"] == 0) & (w["o2_pct"] < burn["o2_pct"])]
    if below.empty:
        lo, lo_run = float("nan"), "none"
    else:
        r = below.nlargest(1, "o2_pct").iloc[0]
        lo, lo_run = float(r["o2_pct"]), f"{r['run_id']} ({r['outcome']})"
    hi = float(burn["o2_pct"])
    return {"o2": (lo + hi) / 2, "low": lo, "high": hi,
            "evidence": f"no burn at {lo}% ({lo_run}); burned at {hi}% ({burn['run_id']})"}


# ---------------- public ----------------
def predict(material, thickness_mm, o2_pct, flow_cm_s) -> dict:
    if not is_supported(material) or o2_pct < TESTED_O2_RANGE[0]:
        return dict(NAN3)
    env = envelope()
    fband = _flow_band(flow_cm_s)[0]
    if o2_pct > TESTED_O2_RANGE[1]:  # monotone-in-O2 assumption: top band is a lower bound
        top = env[(env["flow_band"] == fband)].sort_values("o2_band").tail(1)
        if top.empty:
            return dict(NAN3)
        r = top.iloc[0]
        return {"p_burn": float(r["p_burn"]), "low": float(r["low"]), "high": 1.0}
    cell = env[(env["o2_band"] == _o2_band(o2_pct)[0]) & (env["flow_band"] == fband)]
    if cell.empty:
        return dict(NAN3)
    r = cell.iloc[0]
    return {"p_burn": float(r["p_burn"]), "low": float(r["low"]), "high": float(r["high"])}


def boundary(material, flows=None) -> pd.DataFrame:
    flows = np.geomspace(0.5, 30, 40) if flows is None else np.asarray(flows, float)
    out = pd.DataFrame({"flow_cm_s": flows, "o2_min": np.nan, "low": np.nan, "high": np.nan})
    if not is_supported(material):
        out.attrs["status"] = INSUFFICIENT
        return out
    lim = limiting_o2(material)
    inside = (flows >= BURN_WINDOW[0]) & (flows <= BURN_WINDOW[1])
    out.loc[inside, ["o2_min", "low", "high"]] = [lim["o2"], lim["low"], lim["high"]]
    out.attrs["status"] = ("ok: bracket inside 1-10 cm/s; outside not determined "
                           "(flames quench below ~1 cm/s and blew off above ~11 cm/s)")
    out.attrs["evidence"] = lim["evidence"]
    return out
