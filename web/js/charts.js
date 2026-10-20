/* ECharts option builders. One theme, read from the CSS custom properties so
   light/dark switching costs nothing but a re-render. */

const registry = new Map();

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function palette() {
  return {
    ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), faint: css("--faint"),
    hair: css("--hair"), hairSoft: css("--hair-soft"), grid: css("--grid"),
    panel: css("--panel"), gold: css("--gold"), teal: css("--teal"), sky: css("--sky"),
    rose: css("--rose"), violet: css("--violet"), lime: css("--lime"),
    pos: css("--pos"), neg: css("--neg"), warn: css("--warn"), band: css("--band"),
  };
}

function baseTooltip(p) {
  return {
    trigger: "axis",
    backgroundColor: p.panel,
    borderColor: p.hair,
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: p.ink2, fontSize: 11, fontFamily: css("--mono") },
    axisPointer: {
      type: "line",
      lineStyle: { color: p.faint, width: 1, type: [3, 3] },
    },
    extraCssText: "box-shadow: 0 12px 30px -14px rgba(0,0,0,.7); border-radius: 8px;",
  };
}

function recBands(recessions, p) {
  if (!recessions || !recessions.length) return [];
  return [{
    silent: true,
    itemStyle: { color: p.band },
    data: recessions.map(([a, b]) => [{ xAxis: a }, { xAxis: b }]),
  }];
}

function timeAxis(p, zoom) {
  return {
    type: "time",
    boundaryGap: false,
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { show: false },
    axisLabel: {
      color: p.faint, fontSize: 9, fontFamily: css("--mono"),
      hideOverlap: true,
      formatter: { year: "{yyyy}", month: "{MMM} '{yy}", day: "{MMM} '{yy}" },
    },
  };
}

function valueAxis(p, { unit = "", fmt = null } = {}) {
  return {
    type: "value",
    scale: true,
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: p.grid, width: 1 } },
    axisLabel: {
      color: p.faint, fontSize: 9, fontFamily: css("--mono"),
      formatter: fmt || ((v) => (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(unit === "bp" ? 0 : 2))),
    },
  };
}

export function lineChart(el, { series, rec = [], yFmt = null, unit = "" }) {
  const p = palette();
  const chart = get(el);
  const opt = {
    animation: false,
    grid: { left: 48, right: 16, top: 18, bottom: 24 },
    tooltip: baseTooltip(p),
    xAxis: timeAxis(p),
    yAxis: valueAxis(p, { unit, fmt: yFmt }),
    series: series.map((s, i) => ({
      name: s.label,
      type: "line",
      showSymbol: false,
      symbol: "circle",
      symbolSize: 4,
      sampling: "lttb",
      data: s.points.map((d) => [d.t, d.v]),
      lineStyle: { width: s.width || 1.6, color: s.color, type: s.dash || "solid" },
      itemStyle: { color: s.color },
      areaStyle: s.area ? {
        origin: 0,
        color: {
          type: "linear", x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: alpha(s.color, .20) },
            { offset: 1, color: alpha(s.color, .02) },
          ],
        },
      } : undefined,
      markArea: i === 0 ? (rec.length ? recBands(rec, p)[0] : undefined) : undefined,
      markLine: s.ref != null ? {
        silent: true, symbol: "none",
        lineStyle: { color: p.faint, type: [4, 4], width: 1 },
        label: { formatter: s.refLabel || "", color: p.faint, fontSize: 9, fontFamily: css("--mono") },
        data: [{ yAxis: s.ref }],
      } : undefined,
    })),
  };
  chart.setOption(opt, true);
  return chart;
}

export function spark(el, points, color, { height = 52 } = {}) {
  const p = palette();
  const chart = get(el);
  chart.setOption({
    animation: false,
    grid: { left: 0, right: 0, top: 6, bottom: 2 },
    xAxis: { type: "time", show: false, boundaryGap: false },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { show: false },
    series: [{
      type: "line", showSymbol: false, smooth: false, sampling: "lttb",
      data: points.map((d) => [d.t, d.v]),
      lineStyle: { width: 1.4, color },
      areaStyle: {
        color: {
          type: "linear", x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: alpha(color, .22) },
            { offset: 1, color: alpha(color, 0) },
          ],
        },
      },
    }],
  }, true);
  return chart;
}

export function tinyLine(el, points, color) {
  const chart = get(el);
  chart.setOption({
    animation: false,
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: "time", show: false, boundaryGap: false },
    yAxis: { type: "value", show: false, scale: true },
    series: [{
      type: "line", showSymbol: false, sampling: "lttb",
      data: points.map((d) => [d.t, d.v]),
      lineStyle: { width: 1.1, color },
    }],
  }, true);
  return chart;
}

