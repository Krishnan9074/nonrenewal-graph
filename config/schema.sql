CREATE TABLE IF NOT EXISTS entities (
  entity_id      TEXT PRIMARY KEY,
  type           TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  attrs          JSON
);
CREATE TABLE IF NOT EXISTS documents (
  doc_id       TEXT PRIMARY KEY,
  source       TEXT NOT NULL,
  url          TEXT,
  published_at DATE,
  text         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
  edge_id     TEXT PRIMARY KEY,
  src         TEXT NOT NULL,
  rel         TEXT NOT NULL,
  dst         TEXT NOT NULL,
  valid_from  DATE,
  valid_to    DATE,
  props       JSON,
  doc_id      TEXT,
  span        TEXT,
  extractor   TEXT NOT NULL,
  confidence  DOUBLE NOT NULL,
  ingested_at TIMESTAMP DEFAULT current_timestamp
);
