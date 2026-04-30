-- init_app_metrics.sql
-- Creates app_metrics table and seeds an initial value.

CREATE TABLE IF NOT EXISTS app_metrics (
  metric_key   TEXT PRIMARY KEY,
  metric_value DOUBLE PRECISION NOT NULL,
  unit         TEXT NOT NULL,
  status       TEXT NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL,
  source       TEXT NOT NULL
);

INSERT INTO app_metrics(metric_key, metric_value, unit, status, updated_at, source)
VALUES ('flex_power', 1000, 'kW', 'OK', NOW(), 'init')
ON CONFLICT (metric_key) DO NOTHING;
