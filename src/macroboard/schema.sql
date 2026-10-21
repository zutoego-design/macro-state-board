-- ============================================================
-- Macro State Board — schema
--
-- Bottom-up layering. Each layer is derived from the one below and
-- nothing skips a layer:
--
--   L0 raw        provider payload, one row per series/period/vintage
--   L1 derived    single-series transforms (yoy, spread, drawdown, z)
--   L2 composite  weighted aggregates of L1/L0 across series
--   L3 state      regime labels and checklists, computed at read time
--
-- The API exposes L2/L3 by default. L0/L1 stay in the database for
-- drill-down and for rebuilding L2 without touching a provider.
--
-- Every fact is tagged with the vintage at which it was observed, so the
-- board can be replayed as it looked on any past date.
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- Catalog
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS series (
    series_id     TEXT PRIMARY KEY,          -- e.g. us.rates.ust10y
    title         TEXT NOT NULL,
    short_title   TEXT,
    layer         TEXT NOT NULL DEFAULT 'raw' CHECK (layer IN ('raw','derived','composite')),
    group_id      TEXT NOT NULL,             -- rates|curve|real|inflation|growth|labor|market|aggregate
    unit          TEXT,                      -- pct|bp|idx|thousands|z|score|usd
    frequency     TEXT,                      -- D|W|M|Q|A
    coverage      TEXT,                      -- how far back the provider goes
    source        TEXT,                      -- dbnomics|yahoo|oecd|nyfed|derived|composite
    provider      TEXT,
    dataset       TEXT,
    series_code   TEXT,
    source_url    TEXT,
    method_note   TEXT,
    question      TEXT,                      -- which board question it answers
    decimals      INTEGER DEFAULT 2,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS ix_series_layer ON series(layer, group_id);

-- Per-period provenance for composites: which month the aggregate is stamped
-- with, and how old its oldest input actually was. Without this a "2026-10"
-- reading looks like an October observation when it may rest on August data.
CREATE TABLE IF NOT EXISTS composite_meta (
    composite_id    TEXT NOT NULL,
    period          TEXT NOT NULL,
    n_inputs        INTEGER,
    weight_covered  REAL,
    oldest_input    TEXT,
    newest_input    TEXT,
    PRIMARY KEY (composite_id, period)
);

-- Composite definitions: what goes into an aggregate and with what weight.
-- Storing this makes an aggregate auditable instead of magic.
CREATE TABLE IF NOT EXISTS composite_input (
    composite_id  TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    input_id      TEXT NOT NULL,             -- series_id, or 'transform:series_id'
    weight        REAL NOT NULL DEFAULT 1.0,
    sign          REAL NOT NULL DEFAULT 1.0, -- +1 = higher input means higher composite
    transform     TEXT,                      -- level|yoy|chg|z|invert|pct_rank
    note          TEXT,
    PRIMARY KEY (composite_id, input_id)
);

-- ------------------------------------------------------------
-- Vintages
--   kind='snapshot'  we pulled and stored at this moment
--   kind='release'   the provider's own publication timestamp
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vintage (
    vintage_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of         TEXT NOT NULL,             -- ISO timestamp, UTC
    kind          TEXT NOT NULL DEFAULT 'snapshot' CHECK (kind IN ('release','snapshot')),
    source        TEXT,
    note          TEXT,
    n_obs         INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (as_of, kind, source)
);

-- ------------------------------------------------------------
-- Observations — the only unbounded table.
--   D -> YYYY-MM-DD   W -> YYYY-MM-DD (week ending)
--   M -> YYYY-MM      Q -> YYYY-Qn     A -> YYYY
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS observation (
    series_id     TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    period        TEXT NOT NULL,
    vintage_id    INTEGER NOT NULL REFERENCES vintage(vintage_id) ON DELETE CASCADE,
    value         REAL,
    status        TEXT DEFAULT 'final',       -- final|prelim|advance|tracked
    PRIMARY KEY (series_id, period, vintage_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_obs_series_period ON observation(series_id, period);

-- Latest known value per (series, period) across all vintages.
CREATE VIEW IF NOT EXISTS obs_latest AS
SELECT o.series_id, o.period, o.value, o.vintage_id, s.frequency, s.unit, s.group_id, s.layer
FROM observation o
JOIN (
    SELECT series_id, period, MAX(vintage_id) AS vid
    FROM observation GROUP BY series_id, period
) m ON m.series_id = o.series_id AND m.period = o.period AND m.vid = o.vintage_id
JOIN series s ON s.series_id = o.series_id;

-- One series as it stood at a given vintage.
CREATE VIEW IF NOT EXISTS obs_asof AS
SELECT o.series_id, o.period, o.value, o.vintage_id, v.as_of
FROM observation o JOIN vintage v ON v.vintage_id = o.vintage_id;

-- ------------------------------------------------------------
-- Trackers — for series whose provider exposes only a current value
-- (GDPNow, financial-conditions indices, ...). Each run appends one
-- point per series; over time this *creates* the history the provider
-- refuses to publish. This is the point of the table.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tracker (
    series_id     TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    observed_at   TEXT NOT NULL,             -- YYYY-MM-DD, the day we looked
    value         REAL,
    as_of_label   TEXT,                      -- the provider's own "as of" string
    payload       TEXT,                      -- raw JSON, so nothing is lost
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (series_id, observed_at)
);

CREATE TABLE IF NOT EXISTS tracker_state (
    series_id     TEXT PRIMARY KEY REFERENCES series(series_id) ON DELETE CASCADE,
    last_run      TEXT,
    last_status   TEXT,
    last_value    REAL,
    n_points      INTEGER DEFAULT 0,
    error         TEXT
);

-- ------------------------------------------------------------
-- Models and scores. A model without an out-of-sample score does not
-- belong on the board; this is where that promise is enforced.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model (
    model_id      TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    target_id     TEXT,
    horizon       TEXT,
    method        TEXT,
    protocol      TEXT,
    baseline      TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS model_output (
    model_id      TEXT NOT NULL REFERENCES model(model_id) ON DELETE CASCADE,
    as_of         TEXT NOT NULL,
    target_period TEXT,
    value         REAL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (model_id, as_of, target_period)
);

CREATE TABLE IF NOT EXISTS model_score (
    model_id      TEXT NOT NULL REFERENCES model(model_id) ON DELETE CASCADE,
    metric        TEXT NOT NULL,
    window        TEXT NOT NULL,
    n_obs         INTEGER,
    value         REAL,
    benchmark     REAL,
    as_of         TEXT NOT NULL,
    PRIMARY KEY (model_id, metric, window, as_of)
);

-- ------------------------------------------------------------
-- Ops
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS run_log (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    task          TEXT NOT NULL,
    vintage_id    INTEGER,
    n_series      INTEGER,
    n_rows        INTEGER,
    status        TEXT,
    detail        TEXT
);

CREATE TABLE IF NOT EXISTS release (
    series_id     TEXT PRIMARY KEY,
    next_release  TEXT,
    last_release  TEXT,
    updated_at    TEXT
);
