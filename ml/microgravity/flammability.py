"""Microgravity flammability model trained on BASS-II (PSI-25) step labels.

Model: pooled logistic regression, P(flame survives) vs
    O2 %, log(1+flow), log(1+flow)^2, log(thickness), one-hot material class.
The squared flow term lets the boundary be U-shaped: flames quench at very low flow
(oxygen starvation in microgravity) and blow off at high flow.

Uncertainty: cluster bootstrap over runs (steps within one run are not independent).
Extinction boundary: for each flow, the O2 where P(burn) = 0.5 (closed form, since
the model is linear in O2).

Caveats to carry into the pitch:
- Trained on 13.6-22.2 % O2 only. Anything outside is extrapolation.
- No pressure column in BASS-II; ISS cabin ~101 kPa assumed (verify before stating).
- gravity ~0 only. Partial gravity bounds come from ml/gravity_bounds (Jaisheel).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

HERE = Path(__file__).resolve().parent
LABELS = HERE / "bass2_labels.csv"

CLASSES = ["pmma_film", "pmma_slab", "pmma_rod", "sibal"]  # modeled material classes
TESTED_O2_RANGE = (13.6, 22.2)
POSITIVE = {"burn"}
NEGATIVE = {"extinguish", "blowoff", "no_ignition"}
CONF_WEIGHT = {"high": 1.0, "medium": 0.8, "low": 0.5}
N_BOOT = 300
SEED = 0


# ---------------- data ----------------
def material_class(material: str, thickness_mm: float | None = None) -> str:
    """Map free-form names ('PMMA rod', 'pmma_slab_2sided', 'sibal') to a model class."""
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
    raise ValueError(f"no model for material {material!r}; known: {CLASSES}")


def load_training(path: Path = LABELS) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["outcome"] = d["outcome"].fillna("").str.strip().str.lower()
    d = d[d["outcome"].isin(POSITIVE | NEGATIVE)]
    d = d[d["flow_cm_s"].notna() & d["o2_pct"].notna()]
    d = d[d["material"].map(lambda m: any(c in str(m) for c in CLASSES))].copy()
    d["mclass"] = d["material"].map(material_class)
    d["y"] = d["outcome"].isin(POSITIVE).astype(int)
    d["w"] = d["confidence"].map(CONF_WEIGHT).fillna(0.5)
    return d.reset_index(drop=True)


@lru_cache(maxsize=None)
def class_thickness() -> dict:
    """Median thickness per class (used for boundary() and when SIBAL has none)."""
    d = pd.read_csv(LABELS)
    d = d[d["material"].map(lambda m: any(c in str(m) for c in CLASSES))]
    d["mclass"] = d["material"].map(material_class)
    med = d.groupby("mclass")["thickness_mm"].median().to_dict()
    return {c: (med.get(c) if pd.notna(med.get(c)) else 1.0) for c in CLASSES}


def features(o2, flow, thickness, mclass) -> np.ndarray:
    o2, flow, thickness = (np.atleast_1d(np.asarray(v, dtype=float)) for v in (o2, flow, thickness))
    mclass = np.atleast_1d(np.asarray(mclass))
    lf = np.log1p(np.clip(flow, 0, None))
    lt = np.log(np.clip(thickness, 1e-3, None))
    onehot = np.stack([(mclass == c).astype(float) for c in CLASSES[1:]], axis=1)  # film = base
    return np.column_stack([o2, lf, lf ** 2, lt, onehot])


def _xy(d: pd.DataFrame):
    thk = d["thickness_mm"].fillna(d["mclass"].map(class_thickness()))
    return features(d["o2_pct"], d["flow_cm_s"], thk, d["mclass"]), d["y"].values, d["w"].values


# ---------------- fitting ----------------
def _fit(X, y, w):
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    clf = LogisticRegression(C=1.0, max_iter=2000).fit((X - mu) / sd, y, sample_weight=w)
    beta = clf.coef_[0] / sd                         # back to raw-feature scale
    b0 = clf.intercept_[0] - np.sum(clf.coef_[0] * mu / sd)
    return np.concatenate([[b0], beta])


@lru_cache(maxsize=1)
def fitted() -> dict:
    """Point fit + cluster-bootstrap coefficient draws. Cached per process."""
    d = load_training()
    if d["y"].nunique() < 2:
        raise RuntimeError("labels need both burn and non-burn rows to fit")
    X, y, w = _xy(d)
    point = _fit(X, y, w)

    rng = np.random.default_rng(SEED)
    runs = d["run_id"].unique()
    idx_by_run = {r: np.flatnonzero(d["run_id"].values == r) for r in runs}
    draws = []
    for _ in range(N_BOOT):
        idx = np.concatenate([idx_by_run[r] for r in rng.choice(runs, len(runs))])
        if len(np.unique(y[idx])) < 2:
            continue
        draws.append(_fit(X[idx], y[idx], w[idx]))
    return {"point": point, "draws": np.array(draws), "n_rows": len(d),
            "n_runs": len(runs), "data": d}


def _prob(coefs: np.ndarray, X: np.ndarray) -> np.ndarray:
    z = coefs[..., :1] + coefs[..., 1:] @ X.T
    return 1 / (1 + np.exp(-z))


# ---------------- public ----------------
def predict(material, thickness_mm, o2_pct, flow_cm_s) -> dict:
    m = fitted()
    mc = material_class(material, thickness_mm)
    if thickness_mm is None or np.isnan(thickness_mm):
        thickness_mm = class_thickness()[mc]
    X = features(o2_pct, flow_cm_s, thickness_mm, mc)
    p = float(_prob(m["point"], X)[0])
    boot = _prob(m["draws"], X)[:, 0]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"p_burn": p, "low": float(lo), "high": float(hi)}


def _o2_at_half(coefs: np.ndarray, flow: np.ndarray, thickness: float, mc: str) -> np.ndarray:
    """O2 where logit = 0. coefs: (k, p+1). Returns (k, len(flow)); NaN if O2 slope <= 0."""
    X = features(np.zeros_like(flow), flow, np.full_like(flow, thickness), np.full(len(flow), mc))
    rest = coefs[:, :1] + coefs[:, 1:] @ X.T          # logit with O2 = 0
    slope = coefs[:, 1:2]
    out = -rest / slope
    out[(slope <= 0).ravel()] = np.nan
    return out


def boundary(material, flows=None) -> pd.DataFrame:
    m = fitted()
    mc = material_class(material)
    thk = class_thickness()[mc]
    flows = np.geomspace(0.2, 40, 60) if flows is None else np.asarray(flows, float)
    point = _o2_at_half(m["point"][None, :], flows, thk, mc)[0]
    boot = _o2_at_half(m["draws"], flows, thk, mc)
    lo, hi = np.nanpercentile(boot, [2.5, 97.5], axis=0)
    return pd.DataFrame({"flow_cm_s": flows, "o2_min": point, "low": lo, "high": hi})


def is_extrapolation(o2_pct: float) -> bool:
    return not (TESTED_O2_RANGE[0] <= o2_pct <= TESTED_O2_RANGE[1])
