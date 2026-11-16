"""The interface the frontend uses (frontend/serve.py, frontend/build_cache.py).

`from rag import search as rag` gives three calls:

    search(q, k=6) -> [{"id", "title", "score", "snippet", "doi"}, ...]
    summarize(id)  -> dict shown in an expander
    ask(question)  -> {"answer": str, "sources": [str, ...], ...}

This module provides exactly those on top of rag.answer.EvidenceLedger, and
`ask()` additionally returns the evidence ledger, condition rows and gap radar for the richer rendering.

Retrieval is chunk-level; `search()` rolls chunks up to investigations, scoring
each by its best-matching chunks. Loading is lazy and cached, because building
the index means reading 7,770 chunks and an embedding model.
"""
from __future__ import annotations

import collections
import json
import os
import re
import threading

# How many of an investigation's best passages decide its rank. Small, so a
# study with thousands of chunks cannot win on volume alone.
TOP_PASSAGES = 3
# Weight of PSI's own research-area labels. Deliberately modest: it should
# break ties toward on-topic studies, not override the retrieved text.
AREA_BOOST = 0.02

_WORD = re.compile(r"[a-z]{4,}")
_STOP = {"experiment", "experiments", "investigation", "investigations", "study",
         "studies", "data", "which", "what", "these", "there", "about", "from",
         "with", "were", "that", "this", "have", "been", "measured", "science"}


def _area_overlap(query: str, depth: dict) -> float:
    """Fraction of query terms matching an investigation's PSI area labels.

    The query is NOT synonym-expanded here. Expanding it was tried and made
    ranking worse: the overlap is a fraction of query terms, so a long generic
    title ("Advanced Combustion via Microgravity Experiments - Structure and
    Response of Spherical Diffusion Flames") matches many expanded terms and
    outranks a short on-topic one. Expansion belongs in retrieval, which scores
    passages, not in a label-matching tie-breaker.
    """
    q = {w for w in _WORD.findall(query.lower()) if w not in _STOP}
    if not q:
        return 0.0
    labels = " ".join(str(depth.get(key) or "") for key in
                      ("research_area", "sub_research_area", "title", "acronym")).lower()
    if not labels.strip():
        return 0.0
    return sum(1 for w in q if w in labels) / len(q)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_PATH = os.path.join(ROOT, "data", "metadata.json")

_lock = threading.Lock()
_ledger = None
_meta = None


def _get_ledger():
    """Build the index once per process."""
    global _ledger
    if _ledger is None:
        with _lock:
            if _ledger is None:
                from rag.answer import EvidenceLedger
                # FIF_EMBEDDINGS=0 skips the semantic model (no PyTorch): keyword
                # search only, small enough for a 512 MB free server.
                _ledger = EvidenceLedger(use_embeddings=os.environ.get("FIF_EMBEDDINGS", "1") != "0")
    return _ledger


def _get_meta():
    global _meta
    if _meta is None:
        with open(META_PATH, encoding="utf-8") as fh:
            _meta = json.load(fh)
    return _meta


def available() -> bool:
    """True when the corpus has been built, so callers can fall back cleanly."""
    return os.path.exists(os.path.join(ROOT, "data", "rag", "chunks.jsonl"))


# --------------------------------------------------------------------------
# search: investigation-level hits, as the dashboard cards expect
# --------------------------------------------------------------------------

