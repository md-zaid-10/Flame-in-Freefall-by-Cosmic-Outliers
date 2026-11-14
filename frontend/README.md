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

Screens can be linked directly: `#smoke`, `#oxygen`, `#moon`, `#map`, `#method`.

The main screens use plain language only. Verification verdicts, file names, pages, the model name and search methods are in the **How it works** drawer (top right).

- **Flame map**: the BASS-II acrylic-rod runs (oxygen vs airflow) with an oxygen/airflow control. The readout is `model.predict()` evaluated on every slider position at build time, so the browser never re-implements the model. The drawer shows the `model.envelope()` table.
- **Method**: method, limitations, all searched investigations with DOIs, references and the AI-use disclosure.

## Where every number comes from

| File | Contents |
|---|---|
| `data/psi_file_count.json` | the home-screen file count; rebuild with `python3 frontend/count_psi_files.py` |
| `data/demo.js` | the three prepared answers, ML figures and corpus stats; rebuild with `venv/bin/python frontend/build_cache.py` (add `--keep-answers` to keep the cached AI summaries) |

`build_cache.py` reads `rag.ask()`, `ml/` and `data/rag/corpus_stats.json`. It fails if the
smoke-detector headline quote is no longer found verbatim in a NASA passage, or if the Moon
question stops returning the hard partial-gravity gap. Rebuild it after any change to `rag/` or `ml/`.

`shape.py` hides condition values whose column is mislabelled by `rag/answer.py`
(CO2 columns matched as "oxygen", "Flow restrictor" matched as "flow"). Remove it once that is fixed in `rag/`.

## Honesty rules this UI follows

- NASA's words are blue-ruled quotes; AI-written text is dashed and labelled. With no language model running there is no AI text at all.
- Any partial-gravity gap (hard or soft) renders the "no data" screen with no AI summary, never an answer.
- The 13.6–22.2% oxygen range is BASS-II's (solid materials). Other NASA experiments (FLEX droplets) used richer oxygen, so the UI never says "anything NASA tested".
