"""Storage layer.

Two rules shape this module:

1. **Vintage-correct reads.** `snapshot(conn, vintage_id)` returns every
   series exactly as it was known at that vintage — each series falls back
   to its most recent earlier vintage if the requested one does not carry
   it. Nothing reads "the latest value of period X across any vintage",
   because that silently mixes vintages and breaks replay.

2. **Writes are append-only.** A run opens one vintage and writes into it.
   Earlier vintages are never touched.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from . import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------

def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# period normalisation
# ---------------------------------------------------------------------------

def normalize_period(period: str, frequency: str) -> str:
    s = str(period).strip()
    f = (frequency or "M").upper()
    if f in ("D", "W"):
        return s[:10]
    if f == "M":
        return s[:7]
    if f == "Q":
        if "-Q" in s.upper():
            return s.upper()
        if len(s) >= 7 and s[5:7].isdigit():
            y, m = int(s[:4]), int(s[5:7])
            return f"{y}-Q{(m - 1) // 3 + 1}"
        return s
    if f == "A":
        return s[:4]
    return s


def period_sort_key(period: str):
    p = str(period)
    if "-Q" in p.upper():
        y, q = p.upper().split("-Q")
        return (int(y), int(q) * 3, 0)
    parts = p.replace("-", ":").split(":")
    vals = [int(x) for x in parts if x.isdigit()]
    return tuple(vals + [0] * (3 - len(vals)))


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------

SERIES_COLS = (
    "series_id title short_title layer group_id unit frequency coverage source "
    "provider dataset series_code source_url method_note question decimals is_active"
).split()

_DEFAULTS = {"layer": "raw", "is_active": 1, "decimals": 2}


def upsert_series(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    sql = (
        f"INSERT INTO series ({', '.join(SERIES_COLS)}) "
        f"VALUES ({', '.join('?' * len(SERIES_COLS))}) "
        "ON CONFLICT(series_id) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in SERIES_COLS if c != "series_id")
    )
    n = 0
    for r in rows:
        vals = []
        for c in SERIES_COLS:
            v = r.get(c, _DEFAULTS.get(c))
            vals.append(_DEFAULTS.get(c) if v is None else v)
        if not vals[0]:
            raise ValueError(f"series row without series_id: {r!r}")
        conn.execute(sql, vals)
        n += 1
    conn.commit()
    return n


def upsert_composite_inputs(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    sql = (
        "INSERT INTO composite_input (composite_id, input_id, weight, sign, transform, note) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(composite_id, input_id) DO UPDATE SET "
        "weight=excluded.weight, sign=excluded.sign, transform=excluded.transform, note=excluded.note"
    )
    n = 0
    for r in rows:
        conn.execute(sql, (r["composite_id"], r["input_id"], r.get("weight", 1.0),
                           r.get("sign", 1.0), r.get("transform"), r.get("note")))
        n += 1
    conn.commit()
    return n


# ---------------------------------------------------------------------------
# vintages
# ---------------------------------------------------------------------------

def open_vintage(conn, as_of: str | None = None, kind: str = "snapshot",
                 source: str | None = None, note: str | None = None) -> int:
    as_of = as_of or utc_now()
    row = conn.execute(
        "SELECT vintage_id FROM vintage WHERE as_of=? AND kind=? AND IFNULL(source,'')=IFNULL(?,'')",
        (as_of, kind, source),
    ).fetchone()
    if row:
        return int(row["vintage_id"])
    cur = conn.execute(
        "INSERT INTO vintage (as_of, kind, source, note) VALUES (?,?,?,?)",
        (as_of, kind, source, note),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_vintage(conn, kind: str = "snapshot") -> int | None:
    row = conn.execute(
        "SELECT vintage_id FROM vintage WHERE kind=? ORDER BY vintage_id DESC LIMIT 1", (kind,)
    ).fetchone()
    return int(row["vintage_id"]) if row else None


def vintage_meta(conn, vintage_id: int | None = None) -> dict:
    if vintage_id is None:
        vintage_id = latest_vintage(conn) or 0
    row = conn.execute("SELECT * FROM vintage WHERE vintage_id=?", (vintage_id,)).fetchone()
    n_vint = conn.execute("SELECT COUNT(*) FROM vintage WHERE kind='snapshot'").fetchone()[0]
    return dict(row) if row else {"vintage_id": vintage_id, "as_of": None, "n_obs": 0,
                                  "n_vintages": n_vint}


def write_observations(conn, series_id: str, observations: Sequence[tuple[str, float | None]],
                       vintage_id: int, *, replace: bool = True, status: str = "final") -> int:
    if replace:
        conn.execute("DELETE FROM observation WHERE series_id=? AND vintage_id=?",
                     (series_id, vintage_id))
    rows = [(series_id, p, vintage_id, v, status) for p, v in observations]
    conn.executemany(
        "INSERT INTO observation (series_id, period, vintage_id, value, status) VALUES (?,?,?,?,?) "
        "ON CONFLICT(series_id, period, vintage_id) DO UPDATE SET value=excluded.value, status=excluded.status",
        rows,
    )
    conn.commit()
    return len(rows)


def bump_vintage_count(conn, vintage_id: int) -> int:
    n = conn.execute("SELECT COUNT(*) FROM observation WHERE vintage_id=?", (vintage_id,)).fetchone()[0]
    conn.execute("UPDATE vintage SET n_obs=? WHERE vintage_id=?", (n, vintage_id))
    conn.commit()
    return int(n)


# ---------------------------------------------------------------------------
# reads — vintage-correct
# ---------------------------------------------------------------------------

def snapshot(conn, vintage_id: int | None = None) -> dict[str, list[tuple[str, float]]]:
    """Every series as known at `vintage_id` (default: the latest snapshot).

    Per series, the newest vintage <= vintage_id that actually carries rows
    wins. That is what "as of" means, and it keeps partial ingest runs sane.
    """
    if vintage_id is None:
        vintage_id = latest_vintage(conn) or 0
    rows = conn.execute(
        """
        SELECT o.series_id, o.period, o.value
        FROM observation o
        JOIN (
            SELECT o2.series_id, MAX(o2.vintage_id) AS vid
            FROM observation o2
            WHERE o2.vintage_id <= ?
            GROUP BY o2.series_id
        ) pick ON pick.series_id = o.series_id AND pick.vid = o.vintage_id
        WHERE o.value IS NOT NULL
        ORDER BY o.series_id, o.period
        """,
        (vintage_id,),
    ).fetchall()
    out: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        out.setdefault(r["series_id"], []).append((r["period"], r["value"]))
    return out


def series(conn, series_id: str, vintage_id: int | None = None) -> list[tuple[str, float]]:
    return snapshot(conn, vintage_id).get(series_id, [])


def catalog(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM series WHERE is_active=1 ORDER BY layer DESC, group_id, series_id"
    ).fetchall()]


def composite_inputs(conn, composite_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM composite_input WHERE composite_id=? ORDER BY weight DESC",
        (composite_id,),
    ).fetchall()]


def tracker_history(conn, series_id: str) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT observed_at, value FROM tracker WHERE series_id=? AND value IS NOT NULL ORDER BY observed_at",
        (series_id,),
    ).fetchall()
    return [(r["observed_at"], r["value"]) for r in rows]


def tracker_append(conn, series_id: str, observed_at: str, value: float | None,
                   as_of_label: str | None = None, payload: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO tracker (series_id, observed_at, value, as_of_label, payload) VALUES (?,?,?,?,?) "
        "ON CONFLICT(series_id, observed_at) DO UPDATE SET value=excluded.value, "
        "as_of_label=excluded.as_of_label, payload=excluded.payload",
        (series_id, observed_at, value, as_of_label,
         json.dumps(payload, ensure_ascii=False) if payload is not None else None),
    )
    n = conn.execute("SELECT COUNT(*) FROM tracker WHERE series_id=?", (series_id,)).fetchone()[0]
    conn.execute(
        "INSERT INTO tracker_state (series_id, last_run, last_status, last_value, n_points) "
        "VALUES (?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET last_run=excluded.last_run, "
        "last_status=excluded.last_status, last_value=excluded.last_value, n_points=excluded.n_points",
        (series_id, utc_now(), "ok", value, n),
    )
    conn.commit()


def tracker_error(conn, series_id: str, err: str) -> None:
    conn.execute(
        "INSERT INTO tracker_state (series_id, last_run, last_status, error) VALUES (?,?,?,?) "
        "ON CONFLICT(series_id) DO UPDATE SET last_run=excluded.last_run, "
        "last_status=excluded.last_status, error=excluded.error",
        (series_id, utc_now(), "error", err[:500]),
    )
    conn.commit()


def tracker_states(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM tracker_state ORDER BY series_id").fetchall()]


# ---------------------------------------------------------------------------
# ops
# ---------------------------------------------------------------------------

def start_run(conn, task: str) -> int:
    cur = conn.execute("INSERT INTO run_log (started_at, task, status) VALUES (?,?, 'running')",
                       (utc_now(), task))
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn, run_id: int, *, status: str, vintage_id: int | None = None,
               n_series: int | None = None, n_rows: int | None = None,
               detail: str | None = None) -> None:
    conn.execute(
        "UPDATE run_log SET finished_at=?, status=?, vintage_id=?, n_series=?, n_rows=?, detail=? "
        "WHERE run_id=?",
        (utc_now(), status, vintage_id, n_series, n_rows, detail, run_id),
    )
    conn.commit()


def recent_runs(conn, limit: int = 20) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM run_log ORDER BY run_id DESC LIMIT ?", (limit,)
    ).fetchall()]
