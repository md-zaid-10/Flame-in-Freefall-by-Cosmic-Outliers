"""The Evidence Ledger - orchestrates all four accuracy layers into one answer.

Pipeline for a question:

  1. decompose          split into sub-questions; flag conditions PSI cannot cover
  2. retrieve           hybrid search per sub-question, with a coverage report
  3. conditions         pull matching rows from the experimental tables, so every
                        quantitative statement comes from a CSV and not a model
  4. compose            build the ledger: one row per evidence item, each with
                        investigation, file, page, evidence level and provenance
  5. gap radar          report what the corpus cannot support, measured not guessed
  6. verify             if a language model drafted prose, enforce number and
                        citation grounding before it is allowed out

Step 6 needs an API key. Everything else runs without one, which is deliberate:
the parts that have to be *measurable* do not depend on a model being reachable.
Set ANTHROPIC_API_KEY to enable the prose layer.

Run:
  python -m rag.answer "Which experiments studied fabric flammability?"
  python -m rag.answer --json "..."
"""
from __future__ import annotations

import json
import os
import re
import sys

from rag import decompose, verify
from rag.retrieve import Retriever

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "data", "rag")

# Column names in the experimental tables that carry the conditions we care
# about. Matched case-insensitively as substrings, since PSI's CSV headers are
# not consistent between investigations.
CONDITION_KEYS = {
    "oxygen": ["o2", "oxygen", "xo2"],
    "pressure": ["pressure", "psi", "kpa"],
    "flow": ["flow", "velocity", "cm/s"],
    "fuel": ["fuel", "material", "sample", "specimen"],
    "diameter": ["diameter", "thickness", "size", "dimension"],
    "temperature": ["temp", "temperature"],
}


