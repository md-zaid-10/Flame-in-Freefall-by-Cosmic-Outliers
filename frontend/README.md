# FlameScope frontend (experimental)

A standalone page for the demo video and judges. Nothing else imports this folder,
so deleting `frontend/` removes it.

```bash
venv/bin/python frontend/serve.py        # http://localhost:8765  (prepared + live questions)
open frontend/index.html                 # prepared questions only, no server needed
```

| Key | Action |
|---|---|
| `1` `2` `3` | the three demo scenarios |
| `→` / `n` | next question |
| `m` | flame map |
| `d` | open / close the “How it works” drawer (technical details) |
| `Esc` / `h` | home |

Screens can be linked directly: `#smoke`, `#oxygen`, `#moon`, `#research`, `#map`, `#method`.

The main screens use plain language only. Verification verdicts, file names, pages, the model name and search methods are in the **How it works** drawer (top right).

- **Flame map**: the BASS-II acrylic-rod runs (oxygen vs airflow) with an oxygen/airflow control. The readout is `model.predict()` evaluated on every slider position at build time, so the browser never re-implements the model. The drawer shows the `model.envelope()` table.
- **Research map**: all 19 investigations grouped by job (flammability, detection, suppression, flame physics) with NASA's own goal and impact sentences, a habitat filter (spacecraft, station, Moon/Mars base, pressurized rover) that re-ranks them using `rag.search()`, and a "Fire safety on Earth" section. Groupings, habitat queries and Earth quotes are in `build_cache.py`; the build fails if a quote is not verbatim in its source or a study is missing.
- **Method**: method, limitations, all searched investigations with DOIs, references and the AI-use disclosure.

## Where every number comes from

| File | Contents |
|---|---|
| `data/psi_file_count.json` | the home-screen file count; rebuild with `python3 frontend/count_psi_files.py` |
| `data/demo.js` | the three prepared answers, ML figures and corpus stats; rebuild with `venv/bin/python frontend/build_cache.py` (add `--keep-answers` to keep the cached AI summaries) |

`build_cache.py` reads `rag.ask()`, `ml/` and `data/rag/corpus_stats.json`. It fails if the
smoke-detector headline quote is no longer found verbatim in a NASA passage, or if the Moon
question stops returning the hard partial-gravity gap. Rebuild it after any change to `rag/` or `ml/`.

`shape.py` trims a `rag.ask()` response to the fields the browser needs.

## Honesty rules this UI follows

- NASA's words are blue-ruled quotes; AI-written text is dashed and labelled. With no language model running there is no AI text at all.
- Any partial-gravity gap (hard or soft) renders the "no data" screen with no AI summary, never an answer.
- The 13.6–22.2% oxygen range is BASS-II's (solid materials). Other NASA experiments (FLEX droplets) used richer oxygen, so the UI never says "anything NASA tested".

## Public site (GitHub Pages)

`.github/workflows/pages.yml` publishes `index.html`, `app.js`, `style.css`, `config.js` and `data/demo.js`
to https://md-zaid-10.github.io/Flame-in-Freefall-by-Cosmic-Outliers/ on every push to `main`
that touches `frontend/`. The scenarios, the example questions in `EXAMPLES` (`build_cache.py`),
the research map, flame map and method page are pre-computed. New questions go to the answer
server on Render (https://flamescope.onrender.com), set in `config.js`; see `deploy/README.md`.
If that server can't be reached, the page shows a short notice instead.

To change what the public site answers: edit `PRESETS` / `EXAMPLES`, run
`venv/bin/python frontend/build_cache.py --keep-answers` (keeps existing answers, asks only new
questions; needs a Groq key or Ollama running), check the results, then commit `frontend/data/demo.js`.
