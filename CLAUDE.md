# FlameScope: NASA Space Apps 2026 (team "Cosmic Outliers")

Context for Claude Code. Read this first; it captures decisions made so far.

## Event
- NASA Space Apps Challenge, Nov 14–15 2026. **Deadline: Sun Nov 15, 23:59 local event time** (target submit 22:00).
- Challenge: **"Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data"**
  https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/
- Goal: strong prototype + pitch. A full production build is not required.

## Problem statement (summary)
NASA's microgravity combustion results live in the Physical Sciences Informatics (PSI) database but are hard to
find, compare and interpret. Build an **AI-powered web dashboard** that summarizes, ranks and interprets combustion
investigations to deliver fire-safety insights for spacecraft, stations, Moon/Mars bases and pressurized rovers.
Suggested features: (1) find investigations most relevant to habitat fire safety, (2) **extract data supporting
predictive modeling of flammability** (this is the ML part), (3) highlight research informing next-gen fire safety
equipment. Optional: Earth applications.

Key facts from the challenge page:
- Moon base / pressurized rovers expected at **>=30% O2 and <=10.2 psi** (spacesuits: 100% O2 at 4.3 psi; Earth 14.7 psi).
  That is >40% more O2 than Earth air, so materials are much more flammable.
- **No partial-gravity combustion data exists in PSI yet** (future: LUCI, FM2). Microgravity and normal-gravity results
  can bound intermediate gravity levels.
- Solid-material flammability: BASS, BASS-II, Saffire I–III. Detection: SAME, SAME-R. Suppression: FLEX (CO2/He dilution).
- Hardware: ACME (6 gas-flame expts, CIR); FLEX/FLEX-2/CFI (droplets, MDCA in CIR); BASS/BASS-II/SPICE/SLICE (MSG flow duct).
- Pitch hooks: Apollo 1 fire (O2-rich cabin), Apollo 13, Mir fire, Artemis II smoke alarm.

## Submission rules
- Demo: max **7 slides** (incl. title) OR video **<=30 s**, English. Over the limit = ineligible for global judging.
- Judging: Impact, Creativity, Validity, Relevance, Presentation; judged mostly on the project page.
- All links public, no login. Cite PSI DOIs. Disclose AI use (watermark AI images, note AI-written code/data).
  No NASA logos in AI-generated content. The AI must not come up with the solution idea itself.
- PSI is the core data source. Other public sources are OK as cited supplements.

## Team and ownership (work in parallel, separate folders)
| Person | Area | Folder |
|---|---|---|
| Zaid | ML: microgravity flammability model, labels, uncertainty, `predict()` | `ml/microgravity/`, `ml/model.py` |
| ML teammate | Flow-string parser, material-name normalization, 1 g published baseline, Moon bound, LLM-vs-hand-label validation script | `ml/gravity_bounds/`, parser in `ml/` |
| Ananya | RAG/LLM: search, ranking, summaries, Q&A, LLM label extraction | `rag/` |
| (3rd member, if separate) | Streamlit dashboard, project page, slides | `app.py`, `pages/`, `docs/` |

Rules: don't edit another person's folder; changing an interface needs team agreement; commit small and often.
Integration point: **Sunday ~14:00**; feature freeze ~18:00.

## Interfaces (agreed contracts; stubs first, real later)
```python
# ml/model.py
predict(material, thickness_mm, o2_pct, flow_cm_s, pressure_kpa, gravity_g)
    -> {"p_burn": float, "low": float, "high": float}
boundary(material, gravity_g) -> DataFrame[flow_cm_s, o2_min, low, high]

# rag/search.py
search(query, k=5) -> [{"id", "title", "score", "snippet", "doi"}]
summarize(psi_id) -> {"objective", "fuels", "conditions", "measurements", "relevance"}
ask(question) -> {"answer": str, "sources": [psi_id, ...]}
```
Shared clean-table schema (`ml/data/<psi_id>_clean.csv`):
`psi_id, run_id, material, thickness_mm, o2_pct, flow_cm_s, pressure_kpa, gravity_g, outcome, raw_notes, label_source`
with outcome in {burn, extinguish, blowoff, no_ignition} and label_source in {hand, llm}.

## Data (downloaded; open, CC0)
- `python3 data/fetch_psi.py [PSI-ID ...]` downloads investigation JSON + experimental tables (stdlib only,
  falls back to curl for macOS SSL). Raw videos and data are NOT downloaded (BASS-II raw alone is ~256 GB).
