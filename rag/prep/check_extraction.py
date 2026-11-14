"""Measure extractable text across the downloaded NASA PSI corpus.

Produces, per file: character/word counts, a prose-density score, a text hash for
duplicate detection, and a status telling us whether the file is usable for RAG.

Statuses
    ok              usable prose
    not_prose       text extracts fine but is tabular/filename junk, not language
                    (e.g. the SAFFIRE-III image-directory spreadsheets, ~12M chars
                    of filenames that would swamp a vector index)
    needs_ocr       PDF with no text layer -> would need OCR
    thin_ocr_likely PDF with a sparse text layer -> probably part-scanned
    almost_no_text  parsed, but too little language to be worth indexing
    converted       legacy .doc/.ppt superseded by a converted .docx/.pptx twin
    legacy_format   legacy binary with no converted twin (run convert_legacy_office.ps1)
    parse_error     reader failed

Usage
    python scripts/test_extraction.py                 # whole corpus
    python scripts/test_extraction.py --sample 2      # 2 files per category x type
"""
import collections
import hashlib
import json
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
D = os.path.join(ROOT, "data", "raw", "documents")

# A PDF page with fewer than this many characters is almost certainly a scan.
CHARS_PER_PAGE_OCR = 100
# Share of characters that must be letters/spaces for text to count as prose.
MIN_PROSE_DENSITY = 0.55
# Mean token length outside this band signals filename lists or numeric dumps.
PROSE_WORD_LEN = (3.0, 12.0)
# Below this many alphabetic words a file is not worth indexing.
MIN_WORDS = 50

LEGACY = {"doc", "ppt", "xls"}
MODERN = {"doc": "docx", "ppt": "pptx", "xls": "xlsx"}


def pdf_text(path):
    from pypdf import PdfReader
    r = PdfReader(path)
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            return None, 0, "encrypted"
    pages = []
    for p in r.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages), len(r.pages), None


def docx_text(path):
    import docx
    d = docx.Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append("\t".join(c.text for c in row.cells))
    return "\n".join(parts), len(d.paragraphs), None


def pptx_text(path):
    from pptx import Presentation
    pr = Presentation(path)
    parts = []
    for s in pr.slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                parts.append(sh.text_frame.text)
            if getattr(sh, "has_table", False):
                for row in sh.table.rows:
                    parts.append("\t".join(c.text for c in row.cells))
        if s.has_notes_slide and s.notes_slide.notes_text_frame is not None:
            parts.append(s.notes_slide.notes_text_frame.text)
    return "\n".join(parts), len(pr.slides), None


