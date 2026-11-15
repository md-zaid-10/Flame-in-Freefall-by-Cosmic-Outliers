# FlameScope: 30-second demo video

File: `FlameScope_SpaceApps_30s.mp4`. 30.0 s, 1920×1080, 30 fps, H.264 + AAC, normalized to -15 LUFS.

## Voiceover script (AI-generated voice)

| Time | Line |
|---|---|
| 0.5–3.4 s | Fire behaves differently in space. Meet FlameScope. |
| 4.4–10.4 s | Moon bases will breathe oxygen-rich air, yet NASA's fire data is buried in sixty-six thousand files. |
| 10.8–16.3 s | Ask a fire-safety question, and FlameScope answers in NASA's own words, with every source cited. |
| 16.9–22.9 s | It searches NASA's archive, checks every AI-written number against the source, and maps where flames burned in orbit. |
| 23.4–28.7 s | And when NASA has no data, it says so. FlameScope. Fire safety, grounded in evidence. |

## Storyboard

| Scene | Time | Visual | On-screen text |
|---|---|---|---|
| 1. Hook | 0–4.6 s | FlameScope's own particle orb from the home page, slowly rotating | "NASA Space Apps 2026 · Flame in Freefall" / "Introducing FlameScope" / "Fire-safety answers for spacecraft and Moon bases, in NASA's own words." |
| 2. Problem | 4.6–10.6 s | Real "Oxygen: tested vs planned" bar from the Moon scenario; counter to 66,567 over a field of dots (one per ~100 PSI files) | "Moon habitats will run at ≥30% oxygen." / "Earth air is 20.9%. NASA's space fire tests went no higher than 22.2%." / "66,567 NASA PSI files across 24 combustion investigations" |
| 3. Solution | 10.6–17.0 s | The live app: question typed keystroke by keystroke on the home page, then the real answer screen (SAME quote, AI summary label) with a slow push-in | "Turning NASA's combustion archive into cited fire-safety answers" |
| 4. Technology | 17.0–23.0 s | Flame map: oxygen slider moved from 20.9% to 30% (41 real captured states), zooming toward the chart | "Powered by NASA's PSI archive" + 19 investigations · 7,770 passages / BM25 + TF-IDF + embeddings / local LLM, every number checked / 196 airflow steps from BASS-II |
| 5. Impact | 23.0–26.0 s | Moon scenario screen: "NASA's archive has no fire data at Moon gravity" | "Know what NASA measured, and what it never tested" |
| End card | 26.0–30.0 s | Orb, warm light flash, low boom | "FlameScope" / "NASA Space Apps Challenge 2026" / "Team Cosmic Outliers · Flame in Freefall" / disclosure line |

## Assets used

- Screen captures of the FlameScope frontend (`frontend/`, served locally, the same static build as GitHub Pages): home + typing, smoke-detector scenario, flame map slider sequence, Moon scenario.
- The orb animation, ported from `frontend/app.js` (`initOrb`), redrawn frame by frame.
- Figures (66,567 files, 24 investigations, 19 investigations, 7,770 passages, 196 airflow steps, 13.6–22.2% O2 tested, ≥30% Moon base) taken from `README.md`, `frontend/data/psi_file_count.json` and the app's own screens.
- Font: Inter / Inter Display (SIL OFL).
- Voiceover: Kokoro TTS (Apache-2.0), voice `af_heart`.
- Music and sound effects: synthesized from scratch for this video (no third-party audio).
- No NASA logos, no stock footage, no AI-generated imagery.

## AI disclosure for the project page

The voiceover is AI-generated (Kokoro TTS). The video was assembled with AI help (Claude) from real screen captures of the FlameScope app; no AI-generated images are used.
