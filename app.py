"""FlameScope: fire-safety insights from NASA microgravity combustion data (PSI).

Run:  ./venv/bin/streamlit run app.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "ml"))
import model  # noqa: E402
from gravity_bounds import baselines  # noqa: E402
from microgravity import flammability as flam  # noqa: E402

try:  # Ananya's RAG module; optional until it lands
    from rag import search as rag  # noqa: E402
    HAVE_RAG = True
except Exception:
    HAVE_RAG = False

BURN, NOBURN = "#2a78d6", "#eb6834"
PSI_TO_KPA = 6.89476
BASS2_DOI = "10.60555/4qc4-de67"

st.set_page_config(page_title="FlameScope", page_icon="🔥", layout="wide")


# ---------------- data ----------------
@st.cache_data
def runs():
    return flam.load_training()


@st.cache_data
def metadata():
    return json.loads((ROOT / "data/metadata.json").read_text())


@st.cache_data
def consistency():
    p = ROOT / "ml/microgravity/handcheck_results.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p)
    return {"n": len(d), "agree": float((d["hand_outcome"] == d["outcome"]).mean())}


def fmt_pct(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.0%}"


# ---------------- header ----------------
lim = model.limiting_o2()
g1 = baselines.PMMA_ROD["normal_gravity_bracket"]
moon = baselines.HABITAT["moon_base_o2_min"]

st.title("🔥 FlameScope")
st.markdown("**How flammable are spacecraft materials, and how much margin does a "
            "Moon base have?** Built on NASA Physical Sciences Informatics (PSI) "
            "microgravity combustion data.")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Lowest O₂ where PMMA rods burned (µg)", f"≈{lim['low']:.1f}%",
          help="BASS-II, ISS. Our runs bracket the limit at "
               f"{lim['low']:.1f}–{lim['high']:.1f}%; published value 13.6%.")
c2.metric("Same rods on Earth (1 g) go out at", f"{g1['low']:.0f}%",
          help="Marcum, Olson & Ferkul 2016 (NASA NTRS 20160012691)")
c3.metric("Planned Moon base / rover O₂", f"≥{moon:.0f}%",
          help="Challenge statement: ≥30% O₂ at ≤10.2 psi")
c4.metric("Margin above the microgravity limit", f"+{moon - lim['low']:.0f} pts",
          delta="no safety margin", delta_color="inverse")

tab_map, tab_hab, tab_search, tab_about = st.tabs(
    ["Flammability explorer", "Habitat check", "Research finder", "Method & sources"])

# ---------------- 1. flammability explorer ----------------
with tab_map:
    left, right = st.columns([1, 2.4])
    with left:
        st.subheader("Will it keep burning?")
        material = st.selectbox("Material", ["PMMA rod (acrylic)", "PMMA film",
                                             "PMMA slab", "SIBAL fabric"])
        o2 = st.slider("Oxygen (% by volume)", 10.0, 35.0, 21.0, 0.1)
        flow = st.select_slider("Air flow past the sample (cm/s)",
                                options=[0.5, 1, 1.5, 2, 3, 5, 7, 10, 15, 20, 30],
                                value=5,
                                help="Ventilation flow. On Earth buoyancy creates ~30 cm/s "
                                     "of flow; in microgravity only fans move air.")
        res = model.predict(material, None, o2, flow)
        if not model.is_supported(material):
            st.info("**Insufficient data.** Only PMMA rods have enough BASS-II "
                    "extinctions to estimate a limit. No data is not the same as safe.")
        elif math.isnan(res["p_burn"]):
            st.info("**No ISS runs in this region.** Below the tested O₂ range the model "
                    "does not predict.")
        else:
            st.metric("Observed burn rate in similar ISS runs", fmt_pct(res["p_burn"]),
                      help="Share of BASS-II runs in this O₂ / flow cell whose flame "
                           "survived, counted once per run.")
            st.caption(f"95% interval: {fmt_pct(res['low'])} – {fmt_pct(res['high'])}")
            if model.is_extrapolation(o2):
                st.warning(f"**Extrapolation.** {o2:.1f}% O₂ is outside the tested range "
                           f"({model.TESTED_O2_RANGE[0]}–{model.TESTED_O2_RANGE[1]}%). "
                           "Shown as a lower bound: more oxygen does not make burning "
                           "less likely.")
            if o2 >= lim["high"] and 1 <= flow <= 10:
                st.error("Above the microgravity limit in the most dangerous flow window "
                         "(1–10 cm/s).")
        st.caption("Pressure and gravity are not modeled: BASS-II ran in microgravity at "
                   "ISS cabin pressure.")

    with right:
        d = runs()
        rng = np.random.default_rng(1)
        x = d["flow_cm_s"].where(d["flow_cm_s"] >= 1, 0.6) * np.exp(rng.uniform(-.06, .06, len(d)))
        y = d["o2_pct"] + rng.uniform(-.08, .08, len(d))
        fig = go.Figure()
        fig.add_hrect(y0=model.TESTED_O2_RANGE[1], y1=33, fillcolor="gray", opacity=0.08,
                      line_width=0, annotation_text="not tested on ISS",
                      annotation_position="top left")
        fig.add_hrect(y0=lim["low"], y1=lim["high"], fillcolor="gray", opacity=0.25,
                      line_width=0)
        for yv, txt, dash in [(moon, "Moon base ≥30%", "solid"),
                              (20.9, "Earth air / ISS 20.9%", "dot"),
                              (g1["high"], "1 g: burns at 15%, out at 14%", "dash"),
                              (lim["low"], "µg limit ≈13.6%", "solid")]:
            fig.add_hline(y=yv, line_dash=dash, line_width=1.5 if yv == moon else 1,
                          annotation_text=txt, annotation_position="right")
        for yv_, name, color, sym in [(1, "Kept burning", BURN, "circle"),
                                      (0, "Went out / no ignition", NOBURN, "x")]:
            m = d["y"] == yv_
            fig.add_trace(go.Scatter(
                x=x[m], y=y[m], mode="markers", name=name,
                marker=dict(color=color, symbol=sym, size=8,
                            line=dict(width=0.8, color="white")),
                customdata=np.stack([d.loc[m, "run_id"], d.loc[m, "o2_pct"],
                                     d.loc[m, "flow_cm_s"], d.loc[m, "outcome"]], axis=1),
                hovertemplate="Run %{customdata[0]}<br>O₂ %{customdata[1]}%<br>"
                              "flow %{customdata[2]} cm/s<br>%{customdata[3]}<extra></extra>"))
        fig.add_trace(go.Scatter(x=[flow], y=[o2], mode="markers", name="Your query",
                                 marker=dict(symbol="star", size=18, color="#6250d6",
                                             line=dict(width=1, color="white")),
                                 hovertemplate="Your query<extra></extra>"))
        fig.update_layout(
            height=560, margin=dict(l=10, r=170, t=30, b=10),
            xaxis=dict(type="log", title="Air flow (cm/s)", range=[math.log10(0.42), math.log10(42)],
                       tickvals=[0.6, 1, 2, 5, 10, 20, 40],
                       ticktext=["<1", "1", "2", "5", "10", "20", "40"]),
            yaxis=dict(title="Oxygen (% by volume)", range=[12.5, 33]),
            legend=dict(orientation="h", y=1.06, x=0), hovermode="closest")
        st.plotly_chart(fig, width="stretch", theme="streamlit")
        st.caption(f"PMMA rods, NASA PSI BASS-II (DOI {BASS2_DOI}). Each point is one flow "
                   "step of an ISS run; outcomes extracted from operator notes with LLM "
                   "assistance. Flows <1 cm/s are fan-setting estimates; points jittered.")

# ---------------- 2. habitat check ----------------
with tab_hab:
    st.subheader("Where do crewed habitats sit relative to the microgravity limit?")
    habitats = pd.DataFrame([
        ("Earth sea level", 20.9, 14.7, "reference"),
        ("ISS cabin", 20.9, 14.7, "BASS-II test conditions"),
        ("Moon base / pressurized rover (planned)", 30.0, 10.2, "challenge statement"),
        ("Spacesuit", 100.0, 4.3, "challenge statement"),
    ], columns=["Environment", "O₂ %", "Pressure (psi)", "Source"])
    custom = st.expander("Add your own environment")
    with custom:
        co2 = st.number_input("O₂ %", 10.0, 100.0, 34.0)
        cp = st.number_input("Pressure (psi)", 1.0, 20.0, 8.2)
        if st.checkbox("Include it"):
            habitats.loc[len(habitats)] = ["Custom", co2, cp, "user input"]
    h = habitats.copy()
    h["O₂ partial pressure (kPa)"] = (h["O₂ %"] / 100 * h["Pressure (psi)"] * PSI_TO_KPA).round(1)
    h["Points above µg limit"] = (h["O₂ %"] - lim["low"]).round(1)
    h["Within ISS-tested O₂?"] = np.where(h["O₂ %"] <= model.TESTED_O2_RANGE[1], "yes",
                                         "no: extrapolation")
    st.dataframe(h, hide_index=True, width="stretch")
    st.markdown(
        f"- In microgravity, PMMA rods sustained flames down to **≈{lim['low']:.1f}% O₂**; "
        f"on Earth the same rods go out at **{g1['low']:.0f}%**.\n"
        f"- A **{moon:.0f}% O₂** Moon base is **{moon - lim['low']:.0f} points** above that "
        "limit, and above anything tested on the ISS. Materials that burn in station air "
        "will burn there.\n"
        "- O₂ *percentage* and *partial pressure* both matter. A Moon base at 30% / 10.2 psi "
        "has roughly the same O₂ partial pressure as the ISS, but no PSI data covers that "
        "combination yet.\n"
        "- **Partial gravity (Moon 0.16 g, Mars 0.38 g) has no combustion data in PSI.** "
        "We do not assume the Moon value lies between the 0 g and 1 g limits; future "
        "experiments (e.g. FM2) are needed.")

# ---------------- 3. research finder ----------------
with tab_search:
    st.subheader("Find PSI investigations relevant to habitat fire safety")
    meta = metadata()
    q = st.text_input("Search", "flammability limits of solid materials in low oxygen")
    if HAVE_RAG:
        hits = rag.search(q, k=6)
    else:
        from sklearn.feature_extraction.text import TfidfVectorizer
        ids = list(meta)
        docs = [" ".join(str(meta[i].get(k, "")) for k in
                         ["title", "objective", "hypothesis", "approach", "researchImpacts"])
                for i in ids]
        vec = TfidfVectorizer(stop_words="english")
        X = vec.fit_transform(docs + [q])
        scores = (X[:-1] @ X[-1].T).toarray().ravel()
        hits = [{"id": ids[i], "title": meta[ids[i]]["title"], "score": float(scores[i]),
                 "snippet": str(meta[ids[i]].get("researchImpacts", ""))[:300],
                 "doi": meta[ids[i]].get("doi", "")}
                for i in np.argsort(-scores)[:6] if scores[i] > 0]
        st.caption("Keyword search over PSI study metadata (AI search module not connected).")
    for hit in hits:
        s = meta.get(hit["id"], {})
        with st.expander(f"**{hit['id']}: {hit['title']}**  ·  relevance {hit['score']:.2f}"):
            if hit.get("doi"):
                st.markdown(f"DOI: [{hit['doi']}](https://doi.org/{hit['doi']})")
            for k, lab in [("objective", "Objective"), ("researchImpacts", "Why it matters")]:
                if s.get(k):
                    st.markdown(f"**{lab}.** {s[k][:900]}")
            if HAVE_RAG and hasattr(rag, "summarize"):
                if st.button("AI summary", key=f"sum-{hit['id']}"):
                    st.json(rag.summarize(hit["id"]))
    if HAVE_RAG and hasattr(rag, "ask"):
        st.divider()
        question = st.text_input("Ask a question about the PSI combustion studies")
        if question:
            ans = rag.ask(question)
            st.markdown(ans["answer"])
            st.caption("Sources: " + ", ".join(ans.get("sources", [])))

# ---------------- 4. method & sources ----------------
with tab_about:
    st.subheader("Method")
    cons = consistency()
    st.markdown(f"""
