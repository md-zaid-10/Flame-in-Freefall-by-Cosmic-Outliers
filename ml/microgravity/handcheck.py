"""Blind hand-check of the LLM-assisted BASS-II labels -> validity metric.

1) python ml/microgravity/handcheck.py sample   # writes handcheck_blind.csv (30 rows)
2) Open handcheck_blind.csv, fill `hand_outcome` for every row using ONLY raw_fan/raw_air
   and the other run info. Allowed: burn, extinguish, blowoff, no_ignition, unknown.
   Do not look at bass2_labels.csv while doing this.
3) python ml/microgravity/handcheck.py score    # agreement, kappa, disagreements

The sample is stratified so rare outcomes (extinguish/blowoff) are not swamped by burns.
"""
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score

HERE = Path(__file__).resolve().parent
LABELS = HERE / "bass2_labels.csv"
BLIND = HERE / "handcheck_blind.csv"
KEY = HERE / "handcheck_key.csv"     # LLM answers for the sampled rows; don't open first
N = 30
SEED = 42
SHOW = ["check_id", "run_id", "step", "material", "thickness_mm", "o2_pct", "o2_final_pct",
        "flow_cm_s", "raw_fan", "raw_air"]


def sample():
    if BLIND.exists():
        sys.exit(f"{BLIND.name} exists; delete it to resample (you'd lose hand labels)")
    d = pd.read_csv(LABELS).reset_index(names="row")
    d = d[d["outcome"].notna()]
    d["stratum"] = d["outcome"].where(d["outcome"].isin(["extinguish", "blowoff"]), "other")
    want = {"extinguish": 8, "blowoff": 4}
    parts = [g.sample(min(len(g), want.get(k, 0)), random_state=SEED)
             for k, g in d.groupby("stratum") if k in want]
    taken = pd.concat(parts)
    rest = d.drop(taken.index).sample(N - len(taken), random_state=SEED)
    s = pd.concat([taken, rest]).sample(frac=1, random_state=SEED).reset_index(drop=True)
    s["check_id"] = range(1, len(s) + 1)
    s[SHOW].assign(hand_outcome="", hand_notes="").to_csv(BLIND, index=False)
    s[["check_id", "row", "run_id", "step", "outcome", "confidence"]].to_csv(KEY, index=False)
    print(f"wrote {BLIND.name} ({len(s)} rows). Fill hand_outcome, then run: score")


def score():
    h = pd.read_csv(BLIND)
    k = pd.read_csv(KEY)
    m = h.merge(k, on=["check_id", "run_id", "step"])
    m["hand_outcome"] = m["hand_outcome"].fillna("").str.strip().str.lower()
    m = m[m["hand_outcome"] != ""]
    if m.empty:
        sys.exit("no hand_outcome filled in yet")
    agree = (m["hand_outcome"] == m["outcome"])
    both_known = m[(m["hand_outcome"] != "unknown") & (m["outcome"] != "unknown")]
    print(f"rows checked: {len(m)}/{len(h)}")
    print(f"exact agreement: {agree.mean():.0%} ({agree.sum()}/{len(m)})")
    if len(both_known) and both_known["outcome"].nunique() > 1:
        acc = (both_known["hand_outcome"] == both_known["outcome"]).mean()
        kap = cohen_kappa_score(both_known["hand_outcome"], both_known["outcome"])
        print(f"where both gave a label: agreement {acc:.0%}, Cohen's kappa {kap:.2f} "
              f"(n={len(both_known)})")
    # burn vs not-burn is what the model uses
    bin_ = both_known.assign(h=both_known["hand_outcome"].eq("burn"),
                             l=both_known["outcome"].eq("burn"))
    if len(bin_):
        print(f"burn vs not-burn agreement: {(bin_['h'] == bin_['l']).mean():.0%}")
    print("\nconfusion (rows = hand, cols = LLM):")
    print(pd.crosstab(m["hand_outcome"], m["outcome"]).to_string())
    dis = m[~agree][["check_id", "run_id", "step", "hand_outcome", "outcome", "confidence",
                     "hand_notes"]]
    if len(dis):
        print("\ndisagreements:"); print(dis.to_string(index=False))
    out = HERE / "handcheck_results.csv"
    m.to_csv(out, index=False)
    print(f"\nsaved {out.name}")


if __name__ == "__main__":
    {"sample": sample, "score": score}.get(sys.argv[1] if len(sys.argv) > 1 else "",
                                           lambda: sys.exit(__doc__))()
