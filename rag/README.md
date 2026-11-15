# RAG layer — grounded retrieval over NASA PSI combustion research

Answers questions about NASA's microgravity combustion investigations using only
PSI's own documents, and says so when PSI cannot answer. Independent of `ml/` —
no shared state, no import in either direction.

## Why it is built this way

Scientists do not act on "the AI said so". Three things make an answer usable:
the source is one click away, the numbers come from NASA's tables rather than a
model, and the system reports what the data cannot support. So the output is not
a chat reply but an **evidence ledger**: one row per retrieved item, each with
its investigation, file, page and evidence depth.

The only component that can invent anything is the prose layer, and it is the
one component we do not trust. `rag/verify.py` checks every number in a draft
verbatim against the retrieved sources and every citation against what was
actually retrieved, and blocks the draft if either fails. That check is
mechanical, so the guarantee comes from the architecture, not from the model —
which is why it runs fine on a local 7B.

## Quick start

```bash
pip install -r requirements.txt

python data/fetch_psi.py                      # shared: metadata + tables
python -m rag.prep.build_manifest             # list the document files in PSI
python -m rag.prep.download_documents         # ~700 MB, gitignored
powershell -File rag/prep/convert_legacy_office.ps1   # .doc/.ppt -> .docx/.pptx
python -m rag.prep.check_extraction           # what text is actually usable
python -m rag.corpus                          # build chunks + condition rows
python -m rag.enrich                          # attribution + near-dup keys

python -m rag.answer "Which experiments burned PMMA samples?"
python -m rag.evaluate --k 5                  # measured scorecard
```

`data/rag/chunks.jsonl` and `conditions.jsonl` are committed, so the first three
steps are only needed to rebuild from scratch. Embeddings regenerate on first
retrieval (~1 min) and are gitignored.

The answer layer uses **Groq** when `GROQ_API_KEY` is set (free tier, fast), and
otherwise a local **Ollama** model (`qwen2.5:7b`) with no key and no network. If
Groq fails or hits its rate limit, it falls back to Ollama. `FIF_LLM` forces one
backend (`groq`, `ollama` or `anthropic`). With no model reachable, the evidence
ledger still works.

## Using it from Python

```python
from rag.answer import EvidenceLedger

led = EvidenceLedger()                     # cache this; it loads the index
res = led.compose_prose(led.ask("Which experiments burned PMMA samples?"))

res["prose"]            # cited summary, or None if grounding blocked it
res["evidence_ledger"]  # rows: investigation, file, page, evidence_level, text
res["condition_rows"]   # measured values straight from PSI's CSVs
res["gap_radar"]        # what the corpus cannot support
res["completeness"]     # chunks and investigations searched, near-misses
res["verification"]     # verdict + which numbers/citations were rejected
```

The frontend uses the simpler `rag/search.py` interface (`search`, `summarize`, `ask`).

## Modules

| Module | Role |
|---|---|
| `corpus.py` | builds chunks from `data/metadata.json`, `data/raw/tables/`, `data/raw/documents/` |
| `enrich.py` | fixes shared-document attribution; keys near-duplicate chunks |
| `retrieve.py` | hybrid BM25 + TF-IDF + embeddings, fused by RRF; completeness report |
| `decompose.py` | splits compound questions; blocks partial-gravity extrapolation |
| `verify.py` | verbatim number and citation grounding |
| `answer.py` | orchestrates all of the above into the evidence ledger |
| `llm.py` | Groq / Ollama / Anthropic backend, with Ollama as fallback |
| `evaluate.py` | runs `data/rag/gold_set.json` and prints the scorecard |
| `prep/` | one-off ingestion: manifest, download, legacy conversion, extraction check |

## Corpus

PSI's combustion search returns 26 investigations. Two are keyword false
positives (solder metallurgy, surface-tension convection). Of the remaining 24,
**19 have usable documents**; the other five publish raw instrument data only.
`data/rag/EXCLUDED_INVESTIGATIONS.md` records every exclusion and the four files
that are broken on NASA's own servers.

Retrievable corpus: ~7,800 chunks and ~1,950 condition rows across 19
investigations, from 212 documents.

Coverage is very uneven and the UI should say so. ACME BRE has ~1,600 chunks;
SAFFIRE-I has 1. Ranking must weight PSI's `researchArea` metadata, not document
volume, or every fire-safety question returns ACME — which is gaseous-fuel
combustion, not spacecraft fire safety.

## Measured results

`python -m rag.evaluate` against 26 hand-built cases in `data/rag/gold_set.json`,
whose expected investigations were derived by counting term occurrences in the
built corpus rather than guessed.

| Metric | Result |
|---|---|
| Recall@5 | 18/18 |
| Recall@3 | 18/18 |
| Recall@2 | 17/18 |
| Negative (correct refusal) | 4/4 |
| Decomposition | 2/2 |
| Dedup integrity | 1/1 |

Operating point is k=5–6. At k=4 the prose layer starts getting blocked for
ungrounded numbers — the gate working as intended, not a regression.

## Known limitations

- **Wrong attribution between two retrieved investigations is not caught.**
  `verify.py` proves a citation points at something retrieved, not that it
  supports the sentence. Shared PSI documents make this real: a FLEX objective
  sits inside a file filed under ACME. `enrich.py` reassigns a chunk only when
  another investigation is named early and repeatedly, which is precise but not
  complete.
- **No partial-gravity data exists in PSI.** This is enforced, not just noted:
  lunar and Mars questions get a hard warning and the prose layer is instructed
  not to extrapolate.
- **The local 7B writes awkwardly** — it has produced "ranging from 0.44 to 0.44".
  Grounded, but clumsy; a prompt fix, not a correctness one.
- **Condition-column matching is heuristic.** PSI's CSV headers are inconsistent
  across investigations, so a value may occasionally be labelled with the wrong
  condition name. The value and its source row are always shown verbatim.
