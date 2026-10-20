/* Thin API client — the frontend knows nothing about SQLite. */

const BASE = "/api";

async function j(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${url}`);
  return r.json();
}

export const api = {
  health: () => j(`${BASE}/health`),
  meta: () => j(`${BASE}/meta`),
  overview: () => j(`${BASE}/overview`),
  catalog: () => j(`${BASE}/catalog`),
  provenance: () => j(`${BASE}/provenance`),
  trackers: () => j(`${BASE}/trackers`),
  series: (ids, years = 0) =>
    j(`${BASE}/series?ids=${encodeURIComponent(ids.join(","))}&years=${years}`),
  one: (id, years = 0) => j(`${BASE}/series/${encodeURIComponent(id)}?years=${years}`),
};
