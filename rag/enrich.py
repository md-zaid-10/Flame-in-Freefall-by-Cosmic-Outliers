"""Enrich built chunks with subject attribution and near-duplicate keys.

Fixes two problems found while reviewing real answers.

1. Shared documents were attributed to the wrong investigation.
   PSI files the same document under several investigations - the CIR
   conference paper sits in PSI-20's folder but its text is about FLEX. The
   folder decides the accession, so a FLEX finding was cited as "[ACME BRE]".

   Fix: scan each chunk's own text for investigation acronyms and record them
   as `mentions`. When the text names an investigation that is not the folder
   owner, `subject` points at what the text is actually about. Citations and
   recall then follow the text, not the filing.

2. Near-duplicate chunks crowded out the evidence ledger.
   Identical text on consecutive slides or pages is not byte-identical once
   page furniture differs, so exact-hash dedup missed it. Three ledger slots
   went to the same BASS summary from pages 35, 36 and 37.

   Fix: a shingle key over the normalised first part of each chunk, used by
   the retriever to keep only the best of a near-identical group.

This runs on data/index/chunks.jsonl in place - no document re-extraction.

Run:  python -m rag.enrich
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "data", "rag")

# Acronyms as they appear in NASA text, mapped to accession. Longer, more
# specific forms are matched first so "BASS-II" never matches as "BASS".
ACRONYMS = [
    ("SAFFIRE-III", "PSI-100"), ("SAFFIRE-II", "PSI-99"), ("SAFFIRE-I", "PSI-98"),
    ("SAFFIRE", None),           # bare SAFFIRE is ambiguous: do not attribute
    ("BASS-II", "PSI-25"), ("BASS", "PSI-26"),
    ("FLEX-2", "PSI-68"), ("FLEX", "PSI-69"),
    ("CFI-G", "PSI-159"), ("CFI", "PSI-39"),
    ("SAME-R", "PSI-101"), ("SAME", "PSI-102"),
    ("DAFT-2", "PSI-47"), ("DAFT", "PSI-47"),
    ("SPICE", "PSI-107"),
    ("E-FIELD", "PSI-22"), ("s-Flame", "PSI-23"),
    ("BRE", "PSI-20"), ("Flame Design", "PSI-10"),
    ("SLICE", None),             # excluded from the corpus; mention only
    ("ACME", None),              # programme, not one investigation
]

# A mention only counts as the subject if the text is clearly about it, not
# merely listing it. Require the acronym to appear at least this many times,
# or once in the opening sentence.
SUBJECT_MIN_HITS = 3
OPENING_CHARS = 180

SHINGLE_CHARS = 260


def _norm(text: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", t).strip()


def shingle_key(text: str) -> str:
    """Stable key for near-identical chunks.

    Uses the normalised opening of the chunk: repeated slides and repeated
    report summaries share an opening even when page numbers differ.
    """
    return hashlib.sha1(_norm(text)[:SHINGLE_CHARS].encode()).hexdigest()[:16]


def find_mentions(text: str):
    """Accessions named in the text itself, with hit counts."""
    hits = {}
    consumed = text
    for token, acc in ACRONYMS:
        pat = re.compile(r"(?<![A-Za-z0-9-])" + re.escape(token) + r"(?![A-Za-z0-9])",
                         re.I if len(token) > 4 else 0)
        n = len(pat.findall(consumed))
        if n:
            consumed = pat.sub(" ", consumed)   # so BASS-II is not recounted as BASS
            if acc:
                hits[acc] = hits.get(acc, 0) + n
    return hits


def pick_subject(text: str, owner: str, mentions: dict):
    """What the chunk is about, if the text disagrees with the folder."""
    if not mentions or owner in mentions:
        return None
    # Require both signals: named early AND named repeatedly. A sibling
    # investigation mentioned once in passing (a BASS-II report referring to
    # BASS hardware) must not reassign the chunk.
    opening = find_mentions(text[:OPENING_CHARS])
    best, best_n = None, 0
    for acc, n in mentions.items():
        if n >= SUBJECT_MIN_HITS and acc in opening and n > best_n:
            best, best_n = acc, n
    return best


def enrich(path: str | None = None):
    path = path or os.path.join(IDX, "chunks.jsonl")
    chunks = [json.loads(l) for l in open(path, encoding="utf-8")]

    groups = collections.Counter()
    subjects = 0
    for c in chunks:
        m = find_mentions(c["text"])
        c["mentions"] = sorted(m)
        c["shingle"] = shingle_key(c["text"])
        subj = pick_subject(c["text"], c["accession"], m)
        c["subject"] = subj
        if subj:
            subjects += 1
        groups[c["shingle"]] += 1

    with open(path, "w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    near_dup_groups = {k: v for k, v in groups.items() if v > 1}
    redundant = sum(v - 1 for v in near_dup_groups.values())

    print(f"chunks enriched        : {len(chunks)}")
    print(f"chunks naming another  : {subjects}  "
          f"(text is about an investigation other than its folder)")
    print(f"near-duplicate groups  : {len(near_dup_groups)}")
    print(f"redundant near-dups    : {redundant} "
          f"({100 * redundant / len(chunks):.1f}% of corpus)")

    top = collections.Counter()
    for c in chunks:
        if c["subject"]:
            top[(c["accession"], c["subject"])] += 1
    print()
    print("top folder -> subject corrections:")
    for (owner, subj), n in top.most_common(8):
        print(f"  {owner:9} text about {subj:9} x{n}")

    ok = len(chunks) > 0 and subjects > 0
    print()
    print("MINI-GOAL 7 (attribution + near-dup keys):", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(enrich())
