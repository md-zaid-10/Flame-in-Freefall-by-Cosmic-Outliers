"""Grounding verification - Layer 3 of the accuracy design.

Two mechanical checks, neither of which trusts the language model.

1. verify_numbers()
   Every number in a generated answer must appear verbatim in one of the
   retrieved chunks. A number that is not in the sources is a fabrication,
   and this catches it without asking the model to self-report.

   Equivalent forms are accepted (1,250 == 1250, 0.21 == .21, 21% == 21 %)
   because those are formatting, not different values. Everything else is
   reported as unsupported, with the answer's own sentence for context.

2. verify_citations()
   Every citation in an answer must point at a chunk that was actually
   retrieved for that question, so a plausible-looking reference to a real
   NASA document cannot be invented.

Both are used by rag/answer.py before an answer is shown, and by rag/eval.py
to score the gold set.

Run:  python -m rag.verify            # self-test on worked examples
"""
from __future__ import annotations

import re
import sys

# Numbers worth checking. Deliberately excludes bare 1-2 digit integers used
# as ordinals ("the 3 experiments"), which carry no measurement risk, unless
# they are attached to a unit.
NUM = re.compile(r"""
    (?<![\w.])                      # not mid-token
    (
        \d{1,3}(?:,\d{3})+(?:\.\d+)?   # 1,250 / 12,500.5
      | \d+\.\d+                        # 0.21 / 4.3
      | \.\d+                           # .21
      | \d+                             # 21
    )
    \s*
    (%|percent|psi|kPa|atm|bar|cm/s|mm/s|m/s|mm|cm|mol|vol|
     ms|min|hr|Hz|kW|mg|kg|°C|°F|K|C|F|W|m|s)?   # optional unit
    # Bare "g" is excluded on purpose: in this domain it means gravity
    # ("1/3 g", "micro-g"), not grams, and mg/kg are listed above.
    (?![A-Za-z/])                   # the unit must not be the start of a word
""", re.X | re.I)

UNIT_ALIASES = {
    "percent": "%", "°c": "c", "°f": "f", "vol": "", "mol": "",
}


def _canon_number(raw: str) -> str:
    """Canonical numeric string so 1,250 / 1250 / 1250.0 compare equal."""
    s = raw.replace(",", "").strip()
    if s.startswith("."):
        s = "0" + s
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f == int(f) else repr(f)


def extract_numbers(text: str):
    """Return [(canonical_value, unit, surface_form, position)]."""
    out = []
    for m in NUM.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        unit = UNIT_ALIASES.get(unit, unit)
        # Skip bare small integers with no unit - "the 3 investigations".
        if not unit and re.fullmatch(r"\d{1,2}", raw):
            continue
        out.append((_canon_number(raw), unit, m.group(0).strip(), m.start()))
    return out


def _sentence_at(text: str, pos: int) -> str:
    start = max(text.rfind(".", 0, pos), text.rfind("\n", 0, pos)) + 1
    end = text.find(".", pos)
    end = len(text) if end == -1 else end + 1
    return text[start:end].strip()


def verify_numbers(answer: str, chunks):
    """Check every number in `answer` against the text of `chunks`.

    Returns a dict with a verdict and the unsupported numbers, each with the
    sentence it came from so a reviewer can see what was claimed.
    """
    source_text = "\n".join(c["text"] for c in chunks)
    source_nums = {(v, u) for v, u, _, _ in extract_numbers(source_text)}
    # Values present with any unit, for the looser "value matches but unit
    # differs" case, which we report separately rather than silently accept.
    source_vals = {v for v, _ in source_nums}

    supported, unsupported, unit_mismatch = [], [], []
    for v, u, surface, pos in extract_numbers(answer):
        if (v, u) in source_nums or (v, "") in source_nums:
            supported.append(surface)
        elif v in source_vals:
            unit_mismatch.append({"value": surface,
                                  "sentence": _sentence_at(answer, pos)})
        else:
            unsupported.append({"value": surface,
                                "sentence": _sentence_at(answer, pos)})

    total = len(supported) + len(unsupported) + len(unit_mismatch)
    return {
        "numbers_checked": total,
        "supported": len(supported),
        "unsupported": unsupported,
        "unit_mismatch": unit_mismatch,
        "grounded": not unsupported and not unit_mismatch,
        "rate": round(len(supported) / total, 3) if total else 1.0,
    }


