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

# palette (dark theme; see .streamlit/config.toml)
BURN, NOBURN, QUERY = "#3987e5", "#ff7a3d", "#b9a8ff"
FIRE, TEXT, MUTED, GRID, CARD = "#ff7a3d", "#e8e6e1", "#9a9890", "#262c38", "#161b26"
PSI_TO_KPA = 6.89476
BASS2_DOI = "10.60555/4qc4-de67"

st.set_page_config(page_title="FlameScope", page_icon="🔥", layout="wide")

st.markdown(f"""
<style>
.block-container {{ padding-top: 4.2rem; max-width: 1320px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
.hero-title {{ font-size: 2.8rem !important; font-weight: 800; margin: 0 !important; line-height: 1.1 !important; }}
.hero-title span {{ color: {FIRE}; }}
.hero-sub {{ color: {MUTED}; font-size: 1.1rem !important; margin: .5rem 0 .9rem 0 !important; max-width: 820px; }}
.chips {{ display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1.4rem; }}
.chip {{ border: 1px solid {GRID}; border-radius: 999px; padding: .2rem .75rem;
         font-size: .8rem; color: {MUTED}; }}
.kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.6rem; }}
@media (max-width: 900px) {{ .kpis {{ grid-template-columns: repeat(2, 1fr); }} }}
.kpi {{ background: {CARD}; border: 1px solid {GRID}; border-radius: 14px; padding: 1rem 1.2rem; }}
.kpi .label {{ color: {MUTED}; font-size: .82rem; text-transform: uppercase; letter-spacing: .04em; }}
.kpi .value {{ font-size: 2.2rem; font-weight: 750; margin: .25rem 0 .1rem 0; }}
.kpi .note {{ color: {MUTED}; font-size: .8rem; }}
.kpi.alert {{ border-color: {FIRE}; background: linear-gradient(160deg, rgba(255,122,61,.16), {CARD} 70%); }}
.kpi.alert .value {{ color: {FIRE}; }}
.result {{ border-radius: 14px; padding: 1.1rem 1.2rem; margin-top: .4rem; border: 1px solid {GRID};
           background: {CARD}; }}
.result .big {{ font-size: 2.6rem; font-weight: 800; line-height: 1; }}
.result .cap {{ color: {MUTED}; font-size: .85rem; margin-top: .35rem; }}
.badge {{ display: inline-block; border-radius: 6px; padding: .15rem .55rem; font-size: .78rem;
          font-weight: 650; margin-top: .6rem; margin-right: .3rem; }}
.b-red {{ background: rgba(255,122,61,.18); color: {FIRE}; }}
.b-amber {{ background: rgba(250,178,25,.16); color: #fab219; }}
.b-gray {{ background: rgba(255,255,255,.08); color: {MUTED}; }}
.stTabs [data-baseweb="tab-list"] {{ gap: .4rem; }}
.stTabs [data-baseweb="tab"] {{ font-size: 1rem; padding: .5rem .9rem; }}
.finding {{ border-left: 3px solid {FIRE}; padding: .2rem 0 .2rem .9rem; margin: .6rem 0; }}
.small, p.small {{ color: {MUTED}; font-size: .84rem !important; line-height: 1.45 !important; }}
</style>
""", unsafe_allow_html=True)


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


def dark_layout(fig, height, right=20):
    fig.update_layout(
        height=height, margin=dict(l=70, r=right, t=40, b=60),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, size=13), hoverlabel=dict(bgcolor=CARD, font_color=TEXT),
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=13)))
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, automargin=True)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, automargin=True)
    return fig


lim = model.limiting_o2()
g1 = baselines.PMMA_ROD["normal_gravity_bracket"]
moon = baselines.HABITAT["moon_base_o2_min"]
margin = moon - lim["low"]

