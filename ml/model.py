"""FlameScope flammability model: agreed interface (owner: Zaid).

Signatures and return shapes are the team contract; change only with team agreement.
Internals: ml/microgravity/flammability.py (BASS-II logistic model + run bootstrap).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from microgravity import flammability as _f  # noqa: E402

TESTED_O2_RANGE = _f.TESTED_O2_RANGE
is_extrapolation = _f.is_extrapolation  # use in the UI to label O2 outside 13.6-22.2 %


def predict(material: str, thickness_mm: float, o2_pct: float, flow_cm_s: float,
            pressure_kpa: float = 101.3, gravity_g: float = 0.0) -> dict:
    """P(material keeps burning) with a 95 % bootstrap band: {"p_burn", "low", "high"}.

    pressure_kpa and gravity_g are accepted for the contract but not modeled: BASS-II is
    microgravity at ISS cabin pressure only. Partial-g bounds live in ml/gravity_bounds.
    """
    return _f.predict(material, thickness_mm, o2_pct, flow_cm_s)


def boundary(material: str, gravity_g: float = 0.0) -> pd.DataFrame:
    """Extinction boundary: columns flow_cm_s, o2_min, low, high (95 % band)."""
    return _f.boundary(material)
