"""Query decomposition and gap detection - Layer 1 of the accuracy design.

A compound question retrieved as one vector answers whichever half dominates
the embedding, and the user never learns the other half was dropped. So we
split the question into atomic sub-questions, retrieve for each separately,
and report coverage per part.

This is rule-based on purpose: it runs with no API key, is deterministic, and
is therefore testable in the eval set. An LLM splitter can replace split()
later without changing the interface.

It also carries the scope guard. The challenge brief states that PSI holds no
partial-gravity combustion data, and our own corpus scan confirms every flight
investigation is microgravity. So a question about Moon or Mars gravity must
never be answered from microgravity evidence - detect_scope_gaps() marks it,
and the answer layer refuses to extrapolate.

Run:  python -m rag.decompose            # self-test
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Conjunctions that usually join two independent asks.
SPLIT_RE = re.compile(
    r"\s*(?:\band\s+(?:also\s+)?(?:what|which|how|where|why|whether|do|does|did|is|are|can)\b"
    r"|\band\s+what\b|\balso,?\s+(?:what|which|how)\b"
    r"|;|\?\s+|\bas well as\b)\s*", re.I)

# A question with several coordinated noun phrases ("oxygen, pressure and flow")
# is one ask, not three - we only split on clause-level conjunctions above.

MIN_PART_WORDS = 3

# Conditions PSI does not cover. Phrases are matched case-insensitively.
PARTIAL_GRAVITY = [
    "moon", "lunar", "mars", "martian", "partial gravity", "partial-gravity",
    "1/6 g", "1/6g", "one sixth gravity", "1/3 g", "1/3g", "one third gravity",
    "reduced gravity habitat", "lunar habitat", "mars habitat",
]
# Microgravity terms, used to tell "what happens in microgravity" apart from
# "what happens on the Moon".
MICROGRAVITY = ["microgravity", "micro-gravity", "iss", "orbit", "orbital", "zero gravity",
                "zero-g", "weightless", "spaceflight", "space station"]
# The softer warning is only for questions about whether microgravity data
# carries over ("does it apply to Mars?"). Merely mentioning the ISS
# ("would a Moon fire behave like one on the ISS?") still asks how fire
# behaves on the Moon, which PSI cannot answer.
APPLICABILITY = re.compile(
    r"\b(appl(?:y|ies|ied|icable|icability)|extrapolat\w*|transfer\w*|"
    r"valid\w*|relevan\w*|generali[sz]\w*|carr(?:y|ies) over)\b")


def _mentions(terms, low: str):
    """Terms that occur as whole words, so "iss" does not match "mission"
    and "mars" does not match "Marshall"."""
    return [t for t in terms
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)]


def split(question: str):
    """Split a compound question into atomic sub-questions."""
    q = question.strip()
    raw = [p.strip(" ,;?") for p in SPLIT_RE.split(q) if p and p.strip(" ,;?")]
    parts = [p for p in raw if len(p.split()) >= MIN_PART_WORDS]
    if len(parts) <= 1:
        return [q]

    # Re-attach the interrogative to fragments that lost it in the split, so
    # each part still reads as a question for the retriever.
    lead = re.match(r"^\s*(what|which|how|where|why|whether|do|does|did|is|are|can)\b",
                    q, re.I)
    out = []
    for p in parts:
        if lead and not re.match(
                r"^\s*(what|which|how|where|why|whether|do|does|did|is|are|can)\b",
                p, re.I):
            p = f"{lead.group(1)} {p}"
        out.append(p[0].upper() + p[1:] if p else p)
    return out


def detect_scope_gaps(question: str):
    """Flag parts of a question that PSI cannot answer in principle."""
    low = question.lower()
    gaps = []
    hits = _mentions(PARTIAL_GRAVITY, low)
    if hits:
        asks_extrapolation = bool(_mentions(MICROGRAVITY, low)) and bool(APPLICABILITY.search(low))
        gaps.append({
            "kind": "partial_gravity",
            "triggered_by": hits,
            "severity": "soft" if asks_extrapolation else "hard",
            "message": (
                "PSI contains no partial-gravity combustion data. Every flight "
                "investigation in this corpus is microgravity (ISS, Cygnus, "
                "Shuttle). Microgravity results do not predict combustion at "
                "lunar (~1/6 g) or Martian (~1/3 g) gravity, where buoyancy is "
                "reduced but not absent. Evidence below describes microgravity "
                "only and must not be extrapolated."),
        })
    return gaps


def coverage(parts, per_part_results, min_chunks: int = 2):
    """Per-sub-question coverage, so nothing silently goes unanswered."""
    rows = []
    for part, results in zip(parts, per_part_results):
        invs = sorted({r["accession"] for r in results})
        levels = {r.get("evidence_level") for r in results}
        if len(results) >= min_chunks and levels - {"metadata_only"}:
            state = "answered"
        elif results:
            state = "weak"
        else:
            state = "no_evidence"
        rows.append({
            "sub_question": part, "state": state,
            "chunks": len(results), "investigations": invs,
        })
    answered = sum(r["state"] == "answered" for r in rows)
    return {
        "parts": rows,
        "answered": answered,
        "total": len(rows),
        "complete": answered == len(rows),
    }


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def _selftest():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    split_cases = [
        ("Which experiments studied fabric flammability at high oxygen?", 1),
        ("Which experiments burned solid fuels and what suppression agents worked?", 2),
        ("What is the smoke particle size; how was it measured?", 2),
        ("Compare oxygen, pressure and flow velocity across BASS and FLEX.", 1),
        ("Which experiments used PMMA and which used cotton fabric?", 2),
    ]
    gap_cases = [
        ("How does flame spread behave in a lunar habitat?", True, "hard"),
        ("What is known about flame spread in microgravity?", False, None),
        ("Does microgravity data apply to Mars habitats?", True, "soft"),
        ("Which experiments measured smoke particle size?", False, None),
        ("Would a fire on a Moon base behave like one on the ISS?", True, "hard"),
        ("How does flame spread in microgravity compared to the Moon?", True, "hard"),
        ("What fire risks does a Moon mission face?", True, "hard"),
        ("Are ISS results valid for a lunar base?", True, "soft"),
        ("Are there results from the Marshall flight center?", False, None),
    ]

    fails = 0
    print("query splitting")
    for q, expected in split_cases:
        parts = split(q)
        ok = len(parts) == expected
        fails += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {len(parts)} part(s) "
              f"(expected {expected}): {q[:58]}")
        if len(parts) > 1:
            for p in parts:
                print(f"         - {p}")

    print()
    print("scope-gap detection")
    for q, should_flag, severity in gap_cases:
        gaps = detect_scope_gaps(q)
        ok = bool(gaps) == should_flag and (
            not should_flag or gaps[0]["severity"] == severity)
        fails += not ok
        got = gaps[0]["severity"] if gaps else "none"
        print(f"  {'OK  ' if ok else 'FAIL'} flagged={bool(gaps)} "
              f"severity={got:5} (expected {should_flag}/{severity}): {q[:52]}")

    print()
    print("MINI-GOAL 4 (decomposition + scope guard):",
          "PASS" if not fails else f"FAIL ({fails})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest())