class EvidenceLedger:
    def __init__(self, use_embeddings: bool = True):
        self.r = Retriever(use_embeddings=use_embeddings)
        self.conditions = [json.loads(l) for l in
                           open(os.path.join(IDX, "conditions.jsonl"),
                                encoding="utf-8")]
        self.depth = self.r.depth

    # -- step 3: structured conditions ---------------------------------
    def condition_rows(self, accessions, limit: int = 12):
        """Condition-table rows for the matched investigations.

        Returned verbatim with their source file and row number. Numbers shown
        to a user come from here; the prose layer is never asked for a value.
        """
        picked = []
        for c in self.conditions:
            if c["accession"] not in accessions:
                continue
            tagged = {}
            for label, needles in CONDITION_KEYS.items():
                best = None
                for col, val in c["values"].items():
                    low = col.lower()
                    if not any(n in low for n in needles):
                        continue
                    # "Sample #" / "Test #" are counters, not conditions.
                    if re.search(r"(^|\W)(#|no\.?|num|index|id)(\W|$)", low):
                        continue
                    numeric = bool(re.fullmatch(r"-?[\d.,;:\s%]+", val.strip()))
                    # A fuel or material is named, not numbered; a measurement is.
                    wanted_text = label in ("fuel",)
                    score = (0 if numeric == wanted_text else 1, -len(low))
                    if best is None or score > best[0]:
                        best = (score, col, val)
                if best:
                    tagged[label] = {"column": best[1], "value": best[2]}
            if tagged:
                picked.append({
                    "accession": c["accession"], "acronym": c["acronym"],
                    "file": c["file"], "row": c["row"], "conditions": tagged,
                })
        # Spread across investigations rather than dumping one study's table.
        by_acc = {}
        for p in picked:
            by_acc.setdefault(p["accession"], []).append(p)
        out, i = [], 0
        while len(out) < limit and any(len(v) > i for v in by_acc.values()):
            for acc in sorted(by_acc):
                if len(by_acc[acc]) > i and len(out) < limit:
                    out.append(by_acc[acc][i])
            i += 1
        return out, len(picked)

    # -- step 5: gap radar ---------------------------------------------
    def gap_radar(self, question, matched, scope_gaps):
        """What the corpus cannot support. Every item is measured from our data."""
        gaps = list(scope_gaps)

        thin = [a for a in matched
                if self.depth[a]["evidence_level"] in ("thin", "metadata_only")]
        if thin:
            detail = ", ".join(
                f"{self.depth[a]['acronym'] or a} "
                f"({self.depth[a]['document_chunks']} chunks)" for a in thin)
            gaps.append({
                "kind": "thin_evidence",
                "severity": "soft",
                "triggered_by": thin,
                "message": (
                    f"Thin document coverage for: {detail}. PSI publishes little "
                    f"analysable text for these; their primary evidence sits in "
                    f"raw instrument data and imagery, not in documents."),
            })

        no_cond = [a for a in matched if self.depth[a]["condition_rows"] == 0]
        if no_cond:
            gaps.append({
                "kind": "no_condition_table",
                "severity": "soft",
                "triggered_by": no_cond,
                "message": (
                    "No experimental condition table in PSI for: "
                    + ", ".join(self.depth[a]["acronym"] or a for a in no_cond)
                    + ". Quantitative conditions cannot be verified for these."),
            })

        ground = [a for a in matched
                  if (self.depth[a].get("project_type") or "") == "Ground Investigation"]
        if ground:
            gaps.append({
                "kind": "ground_investigation",
                "severity": "info",
                "triggered_by": ground,
                "message": (
                    "Includes ground investigations (modelling or analysis of "
                    "flight data), not flight measurements: "
                    + ", ".join(a for a in ground) + "."),
            })
        return gaps

    # -- orchestration ---------------------------------------------------
    def ask(self, question: str, k: int = 6):
        parts = decompose.split(question)
        scope_gaps = decompose.detect_scope_gaps(question)

        per_part, ledger, seen = [], [], set()
        reports = []
        for part in parts:
            results, report = self.r.search(part, k=k)
            per_part.append(results)
            reports.append(report)
            for rank, c in enumerate(results, 1):
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                owner = c["accession"]
                subject = c.get("subject")
                # Citeable: the folder, what the text is about, every
                # investigation the identical file also belongs to, and every
                # investigation the text itself names.
                cites = []
                for extra in ([subject, owner] + list(c.get("also_in") or [])
                              + list(c.get("mentions") or [])):
                    if extra and extra not in cites:
                        cites.append(extra)
                ledger.append({
                    "sub_question": part,
                    "rank": rank,
                    "claim_source": c["text"],
                    "investigation": owner,
                    "about": subject,
                    "acronym": c["acronym"],
                    "about_acronym": self.depth[subject]["acronym"] if subject else None,
                    "mentions": c.get("mentions") or [],
                    "source_type": c["source_type"],
                    "file": c["file"],
                    "page": c.get("page"),
                    "section": c.get("section"),
                    "evidence_level": c["evidence_level"],
                    "evidence_kind": ("NASA metadata" if c["source_type"] == "metadata"
                                      else "NASA document"),
                    "cites": cites,
                    "retrievers": list(c["matched_by"]),
                    "score": c["score"],
                })

        cov = decompose.coverage(parts, per_part)
        matched = sorted({row["investigation"] for row in ledger}
                         | {a for row in ledger for a in row["cites"]})
        cond_rows, cond_total = self.condition_rows(matched)
        gaps = self.gap_radar(question, matched, scope_gaps)

        # Completeness, merged across sub-questions.
        searched = reports[0]["investigations_searched"] if reports else 0
        near = sorted({a for rep in reports
                       for a in rep["considered_below_threshold"]
                       if a not in matched})

        return {
            "question": question,
            "sub_questions": parts,
            "coverage": cov,
            "evidence_ledger": ledger,
            "condition_rows": cond_rows,
            "condition_rows_available": cond_total,
            "gap_radar": gaps,
            "completeness": {
                "chunks_searched": reports[0]["chunks_searched"] if reports else 0,
                "investigations_searched": searched,
                "matched": matched,
                "considered_below_threshold": near,
                "embeddings_active": reports[0]["embeddings_active"] if reports else False,
                "retrievers": reports[0]["retrievers_used"] if reports else [],
            },
            "prose": None,          # filled by compose_prose() when a key exists
            "verification": None,
        }

    # -- optional prose layer -------------------------------------------
    def compose_prose(self, result):
        """Draft a cited summary with an LLM, then refuse it if it is not grounded.

        Runs on whatever backend rag.llm finds - by default a local ollama
        model, which needs no key and no network. If no backend is reachable
        the result is returned unchanged; the evidence ledger is already a
        complete answer without prose.
        """
        from rag import llm
        if not llm.available():
            result["verification"] = {
                "verdict": "skipped",
                "note": "No language model reachable; evidence ledger only.",
            }
            return result

        chunks = [{"accession": r["investigation"], "acronym": r["acronym"],
                   "also_in": [a for a in r["cites"] if a != r["investigation"]],
                   "text": r["claim_source"]}
                  for r in result["evidence_ledger"]]
        sources = "\n\n".join(
            f"[{c['acronym'] or c['accession']}] {c['text']}" for c in chunks)
        guard = "\n".join(g["message"] for g in result["gap_radar"]
                          if g["severity"] == "hard")

        # Measured conditions must reach the model, or it will say the sources
        # give no values while the condition table sitting beside it does.
        # These come from PSI's own experimental tables, so they are quotable.
        cond_lines = []
        for row in result["condition_rows"][:10]:
            vals = ", ".join(f"{k} = {v['value']}"
                             for k, v in row["conditions"].items())
            cond_lines.append(
                f"[{row['acronym'] or row['accession']}] {vals}  "
                f"(source: {row['file']} row {row['row']})")
        conditions = ("\n".join(cond_lines) if cond_lines else
                      "No experimental condition rows available.")

        system = ("You summarise NASA microgravity combustion research for "
                  "scientists. You restate the supplied sources and nothing else. "
                  "You never invent numbers, materials or findings.")
        prompt = (
            "Rules you must follow exactly:\n"
            "- Use ONLY the sources below. Never add outside knowledge.\n"
            "- Cite every sentence with the tag of the source you used, copied "
            "exactly as it appears in square brackets in front of that source "
            "below. Only use tags that appear below. Never put section headings, "
            "file names or row numbers in square brackets.\n"
            "- Do not state any number that is not written verbatim in a source.\n"
            "- If the sources do not answer the question, say so plainly.\n"
            "- Be brief: at most four sentences.\n"
            "- MEASURED CONDITIONS below come from NASA's own experimental "
            "tables. If they answer the question, quote those values exactly.\n"
            "- Attribute each statement to the tag in front of the text you "
            "used. The tag is the investigation the text is about.\n"
            + (f"- Binding constraint: {guard}\n" if guard else "")
            + f"\nQuestion: {result['question']}\n"
            + f"\nMEASURED CONDITIONS:\n{conditions}\n"
            + f"\nSources:\n{sources}\n"
        )
        try:
            draft = llm.generate(prompt, system=system, max_tokens=500)
        except llm.LLMUnavailable as e:
            result["verification"] = {"verdict": "skipped", "note": str(e)}
            return result

        # Condition-table values are legitimate sources for numbers, so the
        # verifier must see them too - otherwise quoting PSI's own measured
        # value would be rejected as a fabrication.
        check_against = chunks + [{
            "accession": row["accession"], "acronym": row["acronym"],
            "also_in": [],
            "text": " ".join(str(v["value"]) for v in row["conditions"].values()),
        } for row in result["condition_rows"]]

        verdict, report = verify.enforce(draft, check_against)
        info = llm.describe()
        result["verification"] = {
            "verdict": verdict,
            "backend": info["backend"],
            "model": info.get("model"),
            **report,
        }
        result["prose"] = draft if verdict in ("pass", "flag") else None
        result["blocked_draft"] = draft if verdict == "block" else None
        if verdict == "block":
            result["verification"]["note"] = (
                "Draft was blocked: it contained numbers or citations not present "
                "in the retrieved sources. The evidence ledger below is unaffected.")
        return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def render(res):
    q = res["question"]
    c = res["completeness"]
    print("=" * 78)
    print(f"Q: {q}")
    print("=" * 78)
    print(f"searched   : {c['chunks_searched']} chunks across "
          f"{c['investigations_searched']}/19 investigations "
          f"[{', '.join(c['retrievers'])}"
          f"{', embeddings' if c['embeddings_active'] else ''}]")
    print(f"matched    : {', '.join(c['matched']) or 'none'}")
    if c["considered_below_threshold"]:
        print(f"near-miss  : {', '.join(c['considered_below_threshold'])}")

    cov = res["coverage"]
    print()
    print(f"QUESTION COVERAGE  {cov['answered']}/{cov['total']} parts answered")
    for p in cov["parts"]:
        mark = {"answered": "OK ", "weak": "~  ", "no_evidence": "XX "}[p["state"]]
        print(f"  {mark} {p['sub_question'][:62]}")
        print(f"       {p['chunks']} chunks | {', '.join(p['investigations']) or '-'}")

    if res["prose"]:
        print()
        print("ANSWER")
        print(res["prose"])
    v = res["verification"]
    if v:
        print()
        who = (f" [{v['backend']}:{v['model']}]"
               if v.get("backend") and v.get("model") else "")
        if "numbers" in v:
            print(f"GROUNDING: {v['verdict'].upper()}{who}  "
                  f"numbers "
                  f"{v['numbers']['supported']}/{v['numbers']['numbers_checked']} "
                  f"verbatim | citations "
                  f"{len(v['citations']['valid'])} valid, "
                  f"{len(v['citations']['invalid'])} invalid")
            for u in v["numbers"]["unsupported"]:
                print(f"  rejected number {u['value']!r} in: {u['sentence'][:88]}")
            for u in v["numbers"]["unit_mismatch"]:
                print(f"  unit mismatch {u['value']!r} in: {u['sentence'][:88]}")
        else:
            print(f"GROUNDING: {v['verdict'].upper()}{who}")
        if v.get("note"):
            print(f"  {v['note']}")
        if res.get("blocked_draft"):
            print("  blocked draft (not shown to users):")
            print(f"    {res['blocked_draft'][:220]}")

    print()
    print(f"EVIDENCE LEDGER  ({len(res['evidence_ledger'])} items)")
    for i, r in enumerate(res["evidence_ledger"], 1):
        loc = r["file"] if r["source_type"] == "document" else r["section"]
        page = f" p.{r['page']}" if r.get("page") else ""
        also = (f"  [also cited for {', '.join(a for a in r['cites'] if a != r['investigation'])}]"
                if len(r["cites"]) > 1 else "")
        filed = (f"  (text is about {r['about_acronym'] or r['about']})"
                 if r.get("about") else "")
        label = (f"{r['about_acronym'] or r['about']} via {r['acronym'] or r['investigation']}"
                 if r.get("about") else (r['acronym'] or r['investigation']))
        print(f"  {i:2d}. {label:30} "
              f"{r['evidence_kind']:15} {r['evidence_level']:13}")
        print(f"      {loc}{page}{also}{filed}")
        print(f"      \"{r['claim_source'][:190].replace(chr(10), ' ')}...\"")

    if res["condition_rows"]:
        print()
        print(f"TESTED CONDITIONS  (from experimental tables; "
              f"{res['condition_rows_available']} rows available)")
        for r in res["condition_rows"]:
            vals = "  ".join(f"{k}={v['value']}" for k, v in r["conditions"].items())
            print(f"  {r['acronym'] or r['accession']:14} {vals[:88]}")
            print(f"       source: {r['file']} row {r['row']}")

    print()
    print("GAP RADAR  (what NASA's data does not tell you)")
    if not res["gap_radar"]:
        print("  no gaps detected for this question")
    for g in res["gap_radar"]:
        icon = {"hard": "!!", "soft": " !", "info": "  "}[g["severity"]]
        print(f"  {icon} [{g['kind']}] {g['message']}")
    print()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = [a for a in sys.argv[1:]]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if not args:
        print(__doc__)
        return 1
    led = EvidenceLedger()
    res = led.compose_prose(led.ask(" ".join(args)))
    if as_json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
    else:
        render(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
