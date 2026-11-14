"""Hybrid retrieval over the PSI corpus, with a completeness report.

Layer 2 of the accuracy design.

Why hybrid: embeddings generalise but are weak on the rare tokens that matter
most here - PMMA, Sibal, Zst, n-heptane, "4.3 psi", SAFFIRE. BM25 matches those
exactly. TF-IDF character n-grams add robustness to spelling and hyphenation
variants. Scores are combined with Reciprocal Rank Fusion, which needs no score
calibration between the retrievers.

Because the corpus is small (7,770 chunks, 19 investigations) we can do two
things a large system cannot, and both are shown to the user:
  * over-retrieve (top 150) then rerank, instead of trusting a top-5;
  * prove coverage - report every investigation that was searched, which ones
    matched, and which were considered but fell below threshold.

An embedding retriever is added automatically if sentence-transformers is
installed; everything works without it.

Run:  python -m rag.retrieve "your question"
"""
from __future__ import annotations

import collections
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "data", "rag")

POOL = 150          # candidates pulled from each retriever before fusion
RRF_K = 60          # Reciprocal Rank Fusion damping
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Domain vocabulary. Terms a query may imply but not say, used to widen recall.
EXPANSIONS = {
    "flammability": ["flammable", "ignition", "flame spread", "burning"],
    "fabric": ["cotton", "textile", "cloth", "fiberglass", "Sibal"],
    "solid": ["PMMA", "acrylic", "plastic", "sample", "slab"],
    "oxygen": ["O2", "oxygen concentration", "oxygen mole fraction", "enriched"],
    "suppression": ["extinguish", "extinguishment", "suppressant", "quench"],
    "smoke": ["aerosol", "particulate", "smoke detector", "particle size"],
    "detection": ["detector", "sensor", "alarm", "obscuration"],
    "pressure": ["kPa", "psi", "atm", "ambient pressure"],
    "airflow": ["flow velocity", "co-flow", "forced convection", "cm/s"],
    "droplet": ["drop", "n-heptane", "n-decane", "evaporation"],
    "microgravity": ["reduced gravity", "zero gravity", "mu-g", "ISS"],
    "spacecraft": ["ISS", "orbiter", "vehicle", "habitat", "crew"],
    "lunar": ["Moon", "habitat", "partial gravity"],
    "mars": ["Martian", "partial gravity"],
}

_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-/]*[A-Za-z]|[A-Za-z]|\d+(?:\.\d+)?")


def tokenize(text: str):
    return [t.lower() for t in _TOKEN.findall(text)]


def expand_query(q: str) -> str:
    """Append domain synonyms for terms present in the query."""
    low = q.lower()
    extra = []
    for key, syns in EXPANSIONS.items():
        if key in low:
            extra += syns
    return q + (" " + " ".join(extra) if extra else "")


