"""SQLite schema and upsert helpers for Phase 4 engine tables.

Four new tables: regime_states, distribution_events, signals, flow_map.
Call init_engine_schema(conn) once at startup.
"""
import sqlite3


def init_engine_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS regime_states (
            ticker          TEXT NOT NULL,
            trading_day     TEXT NOT NULL,
            regime          TEXT NOT NULL,
            rs_value        REAL,
            price_vs_21ma   REAL,
            price_vs_50ma   REAL,
            atr_ratio       REAL,
            is_distribution INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (ticker, trading_day)
        );

        CREATE TABLE IF NOT EXISTS distribution_events (
            ticker                 TEXT NOT NULL,
            trading_day            TEXT NOT NULL,
            volume_ratio           REAL,
            vwap_rejection_streak  INTEGER,
            is_flagged             INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (ticker, trading_day)
        );

        CREATE TABLE IF NOT EXISTS signals (
            ticker_a                TEXT NOT NULL,
            ticker_b                TEXT NOT NULL,
            signal_date             TEXT NOT NULL,
            optimal_lag             INTEGER,
            window_length           INTEGER,
            correlation_strength    REAL,
            stability_score         REAL,
            regime_state            TEXT,
            adjustment_policy_id    TEXT NOT NULL DEFAULT 'policy_a',
            direction               TEXT,
            expected_target         REAL,
            invalidation_threshold  REAL,
            sizing_tier             TEXT,
            flow_map_entry          TEXT,
            data_warning            TEXT,
            generated_at            TEXT NOT NULL,
            PRIMARY KEY (ticker_a, ticker_b, signal_date)
        );

        CREATE INDEX IF NOT EXISTS idx_signals_date
            ON signals(signal_date);
        CREATE INDEX IF NOT EXISTS idx_signals_ticker_a
            ON signals(ticker_a);

        CREATE TABLE IF NOT EXISTS flow_map (
            ticker_a     TEXT NOT NULL,
            ticker_b     TEXT NOT NULL,
            direction    TEXT,
            optimal_lag  INTEGER,
            last_updated TEXT,
            PRIMARY KEY (ticker_a, ticker_b)
        );
    """)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signal_transitions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker_a        TEXT NOT NULL,
            ticker_b        TEXT NOT NULL,
            signal_date     TEXT NOT NULL,
            from_action     TEXT,
            to_action       TEXT NOT NULL,
            transitioned_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_transitions_pair
            ON signal_transitions(ticker_a, ticker_b);
        CREATE INDEX IF NOT EXISTS idx_transitions_signal
            ON signal_transitions(ticker_a, ticker_b, signal_date);
    """)
    conn.commit()
    # Migration: add data_warning column if this DB was created before this version
    try:
        conn.execute("ALTER TABLE signals ADD COLUMN data_warning TEXT")
        conn.commit()
    except Exception:
        pass  # Column already exists
    # Migration: add outperformance signal enhancement columns (v1.1)
    try:
        conn.execute("ALTER TABLE signals ADD COLUMN action TEXT")
        conn.execute("ALTER TABLE signals ADD COLUMN response_window REAL")
        conn.execute("ALTER TABLE signals ADD COLUMN rs_acceleration REAL")
        conn.execute("ALTER TABLE signals ADD COLUMN leader_rs_deceleration REAL")
        conn.execute("ALTER TABLE signals ADD COLUMN outperformance_margin REAL")
        conn.commit()
    except Exception:
        pass  # Columns already exist


def upsert_signal(conn: sqlite3.Connection, signal: dict) -> None:
    """Immutable upsert: generated_at is NEVER overwritten on conflict.

    ON CONFLICT updates all fields EXCEPT generated_at so the original
    creation timestamp is preserved as the audit anchor.
    """
    sql = """
        INSERT INTO signals (
            ticker_a, ticker_b, signal_date,
            optimal_lag, window_length,
            correlation_strength, stability_score,
            regime_state, adjustment_policy_id,
            direction, expected_target, invalidation_threshold,
            sizing_tier, flow_map_entry, data_warning, generated_at,
            action, response_window, rs_acceleration,
            leader_rs_deceleration, outperformance_margin
        ) VALUES (
            :ticker_a, :ticker_b, :signal_date,
            :optimal_lag, :window_length,
            :correlation_strength, :stability_score,
            :regime_state, :adjustment_policy_id,
            :direction, :expected_target, :invalidation_threshold,
            :sizing_tier, :flow_map_entry, :data_warning, :generated_at,
            :action, :response_window, :rs_acceleration,
            :leader_rs_deceleration, :outperformance_margin
        )
        ON CONFLICT(ticker_a, ticker_b, signal_date) DO UPDATE SET
            optimal_lag            = excluded.optimal_lag,
            window_length          = excluded.window_length,
            correlation_strength   = excluded.correlation_strength,
            stability_score        = excluded.stability_score,
            regime_state           = excluded.regime_state,
            direction              = excluded.direction,
            expected_target        = excluded.expected_target,
            invalidation_threshold = excluded.invalidation_threshold,
            sizing_tier            = excluded.sizing_tier,
            flow_map_entry         = excluded.flow_map_entry,
            data_warning           = excluded.data_warning,
            action                 = excluded.action,
            response_window        = excluded.response_window,
            rs_acceleration        = excluded.rs_acceleration,
            leader_rs_deceleration = excluded.leader_rs_deceleration,
            outperformance_margin  = excluded.outperformance_margin
            -- generated_at intentionally EXCLUDED from SET: immutability anchor
    """
    conn.execute(sql, signal)
    conn.commit()


def upsert_flow_map(conn: sqlite3.Connection, entry: dict) -> None:
    """Upsert a directed flow map entry.

    entry keys: ticker_a, ticker_b, direction, optimal_lag, last_updated
    """
    sql = """
        INSERT INTO flow_map (ticker_a, ticker_b, direction, optimal_lag, last_updated)
        VALUES (:ticker_a, :ticker_b, :direction, :optimal_lag, :last_updated)
        ON CONFLICT(ticker_a, ticker_b) DO UPDATE SET
            direction    = excluded.direction,
            optimal_lag  = excluded.optimal_lag,
            last_updated = excluded.last_updated
    """
    conn.execute(sql, entry)
    conn.commit()
