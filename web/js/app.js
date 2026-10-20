import { api } from "./api.js";
import * as C from "./charts.js";

const state = {
  years: 10,
  decomp: "us.agg.growth",
  overview: null,
  series: {},
  palette: C.palette(),
};

const SPARK_COLOR = {
  "us.agg.growth": () => state.palette.teal,
  "us.agg.inflation": () => state.palette.rose,
  "us.agg.financial": () => state.palette.sky,
  "us.agg.policy": () => state.palette.violet,
  "us.agg.risk": () => state.palette.gold,
};

const CHART_DEFS = [
  {
    title: "Policy and the curve",
    sub: "effective fed funds, 2Y and 10Y constant maturity · percent",
    series: [
      { id: "us.rates.ust10y", label: "UST 10Y", color: "sky" },
      { id: "us.rates.ust2y", label: "UST 2Y", color: "violet" },
      { id: "us.rates.effr", label: "EFFR", color: "gold" },
    ],
  },
  {
    title: "Term structure",
    sub: "10Y − 2Y (area) and 10Y − 3M, basis points · shaded = NBER recession",
    series: [
      { id: "us.curve.10y2y", label: "10Y − 2Y", color: "teal", area: true },
      { id: "us.curve.10y3m", label: "10Y − 3M", color: "muted", dash: "dashed" },
    ],
  },
  {
    title: "Real rates",
    sub: "10Y TIPS real yield and 10Y breakeven inflation · percent",
    series: [
      { id: "us.rates.real10y", label: "10Y real", color: "teal" },
      { id: "us.infl.be10y", label: "10Y breakeven", color: "gold" },
    ],
  },
  {
    title: "Inflation, robustly",
    sub: "core PCE 3M annualised vs trimmed-mean 3M · percent",
    series: [
      { id: "us.infl.pce_core_3m", label: "Core PCE 3M", color: "rose" },
      { id: "us.infl.trimmed_3m", label: "Trimmed mean", color: "lime", dash: "dashed" },
    ],
  },
  {
    title: "Activity",
    sub: "real GDP YoY, industrial production YoY, CLI 6M change · percent",
    series: [
      { id: "us.growth.gdp_yoy", label: "GDP YoY", color: "sky" },
      { id: "us.growth.ip_yoy", label: "IP YoY", color: "teal" },
      { id: "us.growth.cli_6m", label: "CLI 6M", color: "violet" },
    ],
  },
  {
    title: "Market risk",
    sub: "S&P 500 drawdown (percent) and VIX z-score (sigma)",
    series: [
      { id: "us.market.spx_dd", label: "Drawdown", color: "rose", area: true },
      { id: "us.market.vix_z", label: "VIX z", color: "violet" },
    ],
  },
];