export function clock(el, { points, current }) {
  const p = palette();
  const chart = get(el);

// scale to the recent path, not to the 1970s: a single 8-sigma outlier must
  // not flatten the last three years into the origin
  const recent = points.slice(-60);
  const mags = recent.flatMap((d) => [Math.abs(d.g), Math.abs(d.i)]).sort((a, b) => a - b);
  const p95 = mags.length ? mags[Math.floor(mags.length * 0.95)] : 1.6;
  const ext = Math.round(Math.min(4.5, Math.max(1.8, p95 * 1.35)) * 2) / 2;
  const trail = points.slice(-36);
  const old = points.slice(0, -36);

  const quad = (x0, y0, x1, y1, color) => ([{ xAxis: x0, yAxis: y0 }, { xAxis: x1, yAxis: y1, itemStyle: { color } }]);

  chart.setOption({
    animation: false,
    grid: { left: 54, right: 22, top: 26, bottom: 34 },
    tooltip: {
      ...baseTooltip(p),
      trigger: "item",
      formatter: (d) => {
        const v = d.value || (d.data && d.data.value) || [];
        if (!v || v.length < 2) return "";
        const [g, i] = v;
        const m = (d.data && d.data.name) || "";
        return `<b>${m}</b><br/>growth ${g >= 0 ? "+" : ""}${g.toFixed(2)}σ<br/>` +
               `inflation ${i >= 0 ? "+" : ""}${i.toFixed(2)}σ`;
      },
    },
    xAxis: {
      type: "value", min: -ext, max: ext,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: p.grid } },
      axisLabel: { color: p.faint, fontSize: 9, fontFamily: css("--mono"),
        formatter: (v) => (Math.abs(v) < 1e-9 ? "0" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`) },
      name: "growth impulse →", nameLocation: "middle", nameGap: 22,
      nameTextStyle: { color: p.faint, fontSize: 9, fontFamily: css("--mono") },
    },
    yAxis: {
      type: "value", min: -ext, max: ext,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: p.grid } },
      axisLabel: { color: p.faint, fontSize: 9, fontFamily: css("--mono"),
        formatter: (v) => (Math.abs(v) < 1e-9 ? "0" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`) },
      name: "inflation impulse ↑", nameLocation: "middle", nameGap: 34,
      nameTextStyle: { color: p.faint, fontSize: 9, fontFamily: css("--mono") },
    },
    series: [
      {
        type: "line", data: [], silent: true, tooltip: { show: false },
        markArea: {
          silent: true,
          data: [
            quad(-ext, 0, 0, ext, alpha(p.neg, .05)),
            quad(0, 0, ext, ext, alpha(p.warn, .05)),
            quad(-ext, -ext, 0, 0, alpha(p.sky, .05)),
            quad(0, -ext, ext, 0, alpha(p.pos, .05)),
          ],
        },
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: p.faint, type: [2, 3], width: 1, opacity: .7 },
          label: { show: false },
          data: [{ xAxis: 0 }, { yAxis: 0 }],
        },
      },
      {
        type: "scatter", data: old.map((d) => ({ value: [d.g, d.i], name: d.p })), symbolSize: 3,
        itemStyle: { color: p.teal, opacity: .18 }, silent: true,
      },
      {
        type: "line", data: trail.map((d) => ({ value: [d.g, d.i], name: d.p })),
        showSymbol: true, symbolSize: 3,
        lineStyle: { width: 1.5, color: p.teal, opacity: .85 },
        itemStyle: { color: p.teal },
      },
      {
        type: "effectScatter",
        data: current ? [{ value: [current.g, current.i], name: current.p }] : [],
        symbolSize: 10, rippleEffect: { scale: 3.2, brushType: "stroke" },
        itemStyle: { color: p.gold, shadowBlur: 12, shadowColor: p.gold },
        z: 10,
      },
    ],
  }, true);
  return chart;
}

export function decompBar(el, items) {
  const p = palette();
  const chart = get(el);
  const rows = items.filter((d) => d.contribution != null).slice().reverse();
  chart.setOption({
    animation: false,
    grid: { left: 120, right: 64, top: 8, bottom: 22 },
    tooltip: {
      ...baseTooltip(p), trigger: "item",
      formatter: (d) => {
        const it = rows[d.dataIndex];
        return `<b>${it.title}</b><br/>weight ${it.weight} · sign ${it.sign > 0 ? "+" : "−"}<br/>` +
               `z ${it.z == null ? "—" : it.z.toFixed(2)}<br/>contribution ${it.contribution.toFixed(3)}σ`;
      },
    },
    xAxis: {
      type: "value", axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: p.grid } },
      axisLabel: { color: p.faint, fontSize: 9, fontFamily: css("--mono") },
    },
    yAxis: {
      type: "category",
      data: rows.map((d) => d.title),
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: p.ink2, fontSize: 10.5, fontFamily: css("--sans") },
    },
    series: [{
      type: "bar", barWidth: 11,
      data: rows.map((d) => ({
        value: d.contribution,
        itemStyle: { color: d.contribution >= 0 ? p.pos : p.neg, opacity: .82, borderRadius: 2 },
      })),
      label: {
        show: true, position: "right", color: p.muted, fontSize: 9.5,
        fontFamily: css("--mono"),
        formatter: (d) => `${d.value >= 0 ? "+" : ""}${d.value.toFixed(3)}`,
      },
    }],
  }, true);
  return chart;
}

function alpha(color, a) {
  const c = color.trim();
  if (c.startsWith("#")) {
    const n = c.length === 4
      ? [1, 2, 3].map((i) => parseInt(c[i] + c[i], 16))
      : [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
    return `rgba(${n[0]},${n[1]},${n[2]},${a})`;
  }
  if (c.startsWith("rgb")) return c.replace(/rgba?\(([^)]+)\)/, (_, v) => {
    const parts = v.split(",").map((x) => x.trim()).slice(0, 3);
    return `rgba(${parts.join(",")},${a})`;
  });
  return c;
}

function get(el) {
  let chart = registry.get(el);
  if (!chart) {
    chart = echarts.init(el, null, { renderer: "canvas" });
    registry.set(el, chart);
  }
  return chart;
}

export function resizeAll() {
  registry.forEach((c) => c.resize());
}

export function disposeAll() {
  registry.forEach((c) => c.dispose());
  registry.clear();
}
