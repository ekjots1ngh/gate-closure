-- A sketch for the Tiger Data (TimescaleDB) side track. The Python pipeline does not use it,
-- and it has not been run against a database. It mirrors the pandas store: prices keyed on UTC
-- start_time, forecast vintages partitioned on publish_time so superseded versions are kept,
-- and the as-of join in gclose/features.py written in SQL (without the demand revision).

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS prices (
    start_time        timestamptz NOT NULL,
    settlement_date   date        NOT NULL,
    settlement_period smallint    NOT NULL,
    created_at        timestamptz NOT NULL,
    ssp               double precision,
    sbp               double precision,
    niv               double precision,
    PRIMARY KEY (start_time)
);
SELECT create_hypertable('prices', 'start_time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS forecasts (
    dataset       text        NOT NULL,   -- WINDFOR, NDF, IMBALNGC
    publish_time  timestamptz NOT NULL,
    start_time    timestamptz NOT NULL,
    boundary      text        NOT NULL DEFAULT 'N',
    value         double precision,
    PRIMARY KEY (dataset, boundary, start_time, publish_time)
);
SELECT create_hypertable('forecasts', 'publish_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS forecasts_asof ON forecasts (dataset, boundary, start_time, publish_time DESC);

-- Live ledger: one row per decision; inserted_at is the server clock, never the client's.
CREATE TABLE IF NOT EXISTS ledger (
    inserted_at   timestamptz NOT NULL DEFAULT now(),
    decided_at    timestamptz NOT NULL,   -- must be before target_start - 60 min
    target_start  timestamptz NOT NULL,
    p_short       double precision,
    action        smallint,               -- +1 discharge, -1 charge, 0 hold
    soc_mwh       double precision,
    model_hash    text
);
SELECT create_hypertable('ledger', 'inserted_at', if_not_exists => TRUE);

-- The as-of join: for each target period, the newest vintage of each dataset published
-- strictly before gate closure (start_time - 60 min).
-- Usage: SELECT * FROM asof_features('2026-10-20 00:00+00', '2026-10-21 00:00+00');
CREATE OR REPLACE FUNCTION asof_features(t0 timestamptz, t1 timestamptz)
RETURNS TABLE (
    start_time   timestamptz,
    gate         timestamptz,
    wind_latest  double precision,
    wind_pub     timestamptz,
    wind_prev    double precision,
    demand_latest double precision,
    imbal_latest double precision
) LANGUAGE sql STABLE AS $$
    WITH periods AS (
        SELECT p.start_time, p.start_time - interval '60 minutes' AS gate
        FROM prices p WHERE p.start_time >= t0 AND p.start_time < t1
    )
    SELECT
        pr.start_time, pr.gate,
        w.value, w.publish_time,
        wp.value,
        d.value,
        i.value
    FROM periods pr
    LEFT JOIN LATERAL (
        SELECT value, publish_time FROM forecasts f
        WHERE f.dataset = 'WINDFOR' AND f.start_time = date_trunc('hour', pr.start_time)
          AND f.publish_time < pr.gate
        ORDER BY f.publish_time DESC LIMIT 1
    ) w ON TRUE
    LEFT JOIN LATERAL (
        SELECT value FROM forecasts f
        WHERE f.dataset = 'WINDFOR' AND f.start_time = date_trunc('hour', pr.start_time)
          AND f.publish_time < w.publish_time
        ORDER BY f.publish_time DESC LIMIT 1
    ) wp ON TRUE
    LEFT JOIN LATERAL (
        SELECT value FROM forecasts f
        WHERE f.dataset = 'NDF' AND f.boundary = 'N' AND f.start_time = pr.start_time
          AND f.publish_time < pr.gate
        ORDER BY f.publish_time DESC LIMIT 1
    ) d ON TRUE
    LEFT JOIN LATERAL (
        SELECT value FROM forecasts f
        WHERE f.dataset = 'IMBALNGC' AND f.boundary = 'N' AND f.start_time = pr.start_time
          AND f.publish_time < pr.gate
        ORDER BY f.publish_time DESC LIMIT 1
    ) i ON TRUE
    ORDER BY pr.start_time;
$$;