/* ---------- helpers ---------------------------------------- */

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const pct = (v) => (v == null ? "—" : `${Math.round(v)}`);
const signed = (v, d = 2) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}`);
const signalClass = (s) => (s && s.level ? s.level : "");

/* Levels are unsigned unless the unit is sigma; changes are always signed. */
function level(v, unit) {
  if (v == null) return "—";
  if (unit === "z") return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
  if (unit === "score") return v.toFixed(1);
  if (unit === "idx" || unit === "index") return v.toFixed(1);
  if (unit === "bp") return `${v >= 0 ? "" : "-"}${Math.abs(v).toFixed(0)}`;
  return v.toFixed(2);
}

function fmtPeriod(p) {
  if (!p) return "—";
  return p.length === 10 ? p : p;
}

/* ---------- hero ------------------------------------------- */

function renderHero(hero) {
  const host = $("#hero");
  host.innerHTML = "";
  hero.forEach((h) => {
    const card = el("article", "kpi");
    card.innerHTML = `
      <div class="kpi-top">
        <span class="kpi-label">${h.label}</span>
        <span class="chip ${signalClass(h.signal)}">${h.signal.text}</span>
      </div>
      <div class="kpi-value">${level(h.value, h.unit)}<span class="unit">${h.unit === "z" ? "σ" : h.unit === "score" ? "" : h.unit}</span></div>
      <div class="kpi-spark"></div>
      <div class="kpi-foot">
        <span>3M <b>${signed(h.chg_3m)}</b></span>
        <span>${h.pct_rank == null ? "" : h.pct_rank + "th pctile"}</span>
      </div>`;
    card.addEventListener("click", () => openDrawer(h.id));
    host.appendChild(card);
    C.spark($(".kpi-spark", card), h.spark, (SPARK_COLOR[h.id] || (() => state.palette.gold))());
  });
}

/* ---------- regime ----------------------------------------- */

function renderRegime(regime) {
  const pts = regime.points;
  const current = pts[pts.length - 1];
  C.clock($("#regime-chart"), { points: pts, current });
  $("#phase-name").textContent = regime.current.quadrant;
  $("#phase-desc").textContent = regime.current.desc;
  const chip = $("#regime-chip");
  chip.textContent = `${current ? signed(current.g, 2) : "—"}σ / ${current ? signed(current.i, 2) : "—"}σ`;
  chip.className = "chip muted";
}

/* ---------- checklist -------------------------------------- */

function renderChecklist(cl) {
  const host = $("#checklist");
  host.innerHTML = "";
  cl.items.forEach((it) => {
    const li = el("li");
    li.innerHTML = `
      <span class="nm">${it.label}<span class="dt">${it.detail}</span></span>
      <span class="chip ${it.flag ? "neg" : "pos"}">${it.flag ? "flag" : "clear"}</span>`;
    host.appendChild(li);
  });
  const chip = $("#checklist-chip");
  chip.textContent = `${cl.flags} / ${cl.total} active`;
  chip.className = `chip ${cl.flags >= 4 ? "neg" : cl.flags >= 2 ? "warn" : "pos"}`;
  $("#checklist-note").textContent =
    "Thresholds, not probabilities. Change any of them in the catalogue and the count moves — that is the point.";
}

/* ---------- decomposition ---------------------------------- */

function renderDecompTabs(hero) {
  const host = $("#decomp-tabs");
  host.innerHTML = "";
  hero.forEach((h) => {
    const b = el("button", "", h.label);
    b.setAttribute("aria-pressed", String(h.id === state.decomp));
    b.addEventListener("click", () => {
      state.decomp = h.id;
      renderDecompTabs(state.overview.hero);
      renderDecomp(state.overview.hero);
    });
    host.appendChild(b);
  });
}

function renderDecomp(hero) {
  const item = hero.find((h) => h.id === state.decomp) || hero[0];
  if (!item) return;
  C.decompBar($("#decomp-chart"), item.decomposition);
  const side = $("#decomp-side");
  side.innerHTML = `
    <h4>${item.title}</h4>
    <p>${item.method || ""}</p>
    <p style="margin-top:8px">Contributions are <code>weight × sign × z(input)</code>, divided by
    the total absolute weight, so they add up to the ${signed(item.value)}σ reading.</p>`;
}

/* ---------- charts ----------------------------------------- */

function renderCharts() {
  const host = $("#charts");
  host.innerHTML = "";
  CHART_DEFS.forEach((def) => {
    const card = el("article", "card span-6 chart-card");
    card.innerHTML = `
      <header class="card-head">
        <div><h2>${def.title}</h2><p>${def.sub}</p></div>
        <div class="legend">${def.series.map((s) =>
          `<span><i style="background:var(--${s.color === "muted" ? "faint" : s.color})"></i>${s.label}</span>`).join("")}</div>
      </header>
      <div class="chart"></div>`;
    host.appendChild(card);

    const series = def.series
      .map((s) => {
        const payload = state.series[s.id];
        if (!payload) return null;
        return {
          label: s.label,
          color: s.color === "muted" ? state.palette.faint : state.palette[s.color],
          points: payload.points,
          area: s.area,
          dash: s.dash,
        };
      })
      .filter(Boolean);

    C.lineChart($(".chart", card), {
      series,
      rec: state.overview.recessions || [],
      yFmt: def.yFmt || null,
    });
  });
}

/* ---------- state table ------------------------------------ */

function renderState(rows) {
  const tbody = $("#state-table tbody");
  tbody.innerHTML = "";
  rows.forEach((r) => {
    const tr = el("tr", r.layer === "composite" ? "agg" : "");
    const z = r.z == null ? 0 : Math.max(-3, Math.min(3, r.z));
    const w = (Math.abs(z) / 3) * 23;
    const left = z >= 0 ? 23 : 23 - w;
    const col = Math.abs(z) > 1.5 ? "var(--warn)" : "var(--faint)";
    tr.innerHTML = `
      <td>${r.label}<span class="sid">${r.id}</span></td>
      <td>${level(r.value, r.unit)}</td>
      <td>${r.chg_3m == null ? "—" : (r.unit === "bp" ? signed(r.chg_3m, 0) : signed(r.chg_3m))}</td>
      <td><span class="zbar"><i style="left:${left}px;width:${Math.max(1.5, w)}px;background:${col}"></i></span><span class="znum">${r.z == null ? "—" : r.z.toFixed(2)}</span></td>
      <td>${pct(r.pct_rank)}</td>
      <td>${r.signal ? `<span class="chip ${signalClass(r.signal)}">${r.signal.text}</span>` : ""}</td>
      <td><span class="mini" data-id="${r.id}"></span></td>`;
    tr.addEventListener("click", () => openDrawer(r.id));
    tbody.appendChild(tr);
    C.tinyLine($(`.mini[data-id="${r.id}"]`, tbody), r.spark, state.palette.faint);
  });
  $("#state-count").textContent = `${rows.length} series`;
}

/* ---------- provenance & notes ----------------------------- */

function renderProv(rows) {
  const tb = $("#prov-table tbody");
  tb.innerHTML = rows.map((r) => `
    <tr>
      <td>${r.title}<br><span style="color:var(--faint)">${r.id}</span></td>
      <td>${r.source} · ${r.dataset || ""} · ${r.code || ""}</td>
      <td>${r.coverage || ""}</td>
    </tr>`).join("");
}

function renderNotes(notes) {
  $("#notes").innerHTML = notes.map((n) => `<p>${n}</p>`).join("");
}

/* ---------- drawer ----------------------------------------- */

function closeDrawer() {
  $("#drawer").classList.remove("on");
  $("#scrim").classList.remove("on");
  $("#drawer").setAttribute("aria-hidden", "true");
}

async function openDrawer(id) {
  const d = $("#drawer");
  d.classList.add("on");
  $("#scrim").classList.add("on");
  d.setAttribute("aria-hidden", "false");
  const body = $("#drawer-body");
  body.innerHTML = `<div class="empty">loading…</div>`;
  try {
    const s = await api.one(id, state.years);
    body.innerHTML = `
      <span class="muted">${s.layer} · ${s.group} · ${s.freq}</span>
      <h3>${s.title}</h3>
      <div class="big">${s.last == null ? "—" : signed(s.last, 2)} <span class="muted">${s.unit}</span></div>
      <div class="muted">last ${fmtPeriod(s.last_period)} · z ${s.z ?? "—"} · ${s.pct_rank ?? "—"}th pctile</div>
      <div class="drawer-chart"></div>
      <p><b>Method.</b> ${s.method || "—"}</p>
      <p><b>Question.</b> ${s.question || "—"}</p>
      ${s.inputs ? `<p><b>Inputs.</b> ${s.inputs.map((i) =>
        `${i.title} (w ${i.weight}${i.sign < 0 ? ", −" : ", +"})`).join(" · ")}</p>` : ""}`;
    C.lineChart($(".drawer-chart", body), {
      series: [{
        label: s.short || s.title,
        color: state.palette.gold,
        points: s.points,
        area: true,
      }],
      rec: state.overview.recessions || [],
    });
  } catch (e) {
    body.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

/* ---------- boot ------------------------------------------- */

async function loadCharts() {
  const ids = [...new Set(CHART_DEFS.flatMap((d) => d.series.map((s) => s.id)))];
  const res = await api.series(ids, state.years);
  state.series = res.series;
  renderCharts();
}

async function boot() {
  const [ov, prov] = await Promise.all([api.overview(), api.provenance()]);
  state.overview = ov;
  state.palette = C.palette();

  const tr = ov.meta.tracker || { recorded: 0, changed: 0, date: null };
  $("#asof").innerHTML =
    `as of <b>${ov.meta.as_of || "—"}</b> · vintage <b>${ov.meta.vintage ?? "—"}</b>` +
    ` · ${ov.meta.layers.raw} raw / ${ov.meta.layers.derived} derived / ${ov.meta.layers.composite} composite` +
    ` · tracker <b>${tr.recorded}</b> prints${tr.changed ? `, ${tr.changed} revised` : ""}`;

  renderHero(ov.hero);
  renderRegime(ov.regime);
  renderChecklist(ov.checklist);
  renderDecompTabs(ov.hero);
  renderDecomp(ov.hero);
  renderState(ov.state);
  renderProv(prov.series);
  renderNotes(ov.notes);
  await loadCharts();

  document.querySelectorAll("#range-seg button").forEach((b) => {
    b.addEventListener("click", async () => {
      state.years = Number(b.dataset.years);
      document.querySelectorAll("#range-seg button").forEach((x) =>
        x.setAttribute("aria-pressed", String(x === b)));
      await loadCharts();
    });
  });

  $("#theme-toggle").addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    localStorage.setItem("msb.theme", next);
    state.palette = C.palette();
    C.disposeAll();
    renderHero(state.overview.hero);
    renderRegime(state.overview.regime);
    renderDecomp(state.overview.hero);
    renderState(state.overview.state);
    renderCharts();
  });

  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  let t = null;
  window.addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(() => C.resizeAll(), 120);
  });
}

boot().catch((e) => {
  $("#asof").textContent = "API unreachable — start it with: python -m macroboard serve";
  console.error(e);
});
