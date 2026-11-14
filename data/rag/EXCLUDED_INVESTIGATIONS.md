# Excluded Investigations — Documented Coverage Gaps

PSI combustion search (`term=combustion&source=psi&type=investigation`) returns **26**
investigations. Our RAG corpus uses **19**. This file records the 7 we excluded and why,
so the gap can be surfaced honestly in the application rather than hidden.

Verified: 2026-11-14, against the live PSI API.

---

## Category A — Off-topic (keyword false positives): 2

These matched the word "combustion" incidentally; they are not combustion research.

| Accession | Title | Research area | Reason |
|---|---|---|---|
| PSI-181 | Structure and Properties of Pb-Sn and Pb-free Sn-Ag-Cu Solders | Materials Science (solder joints) | Metallurgy, not combustion |
| PSI-108 | Surface Tension Driven Convection Experiment-1 (STDCE-1) | Fluid Physics | Thermocapillary convection, not combustion |

## Category B — No usable documents in PSI: 5

These ARE legitimate combustion investigations, but PSI hosts **no Science Documents,
Reports or Presentations** for them. Only raw instrument data and/or a metadata archive.
There is no natural-language text to retrieve, so RAG cannot ground an answer on them.

| Accession | Acronym | Doc files | What PSI actually holds |
|---|---|---|---|
| PSI-62  | —              | 0 | Metadata archive only. Ground CFD study: "Concurrent Flame Spread Modeling using Flamelet Generated Manifolds" |
| PSI-60  | —              | 0 | Metadata archive only. Ground study: "Computational and Experimental Analysis of SPICE Data Sets" |
| PSI-106 | SLICE          | 1 | 23,461 raw data files, 1 experimental table, zero documents |
| PSI-21  | ACME CLD Flame | 1 | 4,881 raw data files, 1 experimental table, zero documents |
| PSI-142 | —              | 1 | 1 experimental table. Ground study: "Quantitative Studies of Cool Flame Transitions at Radiation / Stretch Limits" |

### How this should appear in the application

1. These 5 remain **listed in the experiment catalogue** with their PSI metadata, so the
   catalogue reflects what NASA actually holds — 24 combustion investigations, not 19.
2. Each is flagged `evidence_level: "metadata_only"` (or `"none"` for PSI-62 / PSI-60).
3. The RAG assistant must **never** cite them as a source of findings. If a query is
   relevant to them, the answer should say the investigation exists but PSI publishes no
   analysable documents for it.
4. SLICE is the most significant loss: 23,461 raw data files and no published
   interpretation of them in PSI. Worth naming explicitly as a research-accessibility gap.

---

## Thin but INCLUDED (not excluded — flag as low evidence depth)

| Accession | Acronym | Doc files |
|---|---|---|
| PSI-159 | ACME CFI-G | 3 |
| PSI-115 | — | 2 |
| PSI-117 | — | 5 |
| PSI-68  | FLEX-2 | 4 |
| PSI-98  | SAFFIRE-I | 5 |
| PSI-99  | SAFFIRE-II | 5 |
| PSI-25  | BASS-II | 5 |

## Richest coverage

| Accession | Acronym | Doc files |
|---|---|---|
| PSI-22 | ACME E-FIELD Flames | 47 |
| PSI-20 | ACME BRE | 34 |
| PSI-23 | ACME s-Flame | 27 |
| PSI-26 | BASS | 12 |

---

## Separate, larger gap: partial gravity

Independent of the above. PSI holds **no partial-gravity (Moon ~1/6 g, Mars ~1/3 g)
combustion data** — every flight investigation here is microgravity (ISS, Cygnus, Shuttle).
Microgravity results must not be presented as predictive of lunar or Martian fire behaviour.
This constraint is stated in the challenge brief itself and should be enforced in the
application, not merely mentioned.

---

## Appendix — Broken files on NASA's side (4)

Found while downloading, 2026-11-14. These are listed in PSI's file metadata but the
stored object is missing or damaged. Our download code is not at fault: PSI returns a
valid presigned URL for each, and in the last case the bytes we received match the
advertised size exactly.

| Investigation | File | Problem |
|---|---|---|
| PSI-100 SAFFIRE-III | `..._Presentations_SAFFIRE_45 I Con of Env Sys presentation.pdf` | S3 object absent (404) at `legacy/97837/284/` |
| PSI-100 SAFFIRE-III | `..._Presentations_SAFFIRE_46th I Con of Env Sys presentation.pdf` | S3 object absent (404) |
| PSI-100 SAFFIRE-III | `..._Presentations_SAFFIRE_47th I Con of Env Sys presentation.pdf` | S3 object absent (404) |
| PSI-22 ACME E-FIELD | `..._Presentations_Chien et al 2018 Electric-Field Effects on Flames in Microgravity.pdf` | Downloads fully (1,674,645 bytes, matches metadata) but is not a valid PDF — no `%PDF` header. Re-fetch reproduces the same bytes, so the stored object itself is corrupt. |

All four are conference presentations, not primary science documents, so the loss to the
corpus is limited. PSI-100's underlying findings remain covered by its 5 surviving
Science Documents; PSI-22 retains 46 other files.

**Corpus total actually retrieved: 212 of 216 advertised files.**
