-- PostgreSQL version of the SQLite schema in ie/store.py, for production deployments.
CREATE TABLE IF NOT EXISTS documents (
  id              BIGSERIAL PRIMARY KEY,
  org_id          TEXT NOT NULL,
  file_name       TEXT NOT NULL,
  sha256          TEXT NOT NULL,
  storage_key     TEXT,                       -- original file in object storage (S3), never in the DB
  method          TEXT NOT NULL,              -- text-layer | ocr
  ocr_confidence  REAL,
  data            JSONB NOT NULL,             -- extracted (or corrected) invoice
  issues          JSONB NOT NULL DEFAULT '[]',
  confidence      REAL NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('auto_approved','needs_review','approved','rejected')),
  vendor_key      TEXT,
  number_key      TEXT,
  model           TEXT,
  input_tokens    INT,
  output_tokens   INT,
  cost_usd        NUMERIC(10,6),
  latency_ms      INT,
  reviewed_by     TEXT,
  reviewed_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, sha256)
);
CREATE INDEX IF NOT EXISTS documents_queue_idx ON documents (org_id, status, confidence);
CREATE INDEX IF NOT EXISTS documents_dupe_idx  ON documents (org_id, vendor_key, number_key);

-- Every human correction is kept: it becomes training/eval data and an audit trail.
CREATE TABLE IF NOT EXISTS corrections (
  id           BIGSERIAL PRIMARY KEY,
  document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  field        TEXT NOT NULL,
  old_value    TEXT,
  new_value    TEXT,
  corrected_by TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
