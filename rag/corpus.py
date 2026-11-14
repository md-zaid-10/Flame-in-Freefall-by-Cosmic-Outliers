"""Build the retrievable corpus from the downloaded NASA PSI material.

Three sources, deliberately kept distinct because they carry different authority:

  metadata  - PSI's own structured description of each investigation
              (objective / approach / hypothesis / research impacts).
              Clean prose, written by NASA, highest trust.
  document  - text extracted from Science Documents, Reports, Presentations.
              Where the actual findings live.
  table     - experimental condition tables (CSV). NOT chunked for embedding;
              loaded as structured rows so numbers are queried, never generated.

Output
  data/index/chunks.jsonl        one JSON object per retrievable chunk
  data/index/conditions.jsonl    one JSON object per experimental-table row
  data/index/corpus_stats.json   counts used by the Gap Radar and the eval set

Run:  python -m rag.corpus
"""
from __future__ import annotations

import collections
import csv
import hashlib
import io
import json
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "data", "raw", "documents")   # gitignored, fetched by rag/prep
TABLES = os.path.join(ROOT, "data", "raw", "tables")    # shared, from data/fetch_psi.py
META = os.path.join(ROOT, "data", "metadata.json")      # shared, from data/fetch_psi.py
OUT = os.path.join(ROOT, "data", "rag")

# Investigations in the RAG corpus. data/metadata.json carries all 24 that PSI's
# combustion search returns; these 19 are the ones with usable documents. The
# other five hold raw data only - see data/rag/EXCLUDED_INVESTIGATIONS.md.
CORPUS = [
    "PSI-26", "PSI-25", "PSI-98", "PSI-99", "PSI-100",
    "PSI-69", "PSI-68", "PSI-39", "PSI-159",
    "PSI-102", "PSI-101", "PSI-47", "PSI-107",
    "PSI-10", "PSI-20", "PSI-22", "PSI-23",
    "PSI-117", "PSI-115",
]

# Chunking. Documents here are technical reports; ~1200 characters keeps a
# finding together with the conditions it was measured under, and the overlap
# stops a sentence being cut away from the number it refers to.
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200
MIN_CHUNK_CHARS = 120

# Statuses from scripts/test_extraction.py that are safe to index.
USABLE_STATUS = {"ok"}

# Narrative metadata fields worth retrieving, in the order they read best.
META_FIELDS = [
    ("objective", "Objectives"),
    ("approach", "Approach"),
    ("hypothesis", "Hypothesis"),
    ("researchImpacts", "Research impacts and Earth benefits"),
    ("description", "Description"),
]


# --------------------------------------------------------------------------
# text handling
# --------------------------------------------------------------------------

def clean(text: str) -> str:
    """Normalise whitespace without destroying paragraph structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Drop lines that are pure page furniture.
    keep = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            keep.append("")
            continue
        if re.fullmatch(r"(page\s*)?\d{1,4}(\s*of\s*\d{1,4})?", s, re.I):
            continue
        keep.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()


def split_chunks(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP):
    """Paragraph-aware sliding window.

    Paragraphs are packed until the window is full, so a chunk boundary lands
    between paragraphs where possible. Over-long paragraphs (tables, dense
    report text) fall back to a character window with overlap.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(p) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            step = size - overlap
            for i in range(0, len(p), step):
                piece = p[i:i + size]
                if len(piece) >= MIN_CHUNK_CHARS:
                    chunks.append(piece)
            continue
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS]


def text_hash(text: str) -> str:
    return hashlib.sha1(
        re.sub(r"\s+", " ", text).strip().lower().encode("utf-8", "replace")
    ).hexdigest()


# --------------------------------------------------------------------------
# extraction (re-uses the readers proven in scripts/test_extraction.py)
# --------------------------------------------------------------------------

def read_document(path: str):
    """Return (list of (page_or_unit_number, text)) so citations can cite a page."""
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        from pypdf import PdfReader
        r = PdfReader(path)
        if r.is_encrypted:
            try:
                r.decrypt("")
            except Exception:
                return []
        out = []
        for i, p in enumerate(r.pages, 1):
            try:
                t = p.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                out.append((i, t))
        return out
    if ext == "docx":
        import docx
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for t in d.tables:
            for row in t.rows:
                line = "\t".join(c.text for c in row.cells).strip()
                if line:
                    parts.append(line)
        return [(None, "\n".join(parts))]
    if ext == "pptx":
        from pptx import Presentation
        pr = Presentation(path)
        out = []
        for i, s in enumerate(pr.slides, 1):
            parts = []
            for sh in s.shapes:
                if sh.has_text_frame and sh.text_frame.text.strip():
                    parts.append(sh.text_frame.text)
                if getattr(sh, "has_table", False):
                    for row in sh.table.rows:
                        parts.append("\t".join(c.text for c in row.cells))
            if s.has_notes_slide and s.notes_slide.notes_text_frame is not None:
                n = s.notes_slide.notes_text_frame.text
                if n.strip():
                    parts.append(n)
            if parts:
                out.append((i, "\n".join(parts)))
        return out
    if ext == "xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    parts.append("\t".join(cells))
        wb.close()
        return [(None, "\n".join(parts))]
    return []


