"""Build the BASS-II (PSI-25) labeling sheet: one row per (run, airflow step).

Usage (from repo root):
    python ml/microgravity/build_labels.py

Writes:
    ml/microgravity/bass2_labels_auto.csv   always regenerated (machine labels)
    ml/microgravity/bass2_labels.csv        created ONLY if missing; this is the
                                            file you hand-edit. Never overwritten.

Rules (keep simple; ambiguous rows get needs_review=1):
- Flow steps come from "Air display" (cm/s). Parenthetical text and values tagged
  "pot" are fan-potentiometer settings, not cm/s, and are dropped.
- Every step before the last one = burn (flame survived; operators then changed flow).
- Last step: "blowoff" -> blowoff; "N ext" / "0ext" -> extinguish at N;
  "down to ext" / "off" / "out" / "lower" -> burn at last listed flow plus an extra
  extinguish row with unknown flow; "no ign" -> no_ignition; no marker -> blank (review).
- Fan display is also scanned for outcome words (some runs only note it there).

NOTE: Jaisheel owns the shared flow-string parser. This is a minimal local version so
labeling can start now; swap in his parser when it lands.
"""
from pathlib import Path
import re

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data/raw/tables/PSI-25/PSI-25_Experimental table_BASS-II.csv"
OUT_DIR = Path(__file__).resolve().parent
AUTO = OUT_DIR / "bass2_labels_auto.csv"
HAND = OUT_DIR / "bass2_labels.csv"

INCH_MM = 25.4
NUM = r"\d*\.?\d+"


# ---------- material normalization ----------
def parse_material(raw: str) -> dict:
    s = re.sub(r"\s+", " ", str(raw).lower()).strip()
    s = s.replace("2ide", "wide").replace("blac ", "black ")
    out = {"material": "other", "color": "", "thickness_mm": np.nan, "width_cm": np.nan}

    if "sibal" in s:
        out["material"] = "sibal"  # cotton-fiberglass fabric; thickness not given
    elif "nomex" in s:
        out["material"] = "nomex"
    elif "candle" in s:
        out["material"] = "candle"
    elif "spherical" in s:
        out["material"] = "spherical_section"
    elif "rod" in s:
        out["material"] = "pmma_rod"
        out["color"] = "black" if "black" in s else "clear"
        m = re.search(r"(\d+)\s*/\s*(\d+)", s) or re.search(r"(0?\.\d+)\s*\"", s)
        if m and m.lastindex == 2:
            out["thickness_mm"] = round(int(m[1]) / int(m[2]) * INCH_MM, 2)  # diameter
        elif m:
            out["thickness_mm"] = round(float(m[1]) * INCH_MM, 2)
    else:  # PMMA film or slab
        if m := re.search(rf"({NUM})\s*micron", s):
            t = float(m[1]) / 1000
        elif m := re.search(rf"({NUM})\s*mm", s):
            t = float(m[1])
        else:
            t = np.nan
        out["thickness_mm"] = t
        out["material"] = "pmma_film" if t <= 0.5 else "pmma_slab"
        if "2 sided" in s:
            out["material"] += "_2sided"

    if m := re.search(rf"({NUM})\s*cm(?:\s*wide)?", s):
        if out["material"] not in ("spherical_section",):
            out["width_cm"] = float(m[1])
    return out


# ---------- flow-step parsing ----------
def flow_steps(air: str) -> tuple[list[float], list[str]]:
    """Return (flows_cm_s, flags) from an Air display string."""
    flags = []
    s = str(air).lower() if pd.notna(air) else ""
    if not s:
        return [], ["no_air_value"]
    if m := re.search(rf"({NUM})\s*cm/s", s):  # explicit cm/s wins
        return [float(m[1])], flags
    s = re.sub(r"\(.*?(\)|$)", " ", s)              # drop (fan/pot values)
    s = re.sub(rf"{NUM}\s*pot\b", " ", s)            # "0.5 pot"
    s = re.split(r"\bpots?\b", s)[0]                 # "pots 0.4 0.36 ..."
    if re.search(r"[?~>]|etc|ibid|would not", s):
        flags.append("ambiguous_text")
    s = s.replace("<1", " 0.5 ")
    if "0.5" in s and "<1" in str(air):
        flags.append("lt1_as_0.5")
    s = re.sub(r"\bmax\b", " ", s)
    vals = [float(x) for x in re.findall(NUM, s)]
    if not vals:
        flags.append("no_numeric_flow")
    if any(v > 30 for v in vals):
        flags.append("gt30_maybe_fan_units")
    return vals, flags