# Whole bracket contents. Acronyms in this corpus contain spaces, slashes and
# hyphens ("ACME BRE", "DAFT / DAFT-2"), so the label is not a single token.
CITATION = re.compile(r"\[([^\]\n]{1,60})\]")


def _norm_label(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def verify_citations(answer: str, chunks):
    """Every [CITATION] must name an investigation that was retrieved.

    Matching is on normalised labels, and a citation counts as valid if it
    names an allowed label or an allowed label names it - so "[ACME]" is
    accepted for "ACME BRE", and "[ACME BRE, p.20]" is accepted too.

    Note the limit of this check: it proves a citation points at something
    that was actually retrieved. It cannot prove the cited source is the one
    that supports the sentence. Wrong attribution between two retrieved
    investigations is caught by review, not by this function.
    """
    allowed = set()
    for c in chunks:
        allowed.add(_norm_label(c["accession"]))
        if c.get("acronym"):
            allowed.add(_norm_label(c["acronym"]))
        for a in c.get("also_in") or []:
            allowed.add(_norm_label(a))
    allowed.discard("")

    cited, invalid = [], []
    for m in CITATION.finditer(answer):
        raw = m.group(1).strip()
        # Drop trailing locators: "ACME BRE, p.20" -> "ACME BRE"
        label = _norm_label(re.split(r"[,;]", raw)[0])
        if not label:
            continue
        if any(label == a or label.startswith(a + " ") or a.startswith(label + " ")
               for a in allowed):
            cited.append(raw)
        else:
            invalid.append(raw)
    return {
        "citations_found": len(cited) + len(invalid),
        "valid": sorted(set(cited)),
        "invalid": sorted(set(invalid)),
        "all_valid": not invalid,
    }


def enforce(answer: str, chunks):
    """Run both checks and return (verdict, report).

    verdict is one of:
      pass            safe to show
      flag            show with warnings attached
      block           do not show; numbers or citations are fabricated
    """
    nums = verify_numbers(answer, chunks)
    cites = verify_citations(answer, chunks)
    if nums["unsupported"] or cites["invalid"]:
        verdict = "block"
    elif nums["unit_mismatch"]:
        verdict = "flag"
    else:
        verdict = "pass"
    return verdict, {"numbers": nums, "citations": cites}


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def _selftest():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    chunks = [{
        "accession": "PSI-26", "acronym": "BASS", "also_in": [],
        "text": ("Flames burning in air at 0.21 nominal oxygen mole fraction "
                 "self-extinguished. Tests used a flow velocity of 5 cm/s and "
                 "an ambient pressure of 10.2 psi. 1,250 frames were recorded."),
    }]

    cases = [
        ("grounded answer",
         "At 0.21 oxygen mole fraction flames self-extinguished [BASS].",
         "pass"),
        ("equivalent formatting (1250 vs 1,250)",
         "The run captured 1250 frames [PSI-26].",
         "pass"),
        ("hallucinated number",
         "Flames persisted at 0.35 oxygen mole fraction [BASS].",
         "block"),
        ("real value, wrong unit",
         "Ambient pressure was 10.2 kPa [BASS].",
         "flag"),
        ("invented citation",
         "Flow velocity was 5 cm/s [SAFFIRE-IV].",
         "block"),
        ("bare small integer is ignored",
         "There were 3 configurations [BASS].",
         "pass"),
    ]

    failures = 0
    for name, answer, expected in cases:
        verdict, rep = enforce(answer, chunks)
        ok = verdict == expected
        failures += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {name:38} -> {verdict:6} "
              f"(expected {expected})")
        if not ok:
            print(f"        {rep}")

    print()
    print("MINI-GOAL 3 (number + citation grounding):",
          "PASS" if not failures else f"FAIL ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_selftest())
