"""Pre-compute everything the demo screens show, so they render instantly.

Writes frontend/data/demo.js (window.DEMO = {...}). Every figure in it is read
from the backend or the repo's data files; nothing is typed in by hand.

    venv/bin/python frontend/build_cache.py
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, os.path.join(ROOT, "ml"), HERE]

from rag import search as rag  # noqa: E402
import model  # noqa: E402
from gravity_bounds import baselines  # noqa: E402
from microgravity import flammability as flam  # noqa: E402
from shape import shape  # noqa: E402

# The three demo beats. `headline_quote` must appear verbatim in a returned
# NASA passage; the build fails otherwise, so the headline cannot drift.
PRESETS = [
    {"id": "smoke", "kind": "quote",
     "question": "Can a smoke detector built for Earth work in space?",
     "headline_quote": "Smoke detector design must be based on low-g data"},
    {"id": "oxygen", "kind": "measured",
     "question": "How little oxygen does a fire need in space?"},
    {"id": "moon", "kind": "refusal",
     "question": "How does fire behave on the Moon?"},
]


# Extra questions answered from the cache, so the public static site can answer
# them without the AI server. Each must behave as expected at build time
# ("answer": a checked AI answer and no Moon/Mars gap; "no_data": a Moon/Mars
# gap) or it is left out.
EXAMPLES = [
    ("Why are smoke particles bigger in space?", "answer"),
    ("What size droplets were burned in FLEX?", "answer"),
    ("Is CO2 or helium better at putting out fires in space?", "answer"),
    ("Which spacecraft materials did not burn on the ISS?", "answer"),
    ("How do flames spread differently in microgravity?", "answer"),
    ("What did the Saffire mission burn?", "answer"),
    ("How do you put out a fire in space?", "answer"),
    ("Would a fire on a Moon base behave like one on the ISS?", "no_data"),
    ("Is a 30% oxygen atmosphere safe for a lunar habitat?", "no_data"),
    ("Does fire spread faster on Mars?", "no_data"),
    ("Does microgravity data apply to Mars habitats?", "no_data"),
    ("What fire risks does a Moon mission face?", "no_data"),
]


def norm(s):
    return " ".join((s or "").split())


def find_quote(ans, quote):
    for e in ans["evidence"]:
        if quote.lower() in norm(e["text"]).lower():
            return {"text": quote, "acronym": e["acronym"], "investigation": e["investigation"],
                    "doi": e.get("doi"), "file": e["file"], "page": e.get("page")}
    raise SystemExit(f"headline quote not found verbatim in sources: {quote!r}")


def ml_block():
    lim = flam.limiting_o2()
    d = flam.load_training()
    rod = baselines.PMMA_ROD
    hab = baselines.HABITAT
    meta = json.load(open(os.path.join(ROOT, "data", "metadata.json"), encoding="utf-8"))
    return {
        "material": "acrylic (PMMA) rod",
        "limit": {k: lim[k] for k in ("o2", "low", "high", "evidence")},
        "burn_window_cm_s": list(flam.BURN_WINDOW),
        "earth_bracket": {"low": rod["normal_gravity_bracket"]["low"],
                          "high": rod["normal_gravity_bracket"]["high"],
                          "quote": rod["normal_gravity_bracket"]["quote"],
                          "source": rod["normal_gravity_bracket"]["source"]},
        "runs": int(len(d)),
        "outcomes": {k: int(v) for k, v in d["outcome"].value_counts().items()},
        "o2_tested": [float(d["o2_pct"].min()), float(d["o2_pct"].max())],
        "flow_tested": [float(d["flow_cm_s"].min()), float(d["flow_cm_s"].max())],
        "habitat": {k: hab[k] for k in ("earth_air_o2", "moon_base_o2_min",
                                        "moon_base_pressure_psi_max", "source")},
        "references": list(baselines.REFERENCES),
        "source": {"acronym": "BASS-II", "investigation": "PSI-25",
                   "doi": meta.get("PSI-25", {}).get("doi")},
    }


# The map's controls. predict() is evaluated on every slider position here so
# the browser shows model output, never a re-implementation of the model.
MAP_O2 = [round(10 + 0.1 * i, 1) for i in range(251)]          # 10.0 .. 35.0
MAP_FLOWS = [0.5, 1, 1.5, 2, 3, 5, 7, 10, 15, 20, 30]


def _num(x, nd=3):
    return None if x is None or x != x else round(float(x), nd)    # NaN -> None


def map_block():
    d = flam.load_training()
    grid = {}
    for f in MAP_FLOWS:
        row = []
        for o in MAP_O2:
            r = model.predict("pmma_rod", None, o, f)
            row.append(None if r["p_burn"] != r["p_burn"]
                       else [_num(r["p_burn"]), _num(r["low"]), _num(r["high"])])
        grid[str(f)] = row
    env = flam.envelope()
    return {
        "points": [{"run": r.run_id, "o2": float(r.o2_pct), "flow": float(r.flow_cm_s),
                    "outcome": r.outcome, "burn": int(r.y)} for r in d.itertuples()],
        "o2_values": MAP_O2, "flows": MAP_FLOWS, "predict": grid,
        "envelope": [{"o2_band": str(r.o2_band), "flow_band": str(r.flow_band),
                      "runs": _num(r.n, 0), "burning_runs": _num(r.k, 2),
                      "p_burn": _num(r.p_burn), "low": _num(r.low), "high": _num(r.high)}
                     for r in env.itertuples()],
        "tested_o2": list(model.TESTED_O2_RANGE),
    }


def method_block():
    import pandas as pd
    table = pd.read_csv(os.path.join(ROOT, "data", "raw", "tables", "PSI-25",
                                     "PSI-25_Experimental table_BASS-II.csv"), encoding="utf-8-sig")
    labels = pd.read_csv(os.path.join(ROOT, "ml", "microgravity", "bass2_labels.csv"))
    check = pd.read_csv(os.path.join(ROOT, "ml", "microgravity", "handcheck_results.csv"))
    stats = json.load(open(os.path.join(ROOT, "data", "rag", "corpus_stats.json")))
    meta = json.load(open(os.path.join(ROOT, "data", "metadata.json"), encoding="utf-8"))
    rod_runs = flam.load_training()["run_id"].nunique()
    inv = []
    for acc, dep in stats["evidence_depth"].items():
        m = meta.get(acc, {})
        inv.append({"id": acc, "acronym": dep.get("acronym") or m.get("investigationAcronym") or "",
                    "title": m.get("title") or dep.get("title") or acc,
                    "doi": m.get("doi") or "", "evidence_level": dep.get("evidence_level")})
    inv.sort(key=lambda r: int(r["id"].split("-")[1]))
    return {
        "bass2_runs": int(len(table)),
        "label_steps": int(len(labels)),
        "rod_runs": int(rod_runs),
        "recheck": {"n": int(len(check)),
                    "agree": round(float((check["hand_outcome"] == check["outcome"]).mean()), 3)},
        "investigations": inv,
    }


# ---------------- research map ----------------
# Grouping by subject (what each study investigated, from its PSI title and
# objective), never by how much it published. Every corpus investigation must
# appear exactly once; the build fails otherwise.
CATEGORIES = [
    {"id": "flammability", "title": "Material flammability",
     "blurb": "How cabin materials ignite, spread flame and go out.",
     "ids": ["PSI-25", "PSI-26", "PSI-98", "PSI-99", "PSI-100"]},
    {"id": "detection", "title": "Fire & smoke detection",
     "blurb": "What smoke looks like in low gravity, so alarms can see it.",
     "ids": ["PSI-102", "PSI-101", "PSI-47", "PSI-115"]},
    {"id": "suppression", "title": "Suppression & extinction",
     "blurb": "What puts flames out, and when they go out on their own.",
     "ids": ["PSI-69", "PSI-68", "PSI-117"]},
    {"id": "physics", "title": "Flame physics",
     "blurb": "How flames, soot and fuel droplets behave without gravity.",
     "ids": ["PSI-10", "PSI-20", "PSI-22", "PSI-23", "PSI-159", "PSI-39", "PSI-107"]},
]

# One ranking per habitat, from rag.search() (best-passage score, not volume).
HABITATS = [
    {"id": "all", "label": "All habitats",
     "query": "fire safety for crewed spacecraft, space stations and surface habitats"},
    {"id": "spacecraft", "label": "Spacecraft",
     "query": "fire safety in a crewed spacecraft cabin: material flammability, smoke detection, fire suppression"},
    {"id": "station", "label": "Space station",
     "query": "fire safety on the International Space Station: flammability, smoke detection, extinguishing fires"},
    {"id": "surface", "label": "Moon or Mars base",
     "query": "fire safety for lunar and Martian surface habitats: oxygen-enriched atmosphere, reduced pressure, material flammability",
     "note": "No PSI study ran at Moon or Mars gravity. These are the closest microgravity studies; their results may not carry over."},
    {"id": "rover", "label": "Pressurized rover",
     "query": "fire safety in a small pressurized crew vehicle cabin: enriched oxygen, low pressure, ventilation flow, material flammability",
     "note": "PSI has no rover-specific study. These are the closest small-cabin fire studies."},
]

# Earth applications. Each quote must appear verbatim in the named source
# (metadata field or corpus passage); the build fails otherwise.
EARTH = [
    {"title": "Smoke detectors for extreme places on Earth", "id": "PSI-102",
     "quote": "The smoke detectors developed from the results of SAME can also be useful in other extreme environments on Earth, such as submarines or underwater laboratories.",
     "from": "metadata:researchImpacts"},
    {"title": "Fire models for detection and suppression on Earth", "id": "PSI-25",
     "quote": "BASS-II results contribute to the combustion computational models used in the design of fire detection and suppression systems in microgravity and on Earth.",
     "from": "metadata:objective"},
    {"title": "Water-mist fire suppression", "id": "PSI-20",
     "quote": "a space experiment that focused on measuring the extinguishing capability of water mist on a premixed flame propagating along a tube to gain a better understanding of the water mist fire suppression phenomenon",
     "from": "corpus", "context": "Cited in NASA's ISS researchers' guide to combustion. The challenge statement notes that fine-water-mist extinguishers developed for the ISS have practical uses on Earth."},
    {"title": "Firefighter gear", "id": None, "quote": None, "from": None,
     "context": "The challenge statement notes that NASA technology improved firefighter protective clothing and air tanks. None of the PSI combustion studies covers this, so FlameScope has no NASA data to show here."},
]


def _first_sentence(text, max_len=260):
    t = " ".join((text or "").split())
    if not t:
        return ""
    # Skip fragments like "The objectives are: A." by requiring 60+ characters.
    end = t.find(". ", 60)
    if 0 < end < max_len:
        return t[:end + 1]
    return t if len(t) <= max_len else t[:max_len].rsplit(" ", 1)[0] + "…"


def research_block():
    stats = json.load(open(os.path.join(ROOT, "data", "rag", "corpus_stats.json")))
    meta = json.load(open(os.path.join(ROOT, "data", "metadata.json"), encoding="utf-8"))
    corpus_ids = set(stats["evidence_depth"])
    listed = [i for c in CATEGORIES for i in c["ids"]]
    if sorted(listed) != sorted(corpus_ids) or len(listed) != len(set(listed)):
        raise SystemExit(f"research categories must list each corpus investigation once: "
                         f"missing {sorted(corpus_ids - set(listed))}, extra {sorted(set(listed) - corpus_ids)}")

    studies = {}
    for acc in listed:
        m, dep = meta.get(acc, {}), stats["evidence_depth"][acc]
        studies[acc] = {
            "id": acc, "acronym": dep.get("acronym") or m.get("investigationAcronym") or "",
            "title": m.get("title") or acc, "doi": m.get("doi") or "",
            "evidence_level": dep.get("evidence_level"),
            "objective": _first_sentence(m.get("objective")),
            "impact": _first_sentence(m.get("researchImpacts")),
        }

    rankings = {}
    for h in HABITATS:
        hits = rag.search(h["query"], k=len(listed))
        rankings[h["id"]] = [{"id": x["id"], "score": x["score"]} for x in hits if x["id"] in studies]

    chunks = [json.loads(l)["text"] for l in open(os.path.join(ROOT, "data", "rag", "chunks.jsonl"), encoding="utf-8")]
    norm = lambda s: " ".join((s or "").split())
    earth = []
    for e in EARTH:
        if e["quote"]:
            if e["from"].startswith("metadata:"):
                src = norm(meta[e["id"]].get(e["from"].split(":")[1]))
            else:
                src = next((norm(t) for t in chunks if e["quote"] in norm(t)), "")
            if e["quote"] not in src:
                raise SystemExit(f"Earth quote not found verbatim for {e['id']}: {e['quote'][:60]}")
        earth.append({k: e.get(k) for k in ("title", "id", "quote", "context")} |
                     {"acronym": studies[e["id"]]["acronym"] if e["id"] else None,
                      "doi": studies[e["id"]]["doi"] if e["id"] else None})

    return {"categories": CATEGORIES, "habitats": HABITATS, "studies": studies,
            "rankings": rankings, "earth": earth}


# Screens that never display an AI answer: measured data (oxygen), the Moon
# refusal, and Moon/Mars example questions (no AI summary by rule). Their AI
# draft is not stored, so an unchecked sentence can't sit in the public cache.
UNSHOWN_PRESET_KINDS = ("measured", "refusal")


def keep_tie_order(research, prev_rankings):
    """rag.search sorts by score only, so studies with equal scores (e.g.
    Saffire-II and -III) come out in a different order from one run to the
    next. With --keep-answers, keep the published order when a habitat's
    ranking has exactly the same studies and scores; any real change is used
    as-is and reported."""
    for h, new in research["rankings"].items():
        old = prev_rankings.get(h)
        if old is None or old == new:
            continue
        key = lambda r: sorted((x["id"], x["score"]) for x in r)
        if key(old) == key(new) and [x["score"] for x in old] == [x["score"] for x in new]:
            print(f"research ranking {h!r}: tied scores, keeping the published order")
            research["rankings"][h] = old
        else:
            print(f"research ranking {h!r}: CHANGED (scores differ from the published cache)")
    return research


def drop_unshown_answer(ans):
    g = ans.get("grounding") or {}
    ans["answer"] = None
    ans["grounding"] = {
        "verdict": "not_shown",
        "backend": g.get("backend"),
        "model": g.get("model"),
        "note": "AI answer not stored: this screen never displays one.",
    }
    return ans


def main():
    if not rag.available():
        raise SystemExit("RAG corpus not built (data/rag/chunks.jsonl missing).")
    stats = json.load(open(os.path.join(ROOT, "data", "rag", "corpus_stats.json")))
    files = json.load(open(os.path.join(HERE, "data", "psi_file_count.json")))
    ml = ml_block()

    # --keep-answers reuses the answers already in demo.js, so a rebuild for
    # other data does not regenerate (and possibly change) the AI summaries.
    kept, prev_rankings = {}, {}
    if "--keep-answers" in sys.argv:
        prev = open(os.path.join(HERE, "data", "demo.js"), encoding="utf-8").read()
        prev = json.loads(prev[prev.index("=") + 1:].rstrip().rstrip(";"))
        kept = {p["question"]: p["ask"] for p in prev["presets"]}
        kept |= {e["question"]: e["ask"] for e in prev.get("examples", [])}
        prev_rankings = prev.get("research", {}).get("rankings", {})

    presets = []
    for p in PRESETS:
        if p["question"] in kept:
            print("keeping:", p["question"], flush=True)
            ans = kept[p["question"]]
        else:
            print("asking:", p["question"], flush=True)
            ans = shape(rag.ask(p["question"]))
        item = {k: v for k, v in p.items() if k != "headline_quote"}
        item["ask"] = ans
        if p["kind"] == "quote":
            item["headline"] = find_quote(ans, p["headline_quote"])
        if p["kind"] == "refusal":
            hard = [g for g in ans["gaps"] if g["kind"] == "partial_gravity"
                    and g["severity"] == "hard"]
            if not hard:
                raise SystemExit(f"expected a hard partial-gravity gap for {p['question']!r}")
        if p["kind"] in UNSHOWN_PRESET_KINDS:
            drop_unshown_answer(ans)
        presets.append(item)

    examples = []
    for q, expect in EXAMPLES:
        ans, why = kept.get(q), "kept"
        for attempt in range(3):          # answers vary run to run; retry a little
            if ans is None:
                print("asking:", q, flush=True)
                ans = shape(rag.ask(q))
            moon = any(g["kind"] == "partial_gravity" for g in ans["gaps"])
            ok = moon if expect == "no_data" else (
                not moon and bool(ans["answer"]) and ans["grounding"]["verdict"] == "pass")
            if ok:
                break
            why, ans = f"attempt {attempt + 1} did not behave as expected", None
        if ans is None:
            print(f"  SKIPPED (did not behave as expected 3 times): {q}")
            continue
        if expect == "no_data":
            drop_unshown_answer(ans)
        examples.append({"question": q, "expect": expect, "ask": ans})

    out = {
        "built": datetime.datetime.now().isoformat(timespec="minutes"),
        "files": {k: files[k] for k in ("total", "investigations", "counted_on", "method")},
        "corpus": {"investigations": stats["investigations"], "passages": stats["chunks"],
                   "condition_rows": stats["condition_rows"]},
        "ml": ml,
        # Derived, shown on the Moon screen: how far past NASA's tested range a
        # Moon base would sit.
        "moon_gap_points": round(ml["habitat"]["moon_base_o2_min"] - ml["o2_tested"][1], 1),
        "presets": presets,
        "examples": examples,
        "map": map_block(),
        "method": method_block(),
        "research": keep_tie_order(research_block(), prev_rankings),
    }
    path = os.path.join(HERE, "data", "demo.js")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("// Generated by frontend/build_cache.py - do not edit.\n")
        fh.write("window.DEMO = " + json.dumps(out, ensure_ascii=False, indent=1) + ";\n")
    print("wrote", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