class Retriever:
    def __init__(self, use_embeddings: bool = True):
        self.chunks = [json.loads(l) for l in
                       open(os.path.join(IDX, "chunks.jsonl"), encoding="utf-8")]
        self.stats = json.load(open(os.path.join(IDX, "corpus_stats.json"),
                                    encoding="utf-8"))
        self.depth = self.stats["evidence_depth"]
        self.investigations = sorted(self.depth)
        texts = [c["text"] for c in self.chunks]

        from rank_bm25 import BM25Okapi
        self.bm25 = BM25Okapi([tokenize(t) for t in texts])

        from sklearn.feature_extraction.text import TfidfVectorizer
        # Word-level TF-IDF, sublinear tf so long report chunks do not dominate.
        self.tfidf = TfidfVectorizer(sublinear_tf=True, stop_words="english",
                                     ngram_range=(1, 2), min_df=2, max_df=0.6)
        self.tfidf_m = self.tfidf.fit_transform(texts)

        self.embedder = None
        self.emb = None
        if use_embeddings:
            try:
                from sentence_transformers import SentenceTransformer
                import numpy as np
                cache = os.path.join(IDX, "embeddings.npy")
                self.embedder = SentenceTransformer(EMBED_MODEL)
                if os.path.exists(cache):
                    self.emb = np.load(cache)
                    if self.emb.shape[0] != len(texts):
                        self.emb = None
                if self.emb is None:
                    self.emb = self.embedder.encode(
                        texts, batch_size=64, convert_to_numpy=True,
                        normalize_embeddings=True, show_progress_bar=True)
                    np.save(cache, self.emb)
            except Exception:
                self.embedder = None
                self.emb = None

    # -- individual retrievers ------------------------------------------
    def _bm25(self, q: str, n: int):
        scores = self.bm25.get_scores(tokenize(q))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:n]
        return [(i, float(scores[i])) for i in order if scores[i] > 0]

    def _tfidf(self, q: str, n: int):
        from sklearn.metrics.pairwise import linear_kernel
        v = self.tfidf.transform([q])
        sims = linear_kernel(v, self.tfidf_m).ravel()
        order = sorted(range(len(sims)), key=lambda i: -sims[i])[:n]
        return [(i, float(sims[i])) for i in order if sims[i] > 0]

    def _embed(self, q: str, n: int):
        if self.emb is None:
            return []
        qv = self.embedder.encode([q], convert_to_numpy=True,
                                  normalize_embeddings=True)[0]
        sims = self.emb @ qv
        order = sorted(range(len(sims)), key=lambda i: -sims[i])[:n]
        return [(i, float(sims[i])) for i in order]

    # -- fusion ----------------------------------------------------------
    def search(self, query: str, k: int = 8, pool: int = POOL):
        q = expand_query(query)
        runs = {"bm25": self._bm25(q, pool), "tfidf": self._tfidf(q, pool)}
        if self.emb is not None:
            runs["embed"] = self._embed(query, pool)

        fused = collections.defaultdict(float)
        contrib = collections.defaultdict(dict)
        for name, run in runs.items():
            for rank, (i, s) in enumerate(run, 1):
                fused[i] += 1.0 / (RRF_K + rank)
                contrib[i][name] = rank

        ranked = sorted(fused.items(), key=lambda kv: -kv[1])

        # Keep only the best of each near-identical group, so repeated slides
        # or repeated report summaries cannot occupy several ledger slots.
        results, seen_shingles, suppressed = [], set(), 0
        for i, score in ranked:
            if len(results) >= k:
                break
            c = dict(self.chunks[i])
            sh = c.get("shingle")
            if sh and sh in seen_shingles:
                suppressed += 1
                continue
            if sh:
                seen_shingles.add(sh)
            c["score"] = round(score, 5)
            c["matched_by"] = contrib[i]
            # The folder stays the factual location; `subject` records what
            # the text is about when it names a different investigation, and
            # citations prefer it (see rag/enrich.py).
            owner = c["accession"]
            c["attributed_to"] = c.get("subject") or owner
            c["evidence_level"] = self.depth[owner]["evidence_level"]
            results.append(c)

        # Completeness: what was searched, what matched, what was near-miss.
        considered = collections.Counter()
        for i, _ in ranked[:pool]:
            considered[self.chunks[i]["accession"]] += 1
        matched = set()
        for r in results:
            matched.add(r["accession"])
            matched.add(r["attributed_to"])
            matched.update(r.get("also_in") or [])
            # An investigation named in retrieved text is genuinely covered by
            # that evidence, even if the file is filed elsewhere.
            matched.update(r.get("mentions") or [])

        report = {
            "query": query,
            "expanded_query": q if q != query else None,
            "retrievers_used": sorted(runs),
            "embeddings_active": self.emb is not None,
            "chunks_searched": len(self.chunks),
            "investigations_searched": len(self.investigations),
            "pool_size": min(pool, len(ranked)),
            "near_duplicates_suppressed": suppressed,
            "matched_investigations": sorted(matched),
            "considered_below_threshold": sorted(
                acc for acc in considered if acc not in matched),
            "not_retrieved": sorted(
                acc for acc in self.investigations
                if acc not in matched and acc not in considered),
        }
        return results, report


def main():
    # Windows consoles default to cp1252; NASA text contains en-dashes and
    # mathematical symbols that would otherwise crash printing.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    q = " ".join(sys.argv[1:])
    r = Retriever()
    results, report = r.search(q)
    print(f"query  : {q}")
    print(f"engine : {', '.join(report['retrievers_used'])}"
          f"  (embeddings {'on' if report['embeddings_active'] else 'off'})")
    print(f"scope  : {report['chunks_searched']} chunks, "
          f"{report['investigations_searched']}/19 investigations")
    print(f"matched: {', '.join(report['matched_investigations'])}")
    if report["considered_below_threshold"]:
        print(f"near   : {', '.join(report['considered_below_threshold'])}")
    print()
    for i, c in enumerate(results, 1):
        where = c["file"] if c["source_type"] == "document" else c["section"]
        page = f" p.{c['page']}" if c.get("page") else ""
        also = f"  (also in {', '.join(c['also_in'])})" if c["also_in"] else ""
        print(f"[{i}] {c['accession']} {c['acronym'] or '':20} "
              f"score={c['score']:.4f} via={','.join(c['matched_by'])} "
              f"[{c['evidence_level']}]")
        print(f"    {where}{page}{also}")
        print(f"    {c['text'][:260].replace(chr(10), ' ')}...")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