1. **Data.** NASA PSI BASS-II (PSI-25): 129 ISS test runs of solid fuels burning in a
   low-speed flow duct at 13.6–22.2% O₂. The table has no outcome column; outcomes exist
   only as operator notes (e.g. `5 3 2 ext`).
2. **Labels.** A parser splits each run into one row per airflow step. Outcomes
   (burn / extinguish / blowoff / no ignition) come from the notes, with LLM assistance for
   ambiguous rows (marked in the data). Unclear rows are labeled *unknown*, not guessed.
3. **Consistency check.** {"Two independent, blind LLM labeling passes agreed on "
   f"{cons['agree']:.0%} of {cons['n']} sampled steps." if cons else "Pending."}
   This measures labeling consistency, not human validation.
4. **Model.** An empirical flammability envelope for PMMA rods: the observed burn rate per
   O₂ × flow cell, counted once per run, with 95% Jeffreys intervals. We tried logistic
   regression first and rejected it. Operators lowered flow until every flame went out, so
   the extinctions carry almost no O₂ information and the fit was unphysical.
5. **Bounds.** The microgravity limit is bracketed by ISS runs and matches the published
   13.6%. The 1 g comparison uses the same rods (Marcum, Olson & Ferkul 2016).

**Limitations.** Only PMMA rods have enough data. No pressure column (ISS cabin assumed).
No partial-gravity data exists. Everything above 22.2% O₂ is extrapolation.
""")
    st.subheader("Sources")
    for r in baselines.REFERENCES:
        st.markdown(f"- {r}")
    st.markdown("- All PSI studies used are listed with DOIs in the Research finder tab.")
    st.subheader("AI use disclosure")
    st.markdown("- Code for the parser, model, dashboard and figures was written with AI "
                "coding assistance (Claude) and reviewed by the team.\n"
                "- Outcome labels for ambiguous ISS notes were extracted with LLM "
                "assistance and are marked as such in the data.\n"
                "- The project idea and scientific framing are the team's own. No "
                "AI-generated images are used.")