def read_csv_rows(path: str):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            raw = open(path, encoding=enc).read()
            break
        except UnicodeDecodeError:
            continue
    else:
        return [], []
    try:
        dialect = csv.Sniffer().sniff(raw[:4000], delimiters=",;\t")
    except Exception:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(raw), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return [], []
    # The real header is the first row with several non-numeric labels.
    header_idx = 0
    for i, r in enumerate(rows[:10]):
        labels = [c for c in r if c.strip() and not re.fullmatch(r"-?[\d.,]+", c.strip())]
        if len(labels) >= max(2, len(r) // 2):
            header_idx = i
            break
    header = [c.strip() or f"col{j}" for j, c in enumerate(rows[header_idx])]
    return header, rows[header_idx + 1:]


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def load_investigations():
    """Investigation metadata for the RAG corpus, keyed by accession.

    Reads the repository's shared data/metadata.json, written by
    data/fetch_psi.py, so the RAG layer and the ML layer work from one source.
    """
    allmeta = json.load(open(META, encoding="utf-8"))
    missing = [a for a in CORPUS if a not in allmeta]
    if missing:
        raise SystemExit(
            f"data/metadata.json is missing {missing}. "
            f"Run:  python data/fetch_psi.py {' '.join(missing)}")

    inv = {}
    for acc in CORPUS:
        d = allmeta[acc]
        pubs = [p for p in (d.get("publications") or []) if p]
        inv[acc] = {
            "accession": acc,
            "acronym": (d.get("investigationAcronym") or "").strip(),
            "title": d.get("title"),
            "research_area": d.get("researchArea"),
            "sub_research_area": d.get("subResearchArea"),
            "project_type": d.get("projectType"),
            "flight_platform": d.get("flightProgram") or d.get("missionName"),
            "hardware": d.get("experimentHardware"),
            "doi": d.get("doi"),
            "source_link": d.get("sourceLink"),
            "publication_count": len(pubs),
            "raw": d,
        }
    return inv


def build():
    os.makedirs(OUT, exist_ok=True)
    inv = load_investigations()
    report_path = os.path.join(ROOT, "data", "rag", "extraction_report_full.json")
    report = json.load(open(report_path, encoding="utf-8"))
    # (accession, filename) -> extraction status
    status = {(r["acc"], r["name"]): r for r in report}

    chunks, conditions = [], []
    seen_hashes = {}          # text hash -> chunk id, for cross-investigation dedup
    per_inv = collections.Counter()
    skipped = collections.Counter()

    # ---- source 1: investigation metadata -------------------------------
    for acc, meta in inv.items():
        d = meta["raw"]
        for field, label in META_FIELDS:
            val = (d.get(field) or "").strip()
            if len(val) < MIN_CHUNK_CHARS:
                continue
            for i, piece in enumerate(split_chunks(clean(val))):
                cid = f"{acc}:meta:{field}:{i}"
                h = text_hash(piece)
                if h in seen_hashes:
                    continue
                seen_hashes[h] = cid
                chunks.append({
                    "id": cid, "source_type": "metadata", "accession": acc,
                    "acronym": meta["acronym"], "section": label,
                    "file": "data/metadata.json",
                    "page": None, "text": piece, "text_sha1": h,
                    "also_in": [],
                })
                per_inv[acc] += 1

    # ---- source 2: documents --------------------------------------------
    for acc in sorted(inv):
        folder = os.path.join(DOCS, acc)
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if fn.startswith("_"):
                continue
            ext = fn.rsplit(".", 1)[-1].lower()
            if ext in {"doc", "ppt", "xls"}:
                continue                      # superseded by converted twin
            st = status.get((acc, fn))
            if st is None or st.get("status") not in USABLE_STATUS:
                skipped[(st or {}).get("status", "not_in_report")] += 1
                continue
            path = os.path.join(folder, fn)
            try:
                units = read_document(path)
            except Exception as e:
                skipped[f"read_error:{type(e).__name__}"] += 1
                continue
            for unit_no, raw_text in units:
                for i, piece in enumerate(split_chunks(clean(raw_text))):
                    h = text_hash(piece)
                    if h in seen_hashes:
                        # Same text already indexed elsewhere: keep one copy but
                        # record every investigation it belongs to, so a citation
                        # can credit all of them.
                        owner = seen_hashes[h]
                        for c in chunks:
                            if c["id"] == owner:
                                if acc not in c["also_in"] and acc != c["accession"]:
                                    c["also_in"].append(acc)
                                break
                        continue
                    cid = f"{acc}:doc:{fn}:{unit_no or 0}:{i}"
                    seen_hashes[h] = cid
                    chunks.append({
                        "id": cid, "source_type": "document", "accession": acc,
                        "acronym": inv[acc]["acronym"],
                        "section": st.get("cat"), "file": fn, "page": unit_no,
                        "text": piece, "text_sha1": h, "also_in": [],
                    })
                    per_inv[acc] += 1

    # ---- source 3: experimental tables (structured, never embedded) -----
    for acc in sorted(inv):
        folder = os.path.join(TABLES, acc)
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.lower().endswith(".csv"):
                continue
            header, rows = read_csv_rows(os.path.join(folder, fn))
            if not header:
                continue
            for n, row in enumerate(rows):
                rec = {header[j]: row[j].strip()
                       for j in range(min(len(header), len(row)))
                       if row[j].strip()}
                if not rec:
                    continue
                conditions.append({
                    "id": f"{acc}:cond:{fn}:{n}", "accession": acc,
                    "acronym": inv[acc]["acronym"], "file": fn,
                    "row": n, "values": rec,
                })

    # ---- write ----------------------------------------------------------
    with open(os.path.join(OUT, "chunks.jsonl"), "w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "conditions.jsonl"), "w", encoding="utf-8") as fh:
        for c in conditions:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    # Evidence depth per investigation drives the Gap Radar and the UI badge.
    depth = {}
    for acc, meta in inv.items():
        doc_chunks = sum(1 for c in chunks
                         if c["accession"] == acc and c["source_type"] == "document")
        meta_chunks = sum(1 for c in chunks
                          if c["accession"] == acc and c["source_type"] == "metadata")
        n_cond = sum(1 for c in conditions if c["accession"] == acc)
        # Thresholds are on retrievable chunks, so they track how much the
        # assistant can actually ground an answer in, not file count.
        if doc_chunks == 0:
            level = "metadata_only"
        elif doc_chunks < 50:
            level = "thin"
        elif doc_chunks < 250:
            level = "moderate"
        else:
            level = "rich"
        depth[acc] = {
            "acronym": meta["acronym"], "title": meta["title"],
            "research_area": meta["research_area"],
            "sub_research_area": meta["sub_research_area"],
            "project_type": meta["project_type"],
            "flight_platform": meta["flight_platform"],
            "doi": meta["doi"],
            "document_chunks": doc_chunks, "metadata_chunks": meta_chunks,
            "condition_rows": n_cond, "evidence_level": level,
        }

    stats = {
        "chunks": len(chunks),
        "condition_rows": len(conditions),
        "investigations": len(inv),
        "investigations_with_documents": sum(
            1 for v in depth.values() if v["document_chunks"] > 0),
        "chunks_by_source": dict(collections.Counter(c["source_type"] for c in chunks)),
        "duplicate_chunks_collapsed": sum(len(c["also_in"]) for c in chunks),
        "skipped_files": {str(k): v for k, v in skipped.items()},
        "evidence_depth": depth,
    }
    json.dump(stats, open(os.path.join(OUT, "corpus_stats.json"), "w"), indent=1)

    # ---- mini-goal check -------------------------------------------------
    print(f"chunks            : {len(chunks)}")
    print(f"  metadata        : {stats['chunks_by_source'].get('metadata', 0)}")
    print(f"  document        : {stats['chunks_by_source'].get('document', 0)}")
    print(f"condition rows    : {len(conditions)}")
    print(f"investigations    : {len(inv)} "
          f"({stats['investigations_with_documents']} with documents)")
    print(f"dup links recorded: {stats['duplicate_chunks_collapsed']}")
    print(f"skipped files     : {dict(skipped)}")
    print()
    print("evidence depth:")
    for acc, v in sorted(depth.items(), key=lambda kv: -kv[1]["document_chunks"]):
        print(f"  {acc:9} {(v['acronym'] or '-'):22} {v['evidence_level']:14} "
              f"{v['document_chunks']:4d} doc / {v['metadata_chunks']:2d} meta "
              f"/ {v['condition_rows']:4d} cond")

    ok = len(chunks) > 0 and len(conditions) > 0 and len(inv) == len(CORPUS)
    print()
    print("MINI-GOAL 1 (corpus built):", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(build())
