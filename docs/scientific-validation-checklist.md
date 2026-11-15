# Scientific validation checklist: cached AI summaries

Three AI summaries in `frontend/data/demo.js` passed the automatic check but may misread or misattribute
NASA's text. The checker only confirms that each number and citation tag appears somewhere in the
retrieved sources. It does not check that a sentence reads them correctly.

On the site, these summaries carry the label "AI summary · not NASA's words" plus a note telling readers to
trust NASA's passages. **They have not been rewritten.** For each item, a team member should read the source
pages and record a decision below.

Possible decisions:
- **keep**: the summary is accurate.
- **drop**: remove the question from `EXAMPLES` in `frontend/build_cache.py`.
- **regenerate**: delete its cached answer and rebuild.

Never hand-edit `demo.js`, and never rewrite the AI text by hand.

## 1. FLEX droplet sizes

**Question:** "What size droplets were burned in FLEX?"

**Cached AI summary (verbatim):**
> [FLEX-2] The droplets burned in FLEX had a diameter range of 1.5 to 5 mm. [FLEX]

**What the sources show:**
- The only diameter range in the displayed passages is the FLEX-2 Science Requirements Document,
  PSI-68, p.61, DOI 10.60555/byp8-h018. It says *"initial droplet diameters in the range 3 to 5 mm"*.
  That sentence is a design estimate ("assuming an average burning rate constant…"), not a measured result.
- **1.5 mm does not appear in any passage shown to users.** The checker accepted it from somewhere in
  the source text. One candidate is the "1.5" atm pressure value in the FLEX-2 table, which would be a
  unit mismatch. Not confirmed.
- The question asks about FLEX (PSI-69), but no FLEX passage was retrieved. The evidence is FLEX-2 and
  CFI only.

**To check:**
- [ ] Find where "1.5" comes from in the retrieved chunks.
- [ ] Check whether FLEX (PSI-69) publishes measured initial droplet diameters. The FLEX table rows show
  values such as 1.61–1.86 mm.
- [ ] Decision: keep / drop / regenerate. Reviewer: ____

## 2. CO2 vs helium for putting out fires

**Question:** "Is CO2 or helium better at putting out fires in space?"

**Cached AI summary (verbatim):**
> [PSI-117] Helium produces the maximum burning rate, largest extinction diameter, and shortest burn
> time. Carbon dioxide has the lowest burning rate. [PSI-117]

**What the sources show:**
- Both sentences match text in the PSI-117 dissertation, p.73, DOI 10.60555/gz0q-b577.
- These are **numerical simulation results** for a 1.5 mm droplet at 21% O2 (*"The simulation results
  presented in this figure are for Do = 1.5 mm, XO2 = 21%"*), not ISS measurements. PSI-117 is a ground
  investigation.
- The summary does not answer the question ("which is better at putting out fires"). It reports burning
  rate and extinction diameter, which a reader may take as a recommendation.

**To check:**
- [ ] Is it acceptable to present simulation results under this question? If so, should the summary say
  they come from a simulation?
- [ ] Does any PSI source, for example FLEX (PSI-69), which tested CO2 and He dilution, directly compare
  how well they suppress fire?
- [ ] Decision: keep / drop / regenerate. Reviewer: ____

## 3. Ultem and Nomex attribution

**Question:** "Which spacecraft materials did not burn on the ISS?"

**Cached AI summary (verbatim):**
> [SAFFIRE-I] Ultem and Nomex HT90-40 samples did not burn on ISS atmosphere. [BASS]

**What the sources show:**
- The sentence comes almost word for word from **BASS** (PSI-26, "Overview of Recent ISS Results",
  p.30, DOI 10.60555/58h4-dy80): *"Ultem and Nomex HT90-40 samples did not burn on ISS atmosphere 21% to
  22% O2 Flow speeds around 15 cm/s"*.
- The summary opens with a **[SAFFIRE-I]** tag. Saffire-I flew on an uncrewed Cygnus cargo vessel, not
  the ISS, and its retrieved passage (metadata) does not mention Ultem or Nomex. Readers may credit the
  result to the wrong experiment.
- The summary drops the test conditions (21–22% O2, about 15 cm/s), and the same slide notes that a
  *"Nomex-III sample did burn"*.

**To check:**
- [ ] Confirm whether the answer format places the tag before or after the sentence it supports.
- [ ] Decide whether a misplaced tag is acceptable when the correct source ([BASS]) is also present.
- [ ] Decision: keep / drop / regenerate. Reviewer: ____

## Separate issue: research ranking ties (`rag/search.py`, owner: Ananya)

This is not an AI-summary problem, but it affects the research rankings shown on the site.

- **Cause:** `search()` sorts investigations by score alone: `sorted(agg.items(), key=lambda kv: -kv[1]["score"])`.
  When two studies have exactly the same score, their order depends on Python's per-process hash seed, so
  it can flip from one run to the next.
- **Example:** Saffire-II (PSI-99) and Saffire-III (PSI-100) both score 0.05501 for "all habitats". Running with `PYTHONHASHSEED=1`/`2` puts PSI-99 first; `3`/`4` puts PSI-100
  first. All five habitat rankings contain at least one tie.
- **Current workaround (frontend only):** `keep_tie_order()` in `frontend/build_cache.py` keeps the
  published order on `--keep-answers` rebuilds. It applies only when the studies and scores are identical.
  `rag/search.py` was **not** modified.
- **Suggested fix for Ananya to decide:** add a deterministic tie-breaker, for example
  `key=lambda kv: (-kv[1]["score"], kv[0])`. This may reorder currently tied studies once. If adopted,
  rebuild the cache and re-approve the research order.
- [ ] Decision: ____ Owner: Ananya

## Already resolved

The oxygen summary "a flame can self-extinguish at an oxygen mole fraction as low as 0.21, which is
significantly lower than the 21% found in Earth's atmosphere" misread 0.21 mole fraction and 21% as
different values. It was never displayed, and it is no longer stored. Answers are now not stored for
screens that never show one (`drop_unshown_answer` in `frontend/build_cache.py`).