- API: `https://psi.nasa.gov/geode-py/ws/repo/investigations/{PSI-ID}`; table download:
  `.../ws/studies/{study_id}/download?file=...&version=...&redirect=false` -> pre-signed S3 URL.
- Outputs:
  - `data/metadata.json`: per-study title, DOI, objective, hypothesis, approach, researchImpacts, publications (for RAG)
  - `data/raw/investigations/PSI-*.json`: full records (~23 MB; not committed)
  - `data/raw/tables/PSI-*/...csv`: experimental tables (21 files across 18 studies)
- Studies: PSI-26 BASS, PSI-25 BASS-II, PSI-98/99/100 Saffire I–III, PSI-102 SAME, PSI-101 SAME-R, PSI-69 FLEX,
  PSI-68 FLEX-2, PSI-39 CFI, PSI-159 ACME CFI-G, PSI-10 ACME Flame Design, PSI-20 ACME BRE, PSI-21 ACME CLD,
  PSI-22 ACME E-FIELD, PSI-23 ACME s-Flame, PSI-107 SPICE, PSI-106 SLICE; ground studies PSI-117, 62, 60, 142, 115.

## Findings from inspecting the data (important)
- **Main ML file: `data/raw/tables/PSI-25/PSI-25_Experimental table_BASS-II.csv`**: 129 ISS runs.
  Columns: PI, Test #, Date, GMT, Sample #, Fuel Sample Material, Flow restrictor, Fan display, Air display,
  Radiometer gain, Total Frames Shot, Calibrated initial/final O2 % by vol, Initial/Final CO2 %, Initial/Final CO (ppm).
  File has a UTF-8 BOM, so read with `encoding="utf-8-sig"`.
- **No outcome column.** Outcomes appear only as free text in Fan/Air display ("ext" x23, "blowoff" x8,
  "extinguished" x2), roughly 30 runs. The rest need hand labeling (notes, O2 change, publications).
- Many runs step airflow down until extinction, e.g. `"pot 0.9 0.5 and down" / "5 3 2 ext"`,
  `"1.7 (52) 1.25 0.9 0.6 0.4 0.35" / "5 4 3 2 1"`. One run yields several (flow, outcome) points:
  burn at each step, extinguish at the last. Parsing these is the biggest data source.
  "pot" = fan potentiometer value; numbers in parentheses are likely fan display values; Air display ~ cm/s.
- 49 distinct material spellings: mostly PMMA films (0.1–0.4 mm), PMMA slabs (1–5 mm, 1 or 2 sided),
  clear/black PMMA rods (1/4", 3/8", 1/2"), SIBAL (1 or 2 cm), Nomex, one candle. Normalize to material + thickness.
- PIs: T'ien 29, Olson 27, Fernandez-Pello 27, Bhattacharjee 22, Miller 20, Ferkul 4.
- **O2 range tested: 13.6–22.2%.** The Moon base (>=30%) is far outside, so no reliable prediction there.
  Honest framing: "materials burned well below 30% O2 in microgravity, so a 30% Moon base has no flammability
  margin for these materials." Label any 30% point as extrapolation.
- No pressure column (assume ISS cabin conditions; verify from publications before stating).
- **PSI-26 BASS table has no O2/flow** (only date, test #, sample, material), so it is RAG/context only.
- **Ground studies have no flammability tables** (PSI-117/62/60/115 none; PSI-142 is links to cool-flame papers).
  The 1 g baseline must come from cited published values (e.g. PMMA limiting oxygen index).
- Saffire tables are tiny (a few rows): pitch/validation only. SAME/SAME-R: smoke. FLEX/CFI/ACME/SPICE/SLICE: droplets or gas flames, for Ananya.

## ML plan (Zaid)
1. Labeling sheet `ml/microgravity/bass2_labels.csv`: run_id, material, thickness_mm, o2_pct, flow_cm_s,
   outcome, confidence, notes. Pre-fill rows with explicit ext/blowoff text. Hand-label the rest (~1 h).
2. Parse multi-step flow sequences into per-step rows.
3. Model: logistic regression (burn vs extinguish) on O2 + flow per material class; bootstrap for uncertainty.
4. Extinction boundary plot (min O2 vs flow) with the Moon-base 30% line marked as beyond the tested range;
   1 g published value as the other bound.
5. Expose `predict()` / `boundary()` in `ml/model.py`.
6. Validity metric: accuracy of Ananya's LLM-extracted labels vs hand labels.

## Environment
- macOS, Python 3. Streamlit app in `app.py`. A `venv/` (conda) exists in the repo root and is git-ignored.