def xlsx_text(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts, n = [], 0
    for ws in wb.worksheets:
        n += 1
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                parts.append("\t".join(cells))
    wb.close()
    return "\n".join(parts), n, None


def csv_text(path):
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            t = open(path, encoding=enc).read()
            return t, t.count("\n") + 1, None
        except UnicodeDecodeError:
            continue
    return None, 0, "encoding"


HANDLERS = {"pdf": pdf_text, "docx": docx_text, "pptx": pptx_text,
            "xlsx": xlsx_text, "csv": csv_text}


def prose_stats(text):
    """Distinguish real language from tabular/filename dumps."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    letters = sum(c.isalpha() or c.isspace() for c in text)
    density = letters / len(text) if text else 0.0
    mean_len = (sum(len(w) for w in words) / len(words)) if words else 0.0
    return len(words), round(density, 3), round(mean_len, 2)


def classify(ext, text, units, words, density, mean_len):
    if ext == "pdf":
        cpp = (len(text) / units) if units else 0
        if cpp < CHARS_PER_PAGE_OCR:
            return "needs_ocr" if len(text) < 200 else "thin_ocr_likely"
    if words < MIN_WORDS:
        return "almost_no_text"
    if density < MIN_PROSE_DENSITY or not (PROSE_WORD_LEN[0] <= mean_len <= PROSE_WORD_LEN[1]):
        return "not_prose"
    return "ok"


def pick_sample(man, per_bucket=2):
    """Up to `per_bucket` files per (category, extension), spread across studies."""
    buckets = collections.defaultdict(list)
    for r in man:
        buckets[(r["cat"], r["name"].rsplit(".", 1)[-1].lower())].append(r)
    sample, seen = [], collections.Counter()
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda r: (seen[r["acc"]], -r["bytes"]))
        for r in rows[:per_bucket]:
            sample.append(r)
            seen[r["acc"]] += 1
    return sample


def main():
    man = json.load(open(os.path.join(D, "_manifest_downloaded.json")))
    tag = "full"
    if len(sys.argv) > 1 and sys.argv[1] == "--sample":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        man = pick_sample(man, n)
        tag = "sample"
        print("stratified sample: " + str(len(man)) + " files")

    # Converted twins are extra files on disk, not in the download manifest.
    rows = list(man)
    for r in man:
        ext = r["name"].rsplit(".", 1)[-1].lower()
        if ext in LEGACY:
            twin = r["name"][: -len(ext)] + MODERN[ext]
            if os.path.exists(os.path.join(D, r["acc"], twin)):
                rows.append({**r, "name": twin, "converted_from": r["name"]})

    out = []
    for i, r in enumerate(rows, 1):
        path = os.path.join(D, r["acc"], r["name"])
        ext = r["name"].rsplit(".", 1)[-1].lower()
        rec = {"acc": r["acc"], "cat": r["cat"], "name": r["name"], "ext": ext,
               "mb": round(r["bytes"] / 1048576, 2)}
        if "converted_from" in r:
            rec["converted_from"] = r["converted_from"]

        if ext in LEGACY:
            twin = os.path.join(D, r["acc"], r["name"][: -len(ext)] + MODERN[ext])
            rec.update(status="converted" if os.path.exists(twin) else "legacy_format",
                       chars=0, words=0, units=0)
        elif ext not in HANDLERS:
            rec.update(status="unsupported", chars=0, words=0, units=0)
        else:
            try:
                text, units, err = HANDLERS[ext](path)
                if err:
                    rec.update(status=err, chars=0, words=0, units=units)
                else:
                    words, density, mean_len = prose_stats(text)
                    rec.update(chars=len(text), words=words, units=units,
                               density=density, mean_word_len=mean_len,
                               chars_per_unit=round(len(text) / units, 1) if units else 0,
                               text_sha1=hashlib.sha1(
                                   re.sub(r"\s+", " ", text).strip()
                                   .encode("utf-8", "replace")).hexdigest(),
                               status=classify(ext, text, units, words, density, mean_len))
            except Exception as e:
                rec.update(status="parse_error", chars=0, words=0, units=0,
                           error=str(e)[:160])
        out.append(rec)
        print(f"[{i:3d}/{len(rows)}] {rec['status']:16} {rec.get('chars', 0):9d} ch  "
              f"{r['acc']:9} {r['name'][:56]}", flush=True)

    dest = os.path.join(ROOT, "data", "rag", f"extraction_report_{tag}.json")
    json.dump(out, open(dest, "w"), indent=1)

    usable = [r for r in out if r["status"] == "ok"]
    print()
    print("STATUS:", dict(collections.Counter(r["status"] for r in out)))
    print(f"usable files : {len(usable)}")
    print(f"usable chars : {sum(r['chars'] for r in usable):,}")
    print(f"usable words : {sum(r['words'] for r in usable):,}")

    dupes = collections.defaultdict(list)
    for r in usable:
        dupes[r["text_sha1"]].append(f"{r['acc']}/{r['name'][:44]}")
    dup = {k: v for k, v in dupes.items() if len(v) > 1}
    print(f"duplicate text groups: {len(dup)} "
          f"({sum(len(v) for v in dup.values()) - len(dup)} redundant files)")
    for v in dup.values():
        print("   dup:", " | ".join(v))
    print("wrote", dest)


if __name__ == "__main__":
    main()