def end_marker(fan: str, air: str) -> str:
    """Classify how the run ended from free text."""
    a = str(air).lower() if pd.notna(air) else ""
    f = str(fan).lower() if pd.notna(fan) else ""
    both = a + " | " + f
    if "no ign" in both:
        return "no_ignition"
    if "blowoff" in both:
        return "blowoff"
    if re.search(r"(to|decr to)\s*ext|\boff\b|\bout\b|\blower\b|\blow\b", a) or (
            re.search(r"\bpots?\b", a) and re.search(r"ext", a)):  # ext at a lower pot setting
        return "ext_below_last"
    if re.search(r"\d\s*ext|\bext\b|extinguished", a):
        return "ext_at_last"
    if re.search(r"\bext|extinguished|\bout\b", f):
        return "ext_unknown_flow"  # only fan says it; flow in pot units
    return ""


def build() -> pd.DataFrame:
    df = pd.read_csv(SRC, encoding="utf-8-sig")
    df.columns = df.columns.str.replace(r"\s+", " ", regex=True).str.strip()

    rows = []
    for _, r in df.iterrows():
        mat = parse_material(r["Fuel Sample Material"])
        o2 = pd.to_numeric(r["Calibrated initial O2 % by vol"], errors="coerce")
        fan, air = r["Fan display"], r["Air display"]
        flows, flags = flow_steps(air)
        end = end_marker(fan, air)
        base = {
            "run_id": r["Test #"], "pi": r["PI"], **mat, "o2_pct": o2,
            "o2_final_pct": pd.to_numeric(r["Calibrated final O2 % by vol"], errors="coerce"),
            "raw_material": r["Fuel Sample Material"], "raw_fan": fan, "raw_air": air,
        }

        def add(step, flow, outcome, conf, rule):
            review = int(conf == "low" or not outcome or bool(flags) or np.isnan(flow)
                         or (outcome == "burn" and flow == 0))
            rows.append({**base, "step": step, "flow_cm_s": flow, "outcome": outcome,
                         "confidence": conf, "needs_review": review,
                         "auto_rule": rule, "flags": ";".join(flags), "notes": ""})

        if end == "no_ignition":
            add(0, np.nan, "no_ignition", "high", "text:no ign")
            continue
        if not flows:
            add(0, np.nan, {"blowoff": "blowoff", "ext_unknown_flow": "extinguish"}.get(end, ""),
                "low", f"no flow parsed; end={end or 'none'}")
            continue

        for i, fl in enumerate(flows[:-1]):
            add(i, fl, "burn", "medium", "intermediate step -> burn")
        last = len(flows) - 1
        if end == "blowoff":
            rising = len(flows) == 1 or flows[-1] > flows[-2]
            if rising and "down" not in str(air).lower():
                add(last, flows[-1], "blowoff", "high", "text:blowoff")
            else:  # e.g. "5 down then blowoff": flow at blowoff unknown
                add(last, flows[-1], "burn", "medium", "last listed flow before blowoff")
                add(last + 1, np.nan, "blowoff", "low", "text:blowoff; flow unknown")
        elif end == "ext_at_last":
            add(last, flows[-1], "extinguish", "medium", "text:N ext")
        elif end in ("ext_below_last", "ext_unknown_flow"):
            add(last, flows[-1], "burn", "medium", "last listed flow before ext")
            add(last + 1, np.nan, "extinguish", "low", f"text:{end}; flow unknown")
        else:
            add(last, flows[-1], "", "low", "no end marker")

    cols = ["run_id", "step", "pi", "material", "color", "thickness_mm", "width_cm",
            "o2_pct", "flow_cm_s", "outcome", "confidence", "needs_review", "notes",
            "auto_rule", "flags", "o2_final_pct", "raw_material", "raw_fan", "raw_air"]
    return pd.DataFrame(rows)[cols]


if __name__ == "__main__":
    labels = build()
    labels.to_csv(AUTO, index=False)
    print(f"wrote {AUTO.relative_to(ROOT)}: {len(labels)} rows from "
          f"{labels.run_id.nunique()} runs")
    if HAND.exists():
        print(f"{HAND.name} exists: left untouched (your hand labels are safe)")
    else:
        labels.to_csv(HAND, index=False)
        print(f"created {HAND.relative_to(ROOT)}: hand-edit this one")
    print("\noutcomes:\n", labels.outcome.replace("", "(blank)").value_counts().to_string())
    print("\nneeds_review:", int(labels.needs_review.sum()))
    print("\nmaterials:\n", labels.drop_duplicates("run_id").material.value_counts().to_string())
