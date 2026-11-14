/* FlameScope frontend. Every figure comes from window.DEMO (built by
   build_cache.py) or from /api/ask (serve.py). Nothing is typed in by hand.

   Main screens speak plain language. Technical detail (verification verdict,
   files, pages, model, search methods) lives in the "How it works" drawer. */
(() => {
  "use strict";
  const D = window.DEMO;
  const app = document.getElementById("app");
  const drawer = document.getElementById("drawer");
  const drawerBody = document.getElementById("drawer-body");
  const scrim = document.querySelector(".scrim");
  const PRESETS = D.presets;
  const byId = Object.fromEntries(PRESETS.map((p) => [p.id, p]));
  const EXAMPLES = new Map((D.examples || []).map((e) => [e.question.toLowerCase().replace(/[?.!\s]+$/, ""), e]));
  // One-click scenario titles (UI copy only; the answers come from the cache).
  const SCENARIO = {
    smoke: { title: "Spacecraft smoke alarms", tag: "Detection" },
    oxygen: { title: "How little oxygen can fire live on?", tag: "Flammability" },
    moon: { title: "Fire on a Moon base", tag: "Habitats" },
  };
  const PAGES = new Set(["research", "map", "method"]);
  let habitat = "all";      // research map filter
  const INV = Object.fromEntries(D.method.investigations.map((r) => [r.id, r]));
  const live = {};          // question -> shaped ask() response from serve.py
  let LIVE = false;         // serve.py reachable?
  let current = null;       // {question, ans, preset} | {loading} | {error} | {page} | null
  let counted = false;

  // ---------- helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n).toLocaleString("en-US");
  const norm = (s) => String(s ?? "").replace(/\s+/g, " ").trim();
  const doiUrl = (d) => (d ? `https://doi.org/${encodeURIComponent(d).replace(/%2F/g, "/")}` : null);
  const THIN = new Set(["thin", "metadata_only"]);
  // Any Moon/Mars question gets the "No NASA data" screen and no AI summary,
  // whether the backend rated the gap hard or soft. A soft-rated question
  // ("does microgravity data apply to Mars?") once drew an AI summary that
  // said the data was relevant to Mars - the opposite of what PSI supports.
  const partialGravity = (ans) => (ans.gaps || []).some((g) => g.kind === "partial_gravity");
  const model = PRESETS.map((p) => p.ask.grounding?.model).find(Boolean);

  // Passages start and stop mid-sentence. Trim to whole sentences where we
  // can, and mark every cut with an ellipsis so the quote stays honest.
  function excerpt(text, max = 220) {
    let t = norm(text), pre = "", post = "";
    const start = t.slice(0, 140).search(/[.!?]\s+[A-Z]/);
    if (start > 0) { t = t.slice(start + 2); pre = "…"; }
    if (t.length > max) {
      const cut = t.slice(0, max);
      const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("? "));
      if (end > max * 0.5) t = cut.slice(0, end + 1);
      else { t = cut.replace(/\s+\S*$/, ""); post = "…"; }
    }
    return pre + t + post;
  }

  // "[SAME]" citations in AI text become small source pills.
  const withCites = (text) => esc(text).replace(/\s*\[([^\]\n]{1,40})\]/g, ' <span class="cite">$1</span>');

  function docLabel(e) {
    const f = e.file || "";
    let t = "NASA document";
    if (e.kind === "NASA metadata" || /metadata\.json$/.test(f)) t = "NASA project summary";
    else if (/_Reports_/i.test(f)) t = "NASA report";
    else if (/_Presentations_/i.test(f)) t = "NASA presentation";
    else if (/_Science Documents_/i.test(f)) t = "NASA science document";
    else if (/\.csv$/i.test(f)) t = "NASA data table";
    return t + (e.page ? ` · page ${e.page}` : "");
  }

  // Up to n cards, one per investigation first, in the order returned.
  function pickEvidence(ans, n = 3) {
    const ev = ans.evidence || [], seen = new Set(), out = [];
    for (const e of ev) if (out.length < n && !seen.has(e.investigation)) { seen.add(e.investigation); out.push(e); }
    for (const e of ev) if (out.length < n && !out.includes(e)) out.push(e);
    return out;
  }

  // ---------- plain-language source cards ----------
  function card({ name, title, meta, quote, doi, thin, note }) {
    const url = doiUrl(doi);
    return `<article class="src">
      <div class="src-head"><span class="src-name">${esc(name)}</span>${thin ? '<span class="pill amber" title="NASA publishes very little text for this investigation">little published text</span>' : ""}</div>
      ${title ? `<p class="src-title">${esc(title)}</p>` : ""}
      <p class="src-meta">${esc(meta)}</p>
      ${quote ? `<blockquote class="src-quote">“${esc(quote)}”</blockquote>` : ""}
      ${note ? `<p class="src-note">${esc(note)}</p>` : ""}
      ${url ? `<a class="src-link" href="${url}" target="_blank" rel="noopener">Open NASA record ↗</a>` : ""}
    </article>`;
  }

  const evidenceCard = (e) => card({
    name: e.acronym || e.investigation,
    title: INV[e.investigation]?.title,
    meta: docLabel(e),
    quote: excerpt(e.text),
    doi: e.doi,
    thin: THIN.has(e.evidence_level),
    note: e.about && e.about !== e.acronym ? `This passage is about ${e.about}.` : "",
  });

  function sources(cards, label = "Where this comes from") {
    return cards.length ? `<section class="sources"><h3 class="eyebrow">${esc(label)}</h3><div class="src-grid">${cards.join("")}</div></section>` : "";
  }

  // ---------- result parts ----------
  const STATUS = {
    nasa: ["blue", "Answered from NASA documents"],
    measured: ["fire", "Measured from NASA test data"],
    none: ["red", "No NASA data for this"],
    quoted: ["blue", "NASA's documents, quoted directly"],
  };
  const badge = (k) => `<span class="status ${STATUS[k][0]}"><i></i>${STATUS[k][1]}</span>`;

  function aiSummary(ans, asHeadline = false) {
    const g = ans.grounding || {};
    if (ans.answer) {
      return `<div class="ai${asHeadline ? " lead" : ""}"><span class="ai-label">AI summary · every number checked against NASA's text</span>
        <p>${withCites(ans.answer)}</p>${g.verdict === "flag"
          ? '<p class="warn">One value matched NASA\'s documents but its unit did not. Check the sources.</p>' : ""}</div>`;
    }
    if (g.verdict === "block")
      return `<div class="ai blocked">An AI summary was <b>withheld</b> because it contained numbers or sources not found in NASA's documents. NASA's own words are shown instead.</div>`;
    return "";
  }

  const PLAIN_GAP = {
    partial_gravity: "These results come from microgravity and may not apply on the Moon or Mars.",
    thin_evidence: "NASA published very little text for some of these sources.",
    no_condition_table: "Some of these sources have no published measurements to check numbers against.",
    ground_investigation: "Some of these sources are ground tests, not space tests.",
  };
  function caveats(ans) {
    const msgs = [...new Set((ans.gaps || []).filter((g) => g.severity !== "hard").map((g) => PLAIN_GAP[g.kind] || g.message))];
    return msgs.map((m) => `<p class="caveat">⚠ ${esc(m)}</p>`).join("");
  }

  function nextLink(id) {
    const i = PRESETS.findIndex((p) => p.id === id);
    const nxt = i >= 0 ? PRESETS[i + 1] : null;
    return nxt ? `<button class="next" data-preset="${nxt.id}">Next scenario: ${esc(SCENARIO[nxt.id]?.title || nxt.question)} →</button>` : "";
  }

  function oxygenScale() {
    const m = D.ml, h = m.habitat;
    const [lo, hi] = m.o2_tested, moon = h.moon_base_o2_min, earth = h.earth_air_o2;
    const min = 10, max = 32, pos = (x) => `${((x - min) / (max - min)) * 100}%`;
    return `<div class="scale" role="img" aria-label="NASA's BASS-II solid-material burns tested oxygen from ${lo}% to ${hi}%. A Moon base would use at least ${moon}%, ${D.moon_gap_points} points beyond.">
      <div class="ticks"><span style="left:${pos(earth)}"><b>${earth}%</b>Earth air</span></div>
      <div class="track">
        <div class="bar-fill" style="left:${pos(lo)};width:calc(${pos(hi)} - ${pos(lo)})"></div>
        <div class="gap-zone" style="left:${pos(hi)};width:calc(${pos(moon)} - ${pos(hi)})"></div>
        <div class="mark" style="left:${pos(earth)}"></div>
        <div class="mark moon" style="left:${pos(moon)}"></div>
      </div>
      <div class="ticks">
        <span style="left:${pos((lo + hi) / 2)}"><b>${lo}–${hi}%</b>solid burns tested</span>
        <span class="moon" style="left:${pos(moon)}"><b>${moon}%+</b>Moon base</span>
      </div>
    </div>`;
  }

  // ---------- result bodies ----------
  function quoteResult(p) {
    const h = p.headline, ans = p.ask;
    return {
      status: "nasa",
      body: `<span class="eyebrow nasa">NASA's words</span>
        <blockquote class="headline-quote">“${esc(h.text)}”</blockquote>
        <p class="attr">${esc(h.acronym)} · ${esc(INV[h.investigation]?.title || "")}</p>
        ${aiSummary(ans)}${caveats(ans)}`,
      cards: pickEvidence(ans).map(evidenceCard),
    };
  }

  function measuredResult() {
    const m = D.ml, L = m.limit, h = m.habitat, eb = m.earth_bracket;
    return {
      status: "measured",
      body: `<div class="big"><span class="val">${L.o2}<small>%</small></span><span class="unit">oxygen</span></div>
        <p class="sub">The flame limit for an ${esc(m.material)} on the space station: it would not ignite at <b>${L.low}%</b> and kept burning at <b>${L.high}%</b>.</p>
        <div class="tiles">
          <div class="tile"><span>Earth air</span><b>${h.earth_air_o2}%</b></div>
          <div class="tile"><span>Same rod on Earth</span><b>${eb.low}–${eb.high}%</b></div>
          <div class="tile alert"><span>Planned Moon base</span><b>≥ ${h.moon_base_o2_min}%</b></div>
        </div>
        <button class="next" data-goto="map">Explore the flame map →</button>`,
      cards: [
        card({ name: m.source.acronym, title: INV[m.source.investigation]?.title, meta: `NASA data table · ${D.method.rod_runs} acrylic-rod runs on the space station`,
          note: `Did not ignite at ${L.low}% (run O12). Burned at ${L.high}% (run O13b).`, doi: m.source.doi }),
        card({ name: "Earth comparison", title: "Marcum, Olson & Ferkul (2016)", meta: "Published ground test, same acrylic rods, normal gravity", quote: eb.quote }),
        card({ name: "Moon base target", title: "NASA Space Apps 2026 challenge statement", meta: "Planned habitats and pressurized rovers",
          note: `At least ${h.moon_base_o2_min}% oxygen at up to ${h.moon_base_pressure_psi_max} psi.` }),
      ],
    };
  }

  function refusalResult(ans, where = "Moon gravity") {
    // The two gravity levels that ARE measured for the same acrylic rods. We
    // deliberately do not bracket the Moon value between them: flammability
    // can behave differently (even peak) between 0 g and 1 g, as noted in
    // ml/gravity_bounds/baselines.py.
    const L = D.ml.limit, eb = D.ml.earth_bracket, moon = D.ml.habitat.moon_base_o2_min;
    return {
      status: "none",
      body: `<h2 class="refuse">NASA's archive has no fire data at <em>${esc(where)}</em>.</h2>
        <p class="sub">Every space fire experiment in it ran in microgravity, on the ISS, Cygnus and the Shuttle. So FlameScope won't guess a Moon value.</p>
        <p class="eyebrow">What is measured, for the same acrylic rods</p>
        <div class="tiles">
          <div class="tile"><span>Flame limit in space (0 g)</span><b>${L.low}–${L.high}%</b></div>
          <div class="tile"><span>Flame limit on Earth (1 g)</span><b>${eb.low}–${eb.high}%</b></div>
          <div class="tile alert"><span>Planned Moon base</span><b>≥ ${moon}%</b></div>
        </div>
        <p class="sub">A ${moon}% base sits <b>${+(moon - eb.high).toFixed(1)} points</b> above even the Earth limit. Fire can behave differently between 0 g and 1 g, so the Moon value is unknown, but neither measured limit comes close to ${moon}%.</p>
        ${oxygenScale()}`,
      cards: pickEvidence(ans, 2).map(evidenceCard),
      cardsLabel: "What NASA does have (microgravity only)",
    };
  }

  function liveResult(ans) {
    if (partialGravity(ans)) return refusalResult(ans, "Moon or Mars gravity");
    const hasAnswer = !!ans.answer;
    return {
      status: hasAnswer ? "nasa" : "quoted",
      body: (hasAnswer ? aiSummary(ans, true) : aiSummary(ans) ||
          `<p class="sub">Here is what NASA's documents say. Read the passages below.</p>`) + caveats(ans) +
        ((ans.evidence || []).length ? "" : `<p class="sub">NASA's documents did not answer this question.</p>`),
      cards: pickEvidence(ans).map(evidenceCard),
    };
  }

  // ---------- workspace ----------
  function emptyState() {
    const c = D.corpus;
    return `<div class="empty">
      <p class="empty-title">Pick a scenario or ask your own question.</p>
      <p class="sub">FlameScope answers from NASA's space fire experiments, and says plainly when NASA has no data.</p>
      <div class="tiles">
        <div class="tile"><span>NASA fire investigations</span><b>${c.investigations}</b></div>
        <div class="tile"><span>Passages read</span><b>${fmt(c.passages)}</b></div>
        <div class="tile"><span>Space-station test runs measured</span><b>${D.method.rod_runs}</b></div>
      </div>
    </div>`;
  }

  function resultView() {
    if (!current) return emptyState();
    if (current.loading) return `<div class="loading-card"><div class="loading">Checking NASA's fire experiment records…</div>
      <p class="sub">Reading the passages, then checking every number against NASA's text.</p></div>`;
    if (current.error) return `<div class="result-card"><p class="sub">${esc(current.error)}</p></div>`;
    const { question, ans, preset: p } = current;
    const r = !p ? liveResult(ans)
      : p.kind === "quote" ? quoteResult(p)
      : p.kind === "measured" ? measuredResult()
      : refusalResult(ans);
    return `<div class="result-card ${r.status}">
        <div class="result-top">${badge(r.status)}<p class="asked">${esc(question)}</p></div>
        ${r.body}
        ${p ? nextLink(p.id) : ""}
      </div>
      ${sources(r.cards, r.cardsLabel)}`;
  }

  function workspace() {
    const q = current?.question ?? PRESETS[0].question;
    const active = current?.preset?.id;
    return `<section class="ws">
      <header class="mission${current ? " compact" : ""}">
        <h1>Fire-safety answers from <span class="num" data-count="${D.files.total}">${counted ? fmt(D.files.total) : "0"}</span> NASA files.</h1>
        <p>Ask how fire behaves in spacecraft and Moon bases. FlameScope answers with NASA's own experiments, and tells you when NASA has no data.</p>
      </header>
      <div class="ws-grid">
        <aside class="input-panel">
          <form class="ask" data-ask>
            <label for="q">Your question</label>
            <textarea id="q" name="q" rows="3">${esc(q)}</textarea>
            <button type="submit">Explore</button>
          </form>
          <p class="eyebrow">Try a scenario</p>
          <div class="scenarios">${PRESETS.map((p, i) => `
            <button class="scenario${p.id === active ? " on" : ""}" data-preset="${p.id}">
              <span class="sc-tag">${i + 1} · ${esc(SCENARIO[p.id]?.tag || "")}</span>
              <span class="sc-title">${esc(SCENARIO[p.id]?.title || p.question)}</span>
              <span class="sc-q">${esc(p.question)}</span>
            </button>`).join("")}</div>
          ${D.examples?.length ? `<details class="more-q"${current?.ans && !current.preset ? " open" : ""}>
            <summary>More questions to try (${D.examples.length})</summary>
            <div>${D.examples.map((e) => `<button class="ex-q${current?.question === e.question ? " on" : ""}" data-example="${esc(e.question)}">${esc(e.question)}</button>`).join("")}</div>
          </details>` : ""}
        </aside>
        <div class="results" id="results">${resultView()}</div>
      </div>
    </section>`;
  }

  // ---------- technical drawer ----------
  function gapsPanel(ans) {
    if (!ans.gaps?.length) return "";
    return `<div class="panel"><h2>Evidence gaps (verbatim)</h2><div class="ledger">${ans.gaps.map((g) =>
      `<div class="gap ${esc(g.severity)}"><b>${esc(g.kind.replace(/_/g, " "))}</b> · ${esc(g.severity)}<br>${esc(g.message)}</div>`).join("")}</div></div>`;
  }

  function groundingPanel(ans) {
    const g = ans.grounding || {}, c = ans.completeness || {}, cov = ans.coverage || {};
    const meaning = { pass: "every checked number and citation found in the sources", flag: "a value matched but its unit did not",
      block: "draft withheld: invented numbers or citations", skipped: "no language model reachable; sources only" };
    return `<div class="panel"><h2>Verification and search</h2>
      <div class="row">
        <span>Verdict: <span class="verdict ${esc(g.verdict)}">${esc(g.verdict)}</span> <span class="muted">(${esc(meaning[g.verdict] || "")})</span></span>
        <span>Numbers verbatim: <b>${g.numbers_verbatim ?? 0}/${g.numbers_checked ?? 0}</b></span>
        ${g.model ? `<span>Model: ${esc(g.backend)}:${esc(g.model)}</span>` : ""}
        ${g.rejected_numbers?.length ? `<span style="color:var(--red)">Rejected: ${esc(g.rejected_numbers.map((r) => r.value ?? r).join(", "))}</span>` : ""}
        ${g.invalid_citations?.length ? `<span style="color:var(--red)">Invalid citations: ${esc(g.invalid_citations.join(", "))}</span>` : ""}
      </div>
      <div class="row" style="margin-top:8px">
        <span>Searched <b>${fmt(c.chunks_searched ?? 0)}</b> passages across <b>${c.investigations_searched ?? "?"}</b> investigations</span>
        <span>Matched: ${esc((c.matched || []).join(", ") || "none")}</span>
        ${c.considered_below_threshold?.length ? `<span class="muted">Below threshold: ${esc(c.considered_below_threshold.join(", "))}</span>` : ""}
        <span class="muted">Retrievers: ${esc((c.retrievers || []).join(", "))}${c.embeddings_active === false ? " (embeddings off)" : ""}</span>
      </div>
      ${cov.parts?.length > 1 ? `<div class="row small" style="margin-top:8px">${cov.parts.map((p) =>
        `<span>${esc(p.sub_question)}: <b>${esc(p.state)}</b></span>`).join("")}</div>` : ""}
      <p class="small muted" style="margin:10px 0 0">Not checked: whether a cited passage supports the sentence it is attached to. Small unitless integers are not checked.</p></div>`;
  }

  function ledgerPanel(ans, title = "Evidence ledger") {
    const rows = (ans.evidence || []).map((e) => {
      const url = doiUrl(e.doi);
      return `<div class="entry"><div class="head">
        <strong>${esc(e.acronym || e.investigation)}</strong><span>${esc(e.investigation)}</span>
        <span class="lvl ${esc(e.evidence_level)}">${esc(String(e.evidence_level).replace("_", " "))}</span>
        <span>${esc(e.file)}${e.page ? ` p.${esc(e.page)}` : ""}</span>
        ${e.about && e.about !== e.acronym ? `<span style="color:var(--amber)">about ${esc(e.about)}</span>` : ""}
        ${url ? `<a href="${url}" target="_blank" rel="noopener">DOI</a>` : ""}</div>
        <blockquote>${esc(norm(e.text))}</blockquote></div>`;
    }).join("");
    return `<div class="panel"><h2>${esc(title)}</h2><div class="ledger">${rows || '<p class="muted">No passages.</p>'}</div></div>`;
  }

  function conditionsPanel(ans) {
    const rows = ans.conditions || [];
    if (!rows.length) return "";
    const keys = [...new Set(rows.flatMap((r) => Object.keys(r.conditions)))];
    return `<div class="panel"><h2>Tested conditions (PSI experimental tables)</h2>
      <table><thead><tr><th>Investigation</th>${keys.map((k) => `<th>${esc(k)}</th>`).join("")}<th>Source</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td>${esc(r.acronym || r.accession)}</td>${keys.map((k) => {
        const c = r.conditions[k];
        return `<td>${c ? `${esc(c.value)}<span class="col">${esc(c.column)}</span>` : ""}</td>`;
      }).join("")}<td>${esc(r.file)} row ${esc(r.row)}</td></tr>`).join("")}</tbody></table>
      <p class="small muted" style="margin:8px 0 0">${fmt(rows.length)} of ${fmt(ans.conditions_available ?? rows.length)} rows shown. Column labels are matched heuristically.${
        ans.conditions_dropped ? ` ${ans.conditions_dropped} value(s) hidden: mislabelled column (e.g. CO2 matched as oxygen).` : ""}</p></div>`;
  }

  function mlPanel() {
    const m = D.ml, L = m.limit;
    const oc = Object.entries(m.outcomes).map(([k, v]) => `${esc(k.replace("_", " "))} ${v}`).join(" · ");
    return `<div class="panel"><h2>Measured flame limit (BASS-II, ${esc(m.material)})</h2>
      <div class="row">
        <span>Limit <b>${L.o2}%</b> O₂ (midpoint), bracket ${L.low}–${L.high}%</span>
        <span class="muted">${esc(L.evidence)}</span>
        <span>Airflow window ${m.burn_window_cm_s[0]}–${m.burn_window_cm_s[1]} cm/s</span></div>
      <div class="row" style="margin-top:8px">
        <span>${fmt(m.runs)} labelled steps: ${oc}</span>
        <span>Tested O₂ ${m.o2_tested[0]}–${m.o2_tested[1]}% · airflow ${m.flow_tested[0]}–${m.flow_tested[1]} cm/s</span></div>
      <p class="small muted" style="margin:10px 0 0">1 g source: ${esc(m.earth_bracket.source)}</p></div>`;
  }

  function envelopePanel() {
    const M = D.map;
    return `<div class="panel"><h2>Burn rate per O₂ × airflow cell (model.envelope())</h2>
      <table><thead><tr><th>O₂ band</th><th>Airflow (cm/s)</th><th>Runs</th><th>Burning</th><th>Rate</th><th>95% CI</th></tr></thead><tbody>
      ${M.envelope.map((r) => `<tr><td>${esc(r.o2_band)}</td><td>${esc(r.flow_band)}</td><td>${r.runs}</td><td>${r.burning_runs}</td><td>${Math.round(r.p_burn * 100)}%</td><td>${Math.round(r.low * 100)}–${Math.round(r.high * 100)}%</td></tr>`).join("")}
      </tbody></table><p class="small muted" style="margin:8px 0 0">Counted once per run, 95% Jeffreys interval. The slider readout is model.predict() evaluated on every slider position at build time. Above ${M.tested_o2[1]}% O₂ the top band is a lower bound (monotone-in-O₂ assumption).</p></div>`;
  }

  function pipelinePanel() {
    const c = D.corpus, f = D.files;
    return `<div class="panel"><h2>Pipeline</h2><ol class="list">
      <li><b>Corpus.</b> ${fmt(c.passages)} passages and ${fmt(c.condition_rows)} condition rows from ${c.investigations} PSI investigations (${fmt(f.total)} PSI files in total, counted ${esc(f.counted_on)}).</li>
      <li><b>Retrieval.</b> Hybrid search: BM25 + TF-IDF + sentence embeddings, fused by reciprocal rank. Ranking does not use document volume.</li>
      <li><b>Answer.</b> A local LLM${model ? ` (${esc(model)} via Ollama)` : ""} writes at most four sentences from the retrieved passages, citing each.</li>
      <li><b>Verification.</b> Every number must appear verbatim in a source and every citation must name a retrieved investigation, or the summary is blocked.</li>
      <li><b>Gap radar.</b> Partial-gravity questions trigger a hard “no data” response; thin coverage is flagged.</li>
      <li><b>Flame model.</b> Empirical burn envelope from BASS-II acrylic-rod runs with Jeffreys intervals.</li>
    </ol><p class="small muted" style="margin:10px 0 0">${LIVE ? "Live answers on." : "Live answers off in this copy: only pre-computed questions are answered (start frontend/serve.py with Ollama for live answers)."} Data cache built ${esc(D.built)}.</p></div>`;
  }

  function drawerContent() {
    if (current?.page === "map") return `<h1>Flame map</h1>${envelopePanel()}${mlPanel()}`;
    if (current?.page === "research") return `<h1>Research map</h1>${rankingPanel()}`;
    if (current?.page === "method") return `<h1>How it works</h1>${pipelinePanel()}`;
    if (current?.ans) {
      const { question, ans, preset: p } = current;
      return `<h1>${esc(question)}</h1>
        ${p?.kind === "measured" ? mlPanel() : ""}
        ${gapsPanel(ans)}${groundingPanel(ans)}
        ${ledgerPanel(ans, p?.kind === "measured" ? "Related NASA passages" : "Evidence ledger")}
        ${conditionsPanel(ans)}`;
    }
    return `<h1>How it works</h1>${pipelinePanel()}`;
  }

  function openDrawer(open) {
    drawer.hidden = !open; scrim.hidden = !open;
    document.querySelector("[data-drawer]").setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("drawer-open", open);
    if (open) { drawerBody.innerHTML = drawerContent(); drawerBody.scrollTop = 0; drawer.querySelector(".x").focus(); }
  }

  // ---------- research map ----------
  // Rankings come from rag.search() per habitat (pre-computed); grouping is
  // by subject. Card text is NASA's own objective / impact sentence.
  function researchScreen() {
    const R = D.research, H = R.habitats.find((h) => h.id === habitat);
    const order = R.rankings[habitat] || [];
    const rank = new Map(order.map((r, i) => [r.id, i + 1]));
    const catOf = Object.fromEntries(R.categories.flatMap((c) => c.ids.map((id) => [id, c])));
    const byRank = (a, b) => (rank.get(a) ?? 99) - (rank.get(b) ?? 99);
    const name = (s) => s.acronym || s.id;

    const top = order.slice(0, 5).map((r, i) => {
      const s = R.studies[r.id], c = catOf[r.id];
      return `<li><span class="rk">${i + 1}</span><span class="tn"><b>${esc(name(s))}</b> ${esc(s.title)}</span><span class="cat ${c.id}">${esc(c.title)}</span></li>`;
    }).join("");

    const studyCard = (s) => {
      const r = rank.get(s.id), url = doiUrl(s.doi);
      return `<article class="study${r && r <= 5 ? " hot" : ""}">
        <div class="src-head"><span class="src-name">${esc(name(s))}</span>
          ${r ? `<span class="rank-pill">#${r} for ${esc(H.label.toLowerCase())}</span>` : '<span class="rank-pill dim">no close match</span>'}</div>
        <p class="src-title">${esc(s.title)}</p>
        ${s.objective ? `<p class="lbl">Goal</p><blockquote class="src-quote">“${esc(s.objective)}”</blockquote>` : ""}
        ${s.impact ? `<p class="lbl">Why it matters</p><blockquote class="src-quote">“${esc(s.impact)}”</blockquote>` : ""}
        <div class="study-foot">${THIN.has(s.evidence_level) ? '<span class="pill amber">little published text</span>' : ""}
          ${url ? `<a class="src-link" href="${url}" target="_blank" rel="noopener">Open NASA record ↗</a>` : ""}</div>
      </article>`;
    };

    const sections = R.categories.map((c) => `
      <section class="cat-sec">
        <div class="cat-head"><h3 class="cat-title ${c.id}">${esc(c.title)}</h3><p>${esc(c.blurb)}</p></div>
        <div class="study-grid">${[...c.ids].sort(byRank).map((id) => studyCard(R.studies[id])).join("")}</div>
      </section>`).join("");

    const earth = R.earth.map((e) => `
      <article class="src earth${e.quote ? "" : " nodata"}">
        <div class="src-head"><span class="src-name">${esc(e.title)}</span>${e.quote ? "" : '<span class="pill">No NASA data in PSI</span>'}</div>
        ${e.quote ? `<blockquote class="src-quote">“${esc(e.quote)}”</blockquote><p class="src-meta">${esc(e.acronym || e.id)} · NASA's words</p>` : ""}
        ${e.context ? `<p class="src-note">${esc(e.context)}</p>` : ""}
        ${e.doi ? `<a class="src-link" href="${doiUrl(e.doi)}" target="_blank" rel="noopener">Open NASA record ↗</a>` : ""}
      </article>`).join("");

    return `<div class="page research">
      <span class="eyebrow fire">Research map · ${Object.keys(R.studies).length} NASA investigations</span>
      <h1>Which NASA studies matter for which habitat?</h1>
      <p class="sub">Pick a crew habitat. Studies are ranked by how closely NASA's own documents match its fire-safety needs, and grouped by the job they do.</p>
      <div class="hab-chips" role="tablist" aria-label="Habitat">${R.habitats.map((h) =>
        `<button role="tab" aria-selected="${h.id === habitat}" data-habitat="${h.id}">${esc(h.label)}</button>`).join("")}</div>
      ${H.note ? `<p class="caveat">⚠ ${esc(H.note)}</p>` : ""}
      <div class="top5"><p class="eyebrow">Most relevant for ${esc(H.label.toLowerCase())}</p><ol>${top}</ol></div>
      ${sections}
      <section class="cat-sec">
        <div class="cat-head"><h3 class="cat-title earth">Fire safety on Earth</h3><p>Where NASA's space fire research reaches back home.</p></div>
        <div class="study-grid">${earth}</div>
      </section>
    </div>`;
  }

  function rankingPanel() {
    const R = D.research;
    return R.habitats.map((h) => `<div class="panel"><h2>${esc(h.label)}: rag.search() ranking</h2>
      <p class="small muted" style="margin:0 0 8px">Query: “${esc(h.query)}”</p>
      <table><thead><tr><th>#</th><th>Investigation</th><th>Score</th></tr></thead><tbody>
      ${(R.rankings[h.id] || []).map((r, i) => `<tr><td>${i + 1}</td><td>${esc(R.studies[r.id].acronym || r.id)} <span class="muted">${esc(r.id)}</span></td><td>${r.score}</td></tr>`).join("")}
      </tbody></table></div>`).join("") +
      `<p class="small muted">Score: mean of an investigation's best three passage scores plus a small boost for PSI's research-area labels, so document volume does not decide rank. Grouping into the four categories is by subject, fixed in frontend/build_cache.py.</p>`;
  }

  // ---------- flame map ----------
  // Every number on this screen is model.predict() output pre-computed by
  // build_cache.py over the slider grid; nothing is re-modelled here.
  const M = D.map;
  const mapState = { o2: D.ml.habitat.earth_air_o2, flowIdx: M.flows.indexOf(5) };
  const G = { W: 760, H: 440, L: 52, R: 150, T: 14, B: 46, xMin: Math.log10(0.42), xMax: Math.log10(42), yMin: 12.5, yMax: 33 };
  const gx = (f) => G.L + ((Math.log10(Math.max(f, 0.6)) - G.xMin) / (G.xMax - G.xMin)) * (G.W - G.L - G.R);
  const gy = (o) => G.T + (1 - (Math.min(Math.max(o, G.yMin), G.yMax) - G.yMin) / (G.yMax - G.yMin)) * (G.H - G.T - G.B);

  function mapChart() {
    const { W, H, L, R, T, B, yMax } = G, x = gx, y = gy;
    const lim = D.ml.limit, eb = D.ml.earth_bracket, hab = D.ml.habitat, top = M.tested_o2[1];
    const jit = (i, s) => (((Math.sin(i * 12.9898 + s) * 43758.5453) % 1) - 0.5);   // stable jitter
    const grid = [15, 20, 25, 30].map((v) =>
      `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${L - 8}" y="${y(v) + 4}" class="ax" text-anchor="end">${v}%</text>`).join("");
    const xt = [[0.6, "<1"], [1, "1"], [2, "2"], [5, "5"], [10, "10"], [20, "20"], [40, "40"]].map(([v, t]) =>
      `<text x="${x(v)}" y="${H - B + 18}" class="ax" text-anchor="middle">${t}</text>`).join("");
    const ref = (v, label, cls) =>
      `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="ref ${cls}"/><text x="${W - R + 8}" y="${y(v) + 4}" class="rl ${cls}">${esc(label)}</text>`;
    const pts = M.points.map((p, i) => {
      const cx = x(p.flow) + jit(i, 1) * 9, cy = y(p.o2 + jit(i, 2) * 0.16);
      const tip = `Run ${p.run} · ${p.o2}% oxygen · ${p.flow < 1 ? "<1" : p.flow} cm/s · ${p.outcome.replace("_", " ")}`;
      return p.burn
        ? `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4.5" class="pb" data-tip="${esc(tip)}"/>`
        : `<path d="M${(cx - 4).toFixed(1)} ${(cy - 4).toFixed(1)}l8 8m0 -8l-8 8" class="px" data-tip="${esc(tip)}"/>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" class="mapsvg" role="img" aria-label="${M.points.length} airflow steps from BASS-II acrylic rod runs, oxygen against airflow, with the Moon base at ${hab.moon_base_o2_min}% above everything tested.">
      <defs><pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="10" class="hatch"/></pattern></defs>
      <rect x="${L}" y="${y(yMax)}" width="${W - L - R}" height="${y(top) - y(yMax)}" fill="url(#hatch)"/>
      <text x="${L + 10}" y="${y(27)}" class="zone">NOT TESTED IN SPACE</text>
      <rect x="${L}" y="${y(lim.high)}" width="${W - L - R}" height="${y(lim.low) - y(lim.high)}" class="band"/>
      ${grid}${xt}
      ${ref(hab.moon_base_o2_min, `Moon base ≥${hab.moon_base_o2_min}%`, "moon")}
      ${ref(top, `Highest tested ${top}%`, "muted")}
      ${ref(hab.earth_air_o2, `Earth air ${hab.earth_air_o2}%`, "muted dot")}
      ${ref(eb.high, `Earth (1 g) limit ${eb.low}–${eb.high}%`, "muted dash")}
      <text x="${W - R + 8}" y="${y(lim.low) + 4}" class="rl fire">Space limit ${lim.low}–${lim.high}%</text>
      <g class="pts">${pts}</g>
      <path id="qstar" class="qstar" d=""/>
      <text x="${(L + W - R) / 2}" y="${H - 6}" class="ax lbl" text-anchor="middle">Airflow past the sample (cm/s)</text>
      <text transform="translate(14 ${(T + H - B) / 2}) rotate(-90)" class="ax lbl" text-anchor="middle">Oxygen</text>
    </svg>`;
  }

  function mapScreen() {
    return `<section class="page map">
      <span class="eyebrow fire">Measured in ${D.method.rod_runs} NASA space-station runs · ${esc(D.ml.material)}</span>
      <h2 class="title">Where does fire keep burning in space?</h2>
      <div class="map-grid">
        <figure class="chart">
          <div class="legend"><span><i class="lb"></i>Kept burning</span><span><i class="lx">×</i>Went out</span><span><i class="lq">★</i>Your setting</span></div>
          ${mapChart()}
          <div class="tip" id="tip" hidden></div>
        </figure>
        <aside class="ctl">
          <label>Oxygen <output id="o2out"></output>
            <input type="range" id="o2" min="${M.o2_values[0]}" max="${M.o2_values.at(-1)}" step="0.1" value="${mapState.o2}"></label>
          <div class="quick"><button data-o2="${D.ml.habitat.earth_air_o2}">Earth air</button><button data-o2="${D.ml.habitat.moon_base_o2_min}">Moon base</button></div>
          <label>Airflow <output id="flout"></output>
            <input type="range" id="fl" min="0" max="${M.flows.length - 1}" step="1" value="${mapState.flowIdx}"></label>
          <div class="result" id="result"></div>
        </aside>
      </div>
    </section>`;
  }

  function initMap() {
    const o2 = document.getElementById("o2"), fl = document.getElementById("fl");
    if (!o2) return;
    const svg = app.querySelector(".mapsvg"), tip = document.getElementById("tip");
    const lim = D.ml.limit, top = M.tested_o2[1], win = D.ml.burn_window_cm_s;
    const update = () => {
      mapState.o2 = +o2.value; mapState.flowIdx = +fl.value;
      const f = M.flows[mapState.flowIdx], o = mapState.o2;
      document.getElementById("o2out").textContent = `${o.toFixed(1)}%`;
      document.getElementById("flout").textContent = `${f} cm/s`;
      const cx = gx(f), cy = gy(o), s = 11;
      const star = [...Array(10)].map((_, k) => {
        const a = -Math.PI / 2 + k * Math.PI / 5, rr = k % 2 ? s * 0.45 : s;
        return `${(cx + rr * Math.cos(a)).toFixed(1)} ${(cy + rr * Math.sin(a)).toFixed(1)}`;
      });
      document.getElementById("qstar").setAttribute("d", `M${star.join("L")}Z`);
      const r = M.predict[String(f)][Math.round((o - M.o2_values[0]) * 10)];
      const out = document.getElementById("result");
      if (!r) {
        out.innerHTML = `<div class="big-p">—</div><p>No space-station runs this low in oxygen. No data is not the same as safe.</p>`;
        return;
      }
      const pct = (v) => `${Math.round(v * 100)}%`, above = o > top, tags = [];
      if (o >= lim.high && f >= win[0] && f <= win[1]) tags.push(`<span class="pill red">Above the space limit</span>`);
      if (above) tags.push(`<span class="pill amber">Never tested this high</span>`);
      if (f < win[0] || f > win[1]) tags.push(`<span class="pill">Near the airflow edge</span>`);
      out.innerHTML = `<p class="k">${above ? `Burn rate at the highest oxygen tested (${top}%)` : "Burn rate in similar space-station runs"}</p>
        <div class="big-p" style="color:${r[0] >= 0.5 ? "var(--fire)" : "var(--blue)"}">${pct(r[0])}</div>
        <p class="k">95% range ${pct(r[1])}–${pct(r[2])}</p><div class="pills">${tags.join("")}</div>
        ${above ? `<p class="small muted">More oxygen is assumed never to make burning less likely, so this is a floor, not a prediction.</p>` : ""}`;
    };
    o2.addEventListener("input", update);
    fl.addEventListener("input", update);
    app.querySelectorAll("[data-o2]").forEach((b) => b.addEventListener("click", () => { o2.value = b.dataset.o2; update(); }));
    svg.addEventListener("mousemove", (e) => {
      const t = e.target.closest("[data-tip]");
      if (!t) { tip.hidden = true; return; }
      const fig = svg.parentElement.getBoundingClientRect();
      tip.textContent = t.dataset.tip; tip.hidden = false;
      tip.style.left = `${e.clientX - fig.left + 12}px`; tip.style.top = `${e.clientY - fig.top - 30}px`;
    });
    svg.addEventListener("mouseleave", () => { tip.hidden = true; });
    update();
  }

  // ---------- method & sources ----------
  function methodScreen() {
    const m = D.method, c = D.corpus, f = D.files, ml = D.ml, rc = m.recheck;
    const lvl = (l) => THIN.has(l) ? `<span class="lvl ${esc(l)}">${esc(String(l).replace("_", " "))}</span>` : "";
    return `<div class="page method">
      <span class="eyebrow fire">Method &amp; sources</span>
      <h1>How FlameScope works</h1>
      <div class="steps">
        <div class="panel"><b>1 · Find NASA's words</b><p>We search ${fmt(c.passages)} passages from ${c.investigations} combustion investigations in NASA's Physical Sciences Informatics archive (${fmt(f.total)} files in total, counted ${esc(f.counted_on)}). Every quote links to its NASA record.</p></div>
        <div class="panel"><b>2 · Summarise, then check</b><p>A local AI model${model ? ` (${esc(model)}, run with Ollama)` : ""} writes a short summary from those passages only. A checker withholds the summary if it contains a measured value that is not written in a source, or cites an investigation that was not found.</p></div>
        <div class="panel"><b>3 · Measure the flame limit</b><p>From the ${m.rod_runs} acrylic-rod runs in BASS-II, a space-station experiment, we measured where the rods stop burning: between ${ml.limit.low}% and ${ml.limit.high}% oxygen.</p></div>
      </div>

      <div class="panel"><h2>The flammability model</h2><ol class="list">
        <li><b>Data.</b> NASA PSI BASS-II (PSI-25): ${m.bass2_runs} space-station runs of solid fuels burning in a low-speed flow duct at ${ml.o2_tested[0]}–${ml.o2_tested[1]}% oxygen. The table has no outcome column; outcomes exist only as operator notes such as <code>5 3 2 ext</code>.</li>
        <li><b>Labels.</b> A parser splits each run into one row per airflow step (${m.label_steps} steps). Outcomes (burn, extinguish, blowoff, no ignition) come from the notes, with AI help for ambiguous rows, which are marked in the data. Unclear rows are labelled unknown, not guessed. ${ml.runs} labelled steps from ${m.rod_runs} acrylic-rod runs are used.</li>
        <li><b>Consistency check.</b> A second, blind AI labelling pass agreed on <b>${(rc.agree * 100).toFixed(1)}%</b> of ${rc.n} sampled steps. This measures labelling consistency, not human validation.</li>
        <li><b>Model.</b> An empirical envelope: the observed burn rate in each oxygen × airflow cell, counted once per run, with 95% Jeffreys intervals. Logistic regression was tried and rejected: operators lowered airflow until every flame went out, so extinctions carry almost no oxygen information and the fit was unphysical.</li>
        <li><b>Bounds.</b> The space limit is bracketed by two runs (${esc(ml.limit.evidence)}). The Earth comparison, ${ml.earth_bracket.low}–${ml.earth_bracket.high}%, uses the same rods (Marcum, Olson &amp; Ferkul 2016).</li>
      </ol></div>

      <div class="panel"><h2>Limitations</h2><ul class="list">
        <li>Only acrylic (PMMA) rods have enough runs for a limit.</li>
        <li>No pressure column in BASS-II; space-station cabin pressure is assumed.</li>
        <li>NASA's archive has no partial-gravity (Moon or Mars) combustion data. Microgravity results are not extrapolated to them.</li>
        <li>Everything above ${ml.o2_tested[1]}% oxygen is extrapolation; a ${ml.habitat.moon_base_o2_min}% Moon base sits ${D.moon_gap_points} points beyond the BASS-II range.</li>
        <li>The checker proves numbers and citations exist in the sources, not that the AI's reasoning is right. AI summaries are labelled and can be wrong.</li>
        <li>Coverage is uneven: some investigations publish thousands of passages, others almost none. Those are marked “thin”.</li>
      </ul></div>

      <div class="panel"><h2>NASA investigations searched</h2>
        <table><thead><tr><th>PSI ID</th><th>Investigation</th><th>DOI</th></tr></thead><tbody>
        ${m.investigations.map((r) => `<tr><td>${esc(r.id)}</td><td><b>${esc(r.acronym)}</b> ${esc(r.title)} ${lvl(r.evidence_level)}</td><td>${r.doi ? `<a href="${doiUrl(r.doi)}" target="_blank" rel="noopener">${esc(r.doi)}</a>` : ""}</td></tr>`).join("")}
        </tbody></table></div>

      <div class="panel"><h2>Other references</h2><ol class="refs">${ml.references.map((r) => `<li>${esc(r)}</li>`).join("")}</ol></div>

      <div class="panel"><h2>AI use disclosure</h2><ul class="list">
        <li>Code for the parser, model, search, checker and this site was written with AI coding assistance (Claude) and reviewed by the team.</li>
        <li>Outcome labels for ambiguous space-station notes were extracted with AI help and are marked as such in the data.</li>
        <li>Answer summaries are generated by a local AI model, labelled “AI summary”, and checked against NASA's text before they are shown.</li>
        <li>The project idea and scientific framing are the team's own. No AI-generated images are used.</li>
      </ul></div>
    </div>`;
  }

  // ---------- render + routing ----------
  function render() {
    const page = current?.page || "home";
    document.body.dataset.page = page;
    document.querySelectorAll(".nav [data-goto]").forEach((a) => a.toggleAttribute("aria-current", a.dataset.goto === page));
    if (page === "map") { app.innerHTML = mapScreen(); initMap(); }
    else if (page === "research") app.innerHTML = researchScreen();
    else if (page === "method") app.innerHTML = methodScreen();
    else {
      app.innerHTML = workspace();
      if (!counted) countUp();
    }
    if (!drawer.hidden) drawerBody.innerHTML = drawerContent();
  }

  // Only the results panel changes while a live answer loads, so the input
  // panel keeps focus and the page does not jump.
  function renderResults() {
    const el = document.getElementById("results");
    if (!el || current?.page) return render();
    el.innerHTML = resultView();
    app.querySelector(".mission")?.classList.toggle("compact", !!current);
    if (!drawer.hidden) drawerBody.innerHTML = drawerContent();
  }

  function countUp() {
    const el = app.querySelector("[data-count]");
    if (!el) return;
    counted = true;
    const target = +el.dataset.count;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = fmt(target); return; }
    const t0 = performance.now(), dur = 1400;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      el.textContent = fmt(Math.round(target * (1 - Math.pow(1 - k, 3))));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function go(hash) {
    const id = hash.replace(/^#/, "").split(":")[0];
    const p = byId[id];
    current = PAGES.has(id) ? { page: id } : p ? { question: p.question, ans: p.ask, preset: p } : null;
    render();
    // In the one-column (phone) layout the result sits below the inputs, so
    // bring it into view; side by side, keep the page still.
    if (p && matchMedia("(max-width: 900px)").matches) document.getElementById("results")?.scrollIntoView({ block: "start" });
    else window.scrollTo(0, 0);
  }
  const setHash = (id) => {
    const h = `#${id || "home"}`;
    if (location.hash === h) go(h); else location.hash = h;
  };

  async function ask(q) {
    q = norm(q);
    if (!q) return;
    const p = PRESETS.find((x) => x.question.toLowerCase() === q.toLowerCase());
    if (p) return setHash(p.id);
    if (location.hash && location.hash !== "#home") history.replaceState(null, "", "#home");
    // Questions answered at build time work everywhere, including the public
    // static site, with no AI server.
    const ex = EXAMPLES.get(q.toLowerCase().replace(/[?.!\s]+$/, ""));
    if (ex && !live[q]) {
      current = { question: ex.question, ans: ex.ask, preset: null };
      return renderResults();
    }
    if (!LIVE) {
      current = { question: q, error: "This public version answers the scenarios and the example questions on the left. Answers to new questions come from an AI model that runs on the team's own computer, so they aren't available here." };
      return renderResults();
    }
    current = { question: q, loading: true };
    renderResults();
    try {
      if (!live[q]) {
        const r = await fetch(`/api/ask?q=${encodeURIComponent(q)}`);
        const body = await r.json();
        if (!r.ok) throw new Error(body.error || r.statusText);
        live[q] = body;
      }
      if (current?.question === q) { current = { question: q, ans: live[q], preset: null }; renderResults(); }
    } catch (e) {
      current = { question: q, error: `Could not get an answer: ${e.message}` };
      renderResults();
    }
  }

  // ---------- events ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-preset],[data-goto],[data-drawer],[data-close],[data-habitat],[data-example]");
    if (!t) return;
    if (t.dataset.example) {
      const box = document.getElementById("q");
      if (box) box.value = t.dataset.example;
      app.querySelectorAll(".ex-q").forEach((b) => b.classList.toggle("on", b === t));
      ask(t.dataset.example);
    }
    else if (t.dataset.habitat) { habitat = t.dataset.habitat; render(); }
    else if (t.dataset.preset) setHash(t.dataset.preset);
    else if (t.dataset.goto) setHash(t.dataset.goto);
    else if (t.hasAttribute("data-drawer")) openDrawer(drawer.hidden);
    else if (t.hasAttribute("data-close")) openDrawer(false);
  });
  document.addEventListener("submit", (e) => {
    const f = e.target.closest("[data-ask]");
    if (!f) return;
    e.preventDefault();
    ask(f.elements.q.value);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("textarea[name=q]") && !e.shiftKey) {
      e.preventDefault(); e.target.form.requestSubmit(); return;
    }
    if (e.key === "Escape" && !drawer.hidden) { openDrawer(false); return; }
    if (e.target.matches("input, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
    const n = Number(e.key);
    if (n >= 1 && n <= PRESETS.length) setHash(PRESETS[n - 1].id);
    else if (e.key === "Escape" || e.key === "h") setHash("home");
    else if (e.key === "m") setHash("map");
    else if (e.key === "d") openDrawer(drawer.hidden);
    else if (e.key === "ArrowRight" || e.key === "n") {
      const i = PRESETS.findIndex((p) => p.id === current?.preset?.id);
      if (i >= 0) setHash(PRESETS[i + 1]?.id || "home");
    }
  });
  window.addEventListener("hashchange", () => go(location.hash));

  if (location.protocol.startsWith("http")) {
    fetch("/api/health").then((r) => r.ok ? r.json() : null)
      .then((j) => { LIVE = !!j?.live; if (!drawer.hidden) drawerBody.innerHTML = drawerContent(); }).catch(() => {});
  }
  go(location.hash);
})();