# ---------------- hero ----------------
st.markdown(f"""
<div class="hero-title">🔥 Flame<span>Scope</span></div>
<div class="hero-sub">How flammable are spacecraft materials, and how much margin does a
30% oxygen Moon base have? Built on NASA's microgravity combustion experiments.</div>
<div class="chips">
  <span class="chip">NASA PSI · BASS-II (PSI-25)</span>
  <span class="chip">129 ISS test runs</span>
  <span class="chip">23 PSI studies searchable</span>
  <span class="chip">Cited 1 g comparison</span>
</div>
<div class="kpis">
  <div class="kpi"><div class="label">Microgravity limit</div>
    <div class="value">≈{lim['low']:.1f}%</div>
    <div class="note">lowest O₂ where PMMA rods burned on the ISS</div></div>
  <div class="kpi"><div class="label">Same rods on Earth</div>
    <div class="value">{g1['low']:.0f}%</div>
    <div class="note">go out at this O₂ in 1 g (Marcum et al. 2016)</div></div>
  <div class="kpi"><div class="label">Planned Moon base</div>
    <div class="value">≥{moon:.0f}%</div>
    <div class="note">O₂ at ≤10.2 psi (pressurized habitats, rovers)</div></div>
  <div class="kpi alert"><div class="label">Margin above the limit</div>
    <div class="value">+{margin:.0f} pts</div>
    <div class="note">no flammability safety margin</div></div>
</div>
""", unsafe_allow_html=True)

tab_map, tab_hab, tab_search, tab_about = st.tabs(
    ["🔥 Flammability explorer", "🌙 Habitat check", "🔎 Research finder",
     "📄 Method & sources"])

