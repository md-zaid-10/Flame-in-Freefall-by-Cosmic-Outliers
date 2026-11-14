"""FlameScope flammability model: agreed interface (owner: Zaid).

Signatures and return shapes are the team contract; change only with team agreement.
Internals: ml/microgravity/flammability.py (empirical BASS-II envelope for PMMA rods).
NaN results mean "no data", not "safe": show them as "insufficient data" in the UI.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from microgravity import flammability as _f  # noqa: E402

TESTED_O2_RANGE = _f.TESTED_O2_RANGE
is_extrapolation = _f.is_extrapolation  # True outside 13.6-22.2 % O2: label it in the UI
is_supported = _f.is_supported          # only PMMA rods for now
limiting_o2 = _f.limiting_o2            # {"o2", "low", "high", "evidence"}
envelope = _f.envelope                  # table of burn fraction per O2 x flow cell


def predict(material: str, thickness_mm: float, o2_pct: float, flow_cm_s: float,
            pressure_kpa: float = 101.3, gravity_g: float = 0.0) -> dict:
    """Observed burn fraction with 95 % interval: {"p_burn", "low", "high"} (NaN = no data).

    pressure_kpa and gravity_g are accepted for the contract but not modeled: BASS-II is
    microgravity at ISS cabin pressure only. Partial-g bounds live in ml/gravity_bounds.
    """
    return _f.predict(material, thickness_mm, o2_pct, flow_cm_s)


def boundary(material: str, gravity_g: float = 0.0) -> pd.DataFrame:
    """Limiting-O2 boundary: flow_cm_s, o2_min, low, high. NaN where not determined.
    df.attrs["status"] / ["evidence"] explain the result."""
    return _f.boundary(material)
