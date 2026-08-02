-- Allow research sources to record that competition evidence is unavailable.
-- TrendRecordStore applies the equivalent rebuild for existing SQLite files.
DROP INDEX IF EXISTS idx_research_velocity;
DROP INDEX IF EXISTS idx_research_confidence;
DROP INDEX IF EXISTS idx_research_freshness_ts;
DROP INDEX IF EXISTS idx_research_rank;

ALTER TABLE research_records RENAME TO research_records_legacy;

CREATE TABLE research_records (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    intent TEXT NOT NULL,
    velocity REAL NOT NULL,
    competition REAL,
    source TEXT NOT NULL,
    freshness_ts TEXT NOT NULL,
    confidence REAL NOT NULL,
    raw TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE
);

INSERT INTO research_records
(id, topic, intent, velocity, competition, source, freshness_ts,
 confidence, raw, created_at, updated_at, dedupe_key)
SELECT id, topic, intent, velocity, competition, source, freshness_ts,
       confidence, raw, created_at, updated_at, dedupe_key
FROM research_records_legacy;

DROP TABLE research_records_legacy;

CREATE INDEX idx_research_velocity ON research_records (velocity DESC);
CREATE INDEX idx_research_confidence ON research_records (confidence DESC);
CREATE INDEX idx_research_freshness_ts ON research_records (freshness_ts DESC);
CREATE INDEX idx_research_rank ON research_records (velocity DESC, confidence DESC, freshness_ts DESC, id ASC);