# ---------------- 1. flammability explorer ----------------
with tab_map:
    left, right = st.columns([1, 2.5], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Will it keep burning?")
            material = st.selectbox("Material", ["PMMA rod (acrylic)", "PMMA film",
                                                 "PMMA slab", "SIBAL fabric"])
            o2 = st.slider("Oxygen (% by volume)", 10.0, 35.0, 21.0, 0.1)
            flow = st.select_slider(
                "Air flow past the sample (cm/s)",
                options=[0.5, 1, 1.5, 2, 3, 5, 7, 10, 15, 20, 30], value=5,
                help="Ventilation flow. On Earth buoyancy creates ~30 cm/s of flow; "
                     "in microgravity only fans move air.")
        res = model.predict(material, None, o2, flow)
        if not model.is_supported(material):
            st.markdown('<div class="result"><div class="big">—</div>'
                        '<div class="cap">Only PMMA rods have enough ISS extinctions to '
                        'estimate a limit.</div><span class="badge b-gray">Insufficient data'
                        '</span><span class="badge b-gray">No data ≠ safe</span></div>',
                        unsafe_allow_html=True)
        elif math.isnan(res["p_burn"]):
            st.markdown('<div class="result"><div class="big">—</div>'
                        '<div class="cap">No ISS runs this low in oxygen.</div>'
                        '<span class="badge b-gray">Below tested range</span></div>',
                        unsafe_allow_html=True)
        else:
            badges = []
            if o2 >= lim["high"] and 1 <= flow <= 10:
                badges.append('<span class="badge b-red">Above µg limit</span>')
            if model.is_extrapolation(o2):
                badges.append('<span class="badge b-amber">Extrapolation: lower bound</span>')
            if flow < 1 or flow > 10:
                badges.append('<span class="badge b-gray">Near quench / blowoff edge</span>')
            color = FIRE if res["p_burn"] >= 0.5 else BURN
            st.markdown(
                f'<div class="result"><div class="cap" style="margin:0 0 .4rem 0">Observed '
                f'burn rate in similar ISS runs</div><div class="big" style="color:{color}">'
                f'{fmt_pct(res["p_burn"])}</div><div class="cap">95% interval '
                f'{fmt_pct(res["low"])} – {fmt_pct(res["high"])} · counted once per run</div>'
                f'{"".join(badges)}</div>', unsafe_allow_html=True)
        st.markdown('<p class="small" style="margin-top:.8rem">Pressure and gravity are '
                    'not modeled: BASS-II ran in microgravity at ISS cabin pressure. '
                    f'O₂ above {model.TESTED_O2_RANGE[1]}% was never tested.</p>',
                    unsafe_allow_html=True)

    with right:
        d = runs()
        rng = np.random.default_rng(1)
        x = d["flow_cm_s"].where(d["flow_cm_s"] >= 1, 0.6) * np.exp(rng.uniform(-.06, .06, len(d)))
        y = d["o2_pct"] + rng.uniform(-.08, .08, len(d))
        fig = go.Figure()
        fig.add_hrect(y0=model.TESTED_O2_RANGE[1], y1=33, fillcolor="#ffffff", opacity=0.035,
                      line_width=0)
        fig.add_annotation(x=math.log10(0.45), y=26.5, xref="x", yref="y", showarrow=False,
                           text="NOT TESTED ON THE ISS", xanchor="left",
                           font=dict(color=MUTED, size=12))
        fig.add_hrect(y0=lim["low"], y1=lim["high"], fillcolor=FIRE, opacity=0.14, line_width=0)
        refs = [(moon, "Moon base ≥30%", FIRE, "solid", 2.2),
                (20.9, "Earth air / ISS 20.9%", MUTED, "dot", 1.2),
                (g1["high"], "1 g: out at 14–15%", MUTED, "dash", 1.2),
                (lim["low"], "µg limit ≈13.6%", FIRE, "solid", 1.2)]
        for yv, txt, col, dash, w in refs:
            fig.add_hline(y=yv, line_dash=dash, line_width=w, line_color=col,
                          annotation_text=f"<b>{txt}</b>" if yv == moon else txt,
                          annotation_position="right",
                          annotation_font=dict(color=col if yv == moon else TEXT, size=12))
        for yv_, name, color, sym in [(1, "Kept burning", BURN, "circle"),
                                      (0, "Went out / no ignition", NOBURN, "x")]:
            m = d["y"] == yv_
            fig.add_trace(go.Scatter(
                x=x[m], y=y[m], mode="markers", name=name,
                marker=dict(color=color, symbol=sym, size=9,
                            line=dict(width=1, color="#0d1017")),
                customdata=np.stack([d.loc[m, "run_id"], d.loc[m, "o2_pct"],
                                     d.loc[m, "flow_cm_s"], d.loc[m, "outcome"]], axis=1),
                hovertemplate="<b>Run %{customdata[0]}</b><br>O₂ %{customdata[1]}%<br>"
                              "flow %{customdata[2]} cm/s<br>%{customdata[3]}<extra></extra>"))
        fig.add_trace(go.Scatter(x=[flow], y=[o2], mode="markers", name="Your query",
                                 marker=dict(symbol="star", size=20, color=QUERY,
                                             line=dict(width=1.5, color="#0d1017")),
                                 hovertemplate="Your query: %{y}% O₂, %{x} cm/s<extra></extra>"))
        dark_layout(fig, 600, right=175)
        fig.update_xaxes(type="log", title="Air flow past the sample (cm/s)",
                         range=[math.log10(0.42), math.log10(42)],
                         tickvals=[0.6, 1, 2, 5, 10, 20, 40],
                         ticktext=["<1", "1", "2", "5", "10", "20", "40"])
        fig.update_yaxes(title="Oxygen (% by volume)", range=[12.5, 33], dtick=2.5)
        st.plotly_chart(fig, width="stretch", theme=None)
        st.markdown(f'<p class="small">PMMA rods · NASA PSI BASS-II (DOI {BASS2_DOI}). Each '
                    'point is one airflow step of an ISS run; outcomes extracted from operator '
                    'notes with LLM assistance. Flows &lt;1 cm/s are fan-setting estimates; '
                    'points jittered slightly.</p>', unsafe_allow_html=True)

# ---------------- 2. habitat check ----------------
with tab_hab:
    st.markdown("### Where do crewed habitats sit relative to the microgravity limit?")
    habitats = pd.DataFrame([
        ("Earth sea level", 20.9, 14.7, "reference"),
        ("ISS cabin", 20.9, 14.7, "BASS-II test conditions"),
        ("Moon base / rover (planned)", 30.0, 10.2, "challenge statement"),
        ("Spacesuit", 100.0, 4.3, "challenge statement"),
    ], columns=["Environment", "O₂ %", "Pressure (psi)", "Source"])
    with st.expander("➕ Add your own environment"):
        cc1, cc2, cc3 = st.columns([1, 1, 1])
        co2 = cc1.number_input("O₂ %", 10.0, 100.0, 34.0)
        cp = cc2.number_input("Pressure (psi)", 1.0, 20.0, 8.2)
        cc3.write("")
        if cc3.checkbox("Include it"):
            habitats.loc[len(habitats)] = ["Custom", co2, cp, "user input"]

    hc1, hc2 = st.columns([1.3, 1], gap="large")
    with hc1:
        hb = habitats.iloc[::-1]
        bar_colors = [FIRE if v >= model.TESTED_O2_RANGE[1] else BURN for v in hb["O₂ %"]]
        hfig = go.Figure(go.Bar(
            x=hb["O₂ %"], y=hb["Environment"], orientation="h", marker_color=bar_colors,
            marker_line_width=0, text=[f"{v:g}%" for v in hb["O₂ %"]],
            textposition="outside", textfont=dict(color=TEXT),
            hovertemplate="%{y}: %{x}% O₂<extra></extra>", width=0.55))
        hfig.add_vrect(x0=0, x1=lim["low"], fillcolor="#ffffff", opacity=0.04, line_width=0)
        hfig.add_vline(x=lim["low"], line_color=FIRE, line_width=2,
                       annotation_text=f"µg limit {lim['low']:.1f}%",
                       annotation_position="top", annotation_font=dict(color=FIRE))
        hfig.add_vline(x=model.TESTED_O2_RANGE[1], line_color=MUTED, line_dash="dot",
                       annotation_text="ISS-tested up to 22.2%", annotation_position="bottom",
                       annotation_font=dict(color=MUTED))
        dark_layout(hfig, 340)
        hfig.update_layout(showlegend=False, bargap=0.35)
        hfig.update_xaxes(title="Oxygen (% by volume)", range=[0, 110])
        st.plotly_chart(hfig, width="stretch", theme=None)
    with hc2:
        st.markdown(
            f'<div class="finding">In microgravity, PMMA rods kept burning down to '
            f'<b>≈{lim["low"]:.1f}% O₂</b>. On Earth the same rods go out at '
            f'<b>{g1["low"]:.0f}%</b>.</div>'
            f'<div class="finding">A <b>{moon:.0f}% O₂</b> Moon base is <b>{margin:.0f} points'
            '</b> above that limit, and above anything tested on the ISS. Materials that '
            'burn in station air will burn there.</div>'
            '<div class="finding">Partial gravity (Moon 0.16 g, Mars 0.38 g) has <b>no '
            'combustion data in PSI</b>. We do not assume the Moon lies between the 0 g and '
            '1 g limits.</div>', unsafe_allow_html=True)

    h = habitats.copy()
    h["O₂ partial pressure (kPa)"] = (h["O₂ %"] / 100 * h["Pressure (psi)"] * PSI_TO_KPA).round(1)
    h["Points above µg limit"] = (h["O₂ %"] - lim["low"]).round(1)
    h["Within ISS-tested O₂?"] = np.where(h["O₂ %"] <= model.TESTED_O2_RANGE[1], "✅ yes",
                                         "⚠️ extrapolation")
    st.dataframe(h, hide_index=True, width="stretch")
    st.markdown('<p class="small">O₂ percentage and partial pressure both matter. A 30% / '
                '10.2 psi Moon base has about the same O₂ partial pressure as the ISS, but no '
                'PSI data covers that combination yet.</p>', unsafe_allow_html=True)

# ---------------- 3. research finder ----------------
with tab_search:
    st.markdown("### Find PSI investigations relevant to habitat fire safety")
    meta = metadata()
    q = st.text_input("Search the 23 PSI combustion studies",
                      "flammability limits of solid materials in low oxygen",
                      label_visibility="collapsed")
    st.markdown('<span class="small">Try: <i>smoke detection</i> · <i>fire suppression</i> · '
                '<i>droplet combustion</i> · <i>flame spread over fabric</i></span>',
                unsafe_allow_html=True)
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
    for hit in hits:
        s = meta.get(hit["id"], {})
        with st.container(border=True):
            t1, t2 = st.columns([5, 1])
            acr = s.get("investigationAcronym") or s.get("short_name") or ""
            t1.markdown(f"**{hit['title']}**  \n<span class='small'>{hit['id']}"
                        f"{' · ' + acr if acr else ''}"
                        f"{' · ' + s.get('flightProgram', '') if s.get('flightProgram') else ''}"
                        "</span>", unsafe_allow_html=True)
            if hit.get("doi"):
                t2.link_button("DOI ↗", f"https://doi.org/{hit['doi']}")
            snippet = s.get("researchImpacts") or hit.get("snippet", "")
            st.markdown(f"<span class='small'>{str(snippet)[:320]}…</span>",
                        unsafe_allow_html=True)
            with st.expander("More"):
                for k, lab in [("objective", "Objective"), ("researchImpacts", "Why it matters")]:
                    if s.get(k):
                        st.markdown(f"**{lab}.** {s[k][:1200]}")
                if HAVE_RAG and hasattr(rag, "summarize"):
                    if st.button("AI summary", key=f"sum-{hit['id']}"):
                        st.json(rag.summarize(hit["id"]))
    if not HAVE_RAG:
        st.caption("Keyword search over PSI study metadata. The AI search & Q&A module plugs "
                   "in here.")
    if HAVE_RAG and hasattr(rag, "ask"):
        st.divider()
        question = st.text_input("Ask a question about the PSI combustion studies")
        if question:
            ans = rag.ask(question)
            st.markdown(ans["answer"])
            st.caption("Sources: " + ", ".join(ans.get("sources", [])))

# ---------------- 4. method & sources ----------------
with tab_about:
    cons = consistency()
    a1, a2 = st.columns([1.4, 1], gap="large")
    with a1:
        st.markdown("### Method")
        st.markdown(f"""
1. **Data.** NASA PSI BASS-II (PSI-25): 129 ISS test runs of solid fuels burning in a
   low-speed flow duct at 13.6–22.2% O₂. The table has no outcome column; outcomes exist
   only as operator notes (e.g. `5 3 2 ext`).
2. **Labels.** A parser splits each run into one row per airflow step. Outcomes
   (burn / extinguish / blowoff / no ignition) come from the notes, with LLM assistance for
   ambiguous rows (marked in the data). Unclear rows are labeled *unknown*, not guessed.
3. **Consistency check.** {"Two independent, blind LLM labeling passes agreed on "
   f"**{cons['agree']:.0%}** of {cons['n']} sampled steps." if cons else "Pending."}
   This measures labeling consistency, not human validation.
4. **Model.** An empirical flammability envelope for PMMA rods: the observed burn rate per
   O₂ × flow cell, counted once per run, with 95% Jeffreys intervals. We tried logistic
   regression first and rejected it. Operators lowered flow until every flame went out, so
   the extinctions carry almost no O₂ information and the fit was unphysical.
5. **Bounds.** The microgravity limit is bracketed by ISS runs and matches the published
   13.6%. The 1 g comparison uses the same rods (Marcum, Olson & Ferkul 2016).
""")
        st.markdown("### Limitations")
        st.markdown("- Only PMMA rods have enough data.\n- No pressure column (ISS cabin "
                    "assumed).\n- No partial-gravity data exists.\n- Everything above 22.2% "
                    "O₂ is extrapolation.")
    with a2:
        st.markdown("### Sources")
        for r in baselines.REFERENCES:
            st.markdown(f"<p class='small'>• {r}</p>", unsafe_allow_html=True)
        st.markdown("<p class='small'>• All PSI studies used are listed with DOIs in the "
                    "Research finder tab.</p>", unsafe_allow_html=True)
        st.markdown("### AI use disclosure")
        st.markdown("<p class='small'>• Code for the parser, model, dashboard and figures was "
                    "written with AI coding assistance (Claude) and reviewed by the team.<br>"
                    "• Outcome labels for ambiguous ISS notes were extracted with LLM "
                    "assistance and are marked as such in the data.<br>• The project idea "
                    "and scientific framing are the team's own. No AI-generated images are "
                    "used.</p>", unsafe_allow_html=True)
