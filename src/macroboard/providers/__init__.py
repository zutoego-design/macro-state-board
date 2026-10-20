"""Provider adapters.

Every adapter returns ``list[(period, value)]`` with the period already
normalised by the caller (see ``db.normalize_period``) and value either a
float or ``None``. Adapters do no analytics — that is L1's job.
"""

from __future__ import annotations

import urllib.parse

from . import http

DBNOMICS = "https://api.db.nomics.world/v22/series"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart"
OECD = "https://sdmx.oecd.org/public/rest/data"


def _num(v):
    """Parse a provider scalar; the Fed ships 'NA' strings for holidays."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ("", "NA", "N/A", "nan", "None", ".", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# DBnomics — mirrors the Fed's H.15 / TIPS and the BEA NIPA tables
# ---------------------------------------------------------------------------

def dbnomics_series(spec: dict, *, max_age_h: float = 3.0):
    prov, ds, code = spec["provider"], spec["dataset"], spec["series_code"]
    url = f"{DBNOMICS}/{prov}/{ds}/{urllib.parse.quote(code, safe='')}?observations=1"
    payload = http.get_json(url, cache_name=f"dbn_{prov}_{ds}_{code}", max_age_h=max_age_h, timeout=90)
    docs = payload.get("series", {}).get("docs", [])
    if not docs:
        raise http.FetchError(f"dbnomics: no series for {prov}/{ds}/{code}")
    doc = docs[0]
    out = [(str(p), _num(v)) for p, v in zip(doc.get("period", []), doc.get("value", []))
           if p is not None]
    return [(p, v) for p, v in out if v is not None]


def dbnomics_panel(provider: str, dataset: str, *, max_age_h: float = 6.0) -> dict[str, list]:
    """Fetch a whole dataset in one call: {series_code: [(period, value)]}."""
    url = f"{DBNOMICS}/{provider}/{dataset}?observations=1&limit=1000"
    payload = http.get_json(url, cache_name=f"dbn_panel_{provider}_{dataset}",
                            max_age_h=max_age_h, timeout=180)
    docs = payload.get("series", {}).get("docs", [])
    panel: dict[str, list] = {}
    for doc in docs:
        code = doc.get("series_code")
        if not code:
            continue
        rows = []
        for p, v in zip(doc.get("period", []), doc.get("value", [])):
            fv = _num(v)
            if p is not None and fv is not None:
                rows.append((str(p), fv))
        if rows:
            panel[code] = rows
    if not panel:
        raise http.FetchError(f"dbnomics: empty panel for {provider}/{dataset}")
    return panel


# ---------------------------------------------------------------------------
# Yahoo — daily equity and volatility indices
# ---------------------------------------------------------------------------

def yahoo_series(spec: dict, *, years: int = 30, max_age_h: float = 2.0):
    import datetime as dt

    sym = spec["series_code"]
    url = (f"{YAHOO}/{urllib.parse.quote(sym, safe='')}?range={years}y&interval=1d")
    payload = http.get_json(url, cache_name=f"yahoo_{sym}", max_age_h=max_age_h, timeout=90)
    result = payload["chart"]["result"][0]
    stamps = result.get("timestamp", [])
    closes = result["indicators"]["quote"][0].get("close", [])
    out = []
    for ts, c in zip(stamps, closes):
        if c is None:
            continue
        day = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d")
        out.append((day, float(c)))
    return out


# ---------------------------------------------------------------------------
# OECD SDMX 2.1 — returns real CSV when asked for the data CSV media type
# ---------------------------------------------------------------------------

OECD_CSV = "application/vnd.sdmx.data+csv;version=1.0.0, text/csv, */*"


def oecd_series(spec: dict, *, start: str = "1950-01", max_age_h: float = 12.0):
    agency, flow = spec["provider"], spec["dataset"]
    version = spec.get("dataset_version", "1.0")
    key = spec["series_code"]
    url = f"{OECD}/{agency},{flow},{version}/{urllib.parse.quote(key, safe='.,')}?startPeriod={start}&format=csv"
    text = http.get_text(url, cache_name=f"oecd_{flow}_{key}".replace("@", "_"),
                         max_age_h=max_age_h, timeout=120,
                         headers={"Accept": OECD_CSV})
    lines = text.splitlines()
    if len(lines) < 2:
        raise http.FetchError(f"oecd: no data for {flow}/{key}")
    header = lines[0].split(",")
    try:
        i_time = header.index("TIME_PERIOD")
        i_val = header.index("OBS_VALUE")
    except ValueError as exc:
        raise http.FetchError(f"oecd: unexpected header {header[:6]}") from exc
    i_freq = header.index("FREQ") if "FREQ" in header else None
    want_freq = (spec.get("frequency") or "").upper()
    out = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= max(i_time, i_val):
            continue
        # a loose key can return several frequencies at once; keep one
        if i_freq is not None and want_freq and parts[i_freq].strip().upper() != want_freq:
            continue
        v = _num(parts[i_val])
        if v is not None:
            out.append((parts[i_time].strip(), v))
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Tracked current-value providers (no history available)
# ---------------------------------------------------------------------------

def atlanta_gdpnow(spec: dict, *, max_age_h: float = 6.0) -> tuple[float, str, dict]:
    """Return (value, as_of_label, raw) for the current GDPNow vintage."""
    url = "https://www.atlantafed.org/-/media/dst/forecast-center/gdpnow/gdpnow.json"
    payload = http.get_json(url, cache_name="gdpnow", max_age_h=max_age_h, timeout=60)
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    if not rows:
        raise http.FetchError("gdpnow: empty payload")
    last = rows[-1] if isinstance(rows, list) else rows
    if isinstance(last, dict):
        for k in ("gdpnow", "value", "nowcast", "GDPNow"):
            if k in last and _num(last[k]) is not None:
                label = str(last.get("date") or last.get("asOf") or "")
                return _num(last[k]), label, last
    raise http.FetchError(f"gdpnow: unrecognised payload {str(last)[:200]}")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def fetch(spec: dict) -> list[tuple[str, float | None]]:
    src = spec["source"]
    if src == "dbnomics":
        return dbnomics_series(spec)
    if src == "yahoo":
        return yahoo_series(spec)
    if src == "oecd":
        return oecd_series(spec)
    raise http.FetchError(f"no adapter for source={src!r} ({spec.get('series_id')})")