def search(q: str, k: int = 6):
    """Investigations relevant to `q`, best first.

    An investigation's score is the sum of its chunk fusion scores, so a study
    matching on several passages outranks one matching on a single line. The
    snippet is the best-matching passage itself, not a canned summary field.
    """
    led = _get_ledger()
    meta = _get_meta()
    # Over-retrieve chunks so the roll-up has several passages per study.
    chunks, _report = led.r.search(q, k=max(k * 5, 30))

    agg = collections.defaultdict(lambda: {"hits": [], "best": None, "chunks": 0})
    for c in chunks:
        # Credit what the text is about, plus every study the same file belongs to.
        for acc in {c.get("subject") or c["accession"], c["accession"],
                    *(c.get("also_in") or [])}:
            a = agg[acc]
            a["hits"].append(c["score"])
            a["chunks"] += 1
            if a["best"] is None:
                a["best"] = c

    # Rank on the best few passages, not the total.
    #
    # Summing every matching chunk rewards document volume, and volume here is
    # wildly uneven: ACME BRE has ~1,600 retrievable chunks, SAFFIRE-I has 1.
    # Summing made every fire-safety query return ACME - which is gaseous-fuel
    # combustion, not spacecraft fire safety. Taking the top few passages caps
    # that advantage, and a small boost for PSI's own research-area labels lets
    # a short, on-topic study outrank a long, off-topic one.
    for acc, a in agg.items():
        top = sorted(a["hits"], reverse=True)[:TOP_PASSAGES]
        a["score"] = sum(top) / len(top) if top else 0.0
        a["score"] += AREA_BOOST * _area_overlap(q, led.depth.get(acc, {}))

    out = []
    for acc, a in sorted(agg.items(), key=lambda kv: -kv[1]["score"])[:k]:
        s = meta.get(acc, {})
        best = a["best"] or {}
        depth = led.depth.get(acc, {})
        out.append({
            "id": acc,
            "title": s.get("title") or depth.get("title") or acc,
            "score": round(a["score"], 5),
            "snippet": " ".join((best.get("text") or "").split())[:320],
            "doi": s.get("doi", ""),
            # extras the frontend shows next to each result
            "acronym": depth.get("acronym") or s.get("investigationAcronym") or "",
            "evidence_level": depth.get("evidence_level", "unknown"),
            "matched_chunks": a["chunks"],
            "source_file": best.get("file"),
            "source_page": best.get("page"),
        })
    return out


# --------------------------------------------------------------------------
# summarize: what PSI holds for one investigation, measured not generated
# --------------------------------------------------------------------------

def summarize(investigation_id: str):
    """Evidence profile for one investigation. No model involved."""
    led = _get_ledger()
    meta = _get_meta().get(investigation_id, {})
    depth = led.depth.get(investigation_id, {})
    pubs = [p for p in (meta.get("publications") or []) if p]
    return {
        "investigation": investigation_id,
        "acronym": depth.get("acronym") or meta.get("investigationAcronym") or "",
        "title": meta.get("title"),
        "evidence_level": depth.get("evidence_level"),
        "retrievable_document_chunks": depth.get("document_chunks"),
        "experimental_condition_rows": depth.get("condition_rows"),
        "project_type": depth.get("project_type"),
        "flight_platform": depth.get("flight_platform"),
        "doi": meta.get("doi"),
        "publications": len(pubs),
        "note": ("PSI publishes little analysable text for this investigation; "
                 "its primary evidence is raw instrument data."
                 if depth.get("evidence_level") in ("thin", "metadata_only") else None),
    }


# --------------------------------------------------------------------------
# ask: grounded answer plus everything needed to audit it
# --------------------------------------------------------------------------

def ask(question: str, k: int = 6):
    """Grounded answer for `question`.

    `answer` is None when no language model is reachable, or when the draft was
    blocked for containing numbers or citations absent from the sources. The
    ledger, condition rows and gap radar are always populated, so the UI has a
    complete answer either way.
    """
    led = _get_ledger()
    res = led.compose_prose(led.ask(question, k=k))
    v = res.get("verification") or {}
    meta = _get_meta()

    sources = []
    for row in res["evidence_ledger"]:
        acc = row["investigation"]
        label = row["acronym"] or acc
        if label not in sources:
            sources.append(label)

    return {
        "answer": res["prose"],
        "sources": sources,
        "evidence": [{
            "investigation": r["investigation"],
            "acronym": r["acronym"],
            "about": r.get("about_acronym") or r.get("about"),
            "kind": r["evidence_kind"],
            "evidence_level": r["evidence_level"],
            "file": r["file"],
            "page": r.get("page"),
            "text": r["claim_source"],
            "cites": r["cites"],
            "doi": meta.get(r["investigation"], {}).get("doi", ""),
        } for r in res["evidence_ledger"]],
        "conditions": res["condition_rows"],
        "conditions_available": res["condition_rows_available"],
        "gaps": res["gap_radar"],
        "coverage": res["coverage"],
        "completeness": res["completeness"],
        "grounding": {
            "verdict": v.get("verdict", "skipped"),
            "backend": v.get("backend"),
            "model": v.get("model"),
            "numbers_checked": (v.get("numbers") or {}).get("numbers_checked", 0),
            "numbers_verbatim": (v.get("numbers") or {}).get("supported", 0),
            "rejected_numbers": (v.get("numbers") or {}).get("unsupported", []),
            "invalid_citations": (v.get("citations") or {}).get("invalid", []),
            "note": v.get("note"),
        },
    }
