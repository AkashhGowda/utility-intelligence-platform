import os
import json

import psycopg2
import pandas as pd
from psycopg2.extras import Json, execute_values


def _setting(name, default=None):
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default


def get_connection():
    database_url = _setting("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=_setting("DB_HOST", "127.0.0.1"),
        port=_setting("DB_PORT", "5432"),
        database=_setting("DB_NAME", "solar_monitoring"),
        user=_setting("DB_USER", "postgres"),
        password=_setting("DB_PASSWORD", ""),
    )


def read_solar_time_logs():
    """Return the raw solar time-series rows used for anomaly detection."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    t.location_id,
                    l.location_name,
                    t.log_date,
                    t.log_timestamp,
                    t.kwh,
                    t.kvah,
                    t.kw,
                    t.kva,
                    t.current,
                    t.power_factor,
                    t.site_location,
                    t.plant_name,
                    t.line_name
                FROM solar_time_logs t
                LEFT JOIN solar_locations l ON l.location_id = t.location_id
                ORDER BY l.location_name, t.log_date, t.log_timestamp
                """
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    columns = [
        "location_id",
        "location_name",
        "log_date",
        "log_timestamp",
        "kwh",
        "kvah",
        "kw",
        "kva",
        "current",
        "power_factor",
        "site_location",
        "plant_name",
        "line_name",
    ]
    return __import__("pandas").DataFrame(rows, columns=columns)


def create_dashboard_tables():
    """Create normalized tables used by the Command Center snapshot."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dashboard_energy (
                        location TEXT NOT NULL,
                        daily_kwh DOUBLE PRECISION,
                        mtd_kwh DOUBLE PRECISION
                    );
                    CREATE TABLE IF NOT EXISTS dashboard_solar (
                        source TEXT NOT NULL,
                        daily_kwh DOUBLE PRECISION,
                        mtd_kwh DOUBLE PRECISION
                    );
                    CREATE TABLE IF NOT EXISTS dashboard_transformers (
                        transformer TEXT NOT NULL,
                        sensor_id TEXT,
                        daily_kwh DOUBLE PRECISION,
                        loading_percent DOUBLE PRECISION,
                        health_indicator DOUBLE PRECISION,
                        mtd_kwh DOUBLE PRECISION
                    );
                    CREATE TABLE IF NOT EXISTS dashboard_air (
                        utility TEXT NOT NULL,
                        avg_flow_m3_hr DOUBLE PRECISION,
                        total_m3 DOUBLE PRECISION
                    );
                    CREATE TABLE IF NOT EXISTS dashboard_environment (
                        location TEXT NOT NULL,
                        humidity_avg DOUBLE PRECISION,
                        humidity_max DOUBLE PRECISION,
                        temperature_avg DOUBLE PRECISION,
                        temperature_max DOUBLE PRECISION,
                        humidity_target DOUBLE PRECISION,
                        temperature_target DOUBLE PRECISION
                    );
                    CREATE TABLE IF NOT EXISTS dashboard_pf (
                        row_number INTEGER,
                        column_number INTEGER,
                        value DOUBLE PRECISION
                    );
                    CREATE TABLE IF NOT EXISTS dashboard_sources (
                        source_name TEXT NOT NULL,
                        filename TEXT NOT NULL
                    );
                """)
    finally:
        conn.close()


def load_dashboard_tables():
    """Return the live PostgreSQL dashboard tables used by the major panels."""
    create_dashboard_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT location, daily_kwh, mtd_kwh FROM dashboard_energy")
            energy = cursor.fetchall()
            cursor.execute("SELECT source, daily_kwh, mtd_kwh FROM dashboard_solar")
            solar = cursor.fetchall()
            cursor.execute(
                "SELECT transformer, sensor_id, daily_kwh, loading_percent, health_indicator, mtd_kwh FROM dashboard_transformers"
            )
            transformers = cursor.fetchall()
            cursor.execute("SELECT utility, avg_flow_m3_hr, total_m3 FROM dashboard_air")
            air = cursor.fetchall()
            cursor.execute(
                "SELECT location, humidity_avg, humidity_max, temperature_avg, temperature_max, humidity_target, temperature_target FROM dashboard_environment"
            )
            environment = cursor.fetchall()
            cursor.execute("SELECT row_number, column_number, value FROM dashboard_pf")
            pf = cursor.fetchall()
            cursor.execute("SELECT source_name, filename FROM dashboard_sources")
            sources = cursor.fetchall()
    finally:
        conn.close()

    return {
        "energy": __import__("pandas").DataFrame(energy, columns=["location", "daily_kwh", "mtd_kwh"]),
        "solar": __import__("pandas").DataFrame(solar, columns=["source", "daily_kwh", "mtd_kwh"]),
        "transformers": __import__("pandas").DataFrame(
            transformers,
            columns=[
                "transformer", "sensor_id", "daily_kwh", "loading_percent", "health_indicator", "mtd_kwh",
            ],
        ),
        "air": __import__("pandas").DataFrame(air, columns=["utility", "avg_flow_m3_hr", "total_m3"]),
        "environment": __import__("pandas").DataFrame(
            environment,
            columns=[
                "location",
                "humidity_avg",
                "humidity_max",
                "temperature_avg",
                "temperature_max",
                "humidity_target",
                "temperature_target",
            ],
        ),
        "pf": __import__("pandas").DataFrame(pf, columns=["row_number", "column_number", "value"]),
        "sources": sources,
        "data_source": "PostgreSQL dashboard tables",
        "energy_history": __import__("pandas").DataFrame(),
    }


def empty_dashboard_tables():
    """Return the same shape as live dashboard data when PostgreSQL is unavailable."""
    pd = __import__("pandas")
    return {
        "energy": pd.DataFrame(columns=["location", "daily_kwh", "mtd_kwh"]),
        "solar": pd.DataFrame(columns=["source", "daily_kwh", "mtd_kwh"]),
        "transformers": pd.DataFrame(
            columns=[
                "transformer", "sensor_id", "daily_kwh", "loading_percent",
                "health_indicator", "mtd_kwh",
            ]
        ),
        "air": pd.DataFrame(columns=["utility", "avg_flow_m3_hr", "total_m3"]),
        "environment": pd.DataFrame(
            columns=[
                "location", "humidity_avg", "humidity_max", "temperature_avg",
                "temperature_max", "humidity_target", "temperature_target",
            ]
        ),
        "pf": pd.DataFrame(columns=["row_number", "column_number", "value"]),
        "sources": [],
        "data_source": "PostgreSQL dashboard tables",
        "energy_history": pd.DataFrame(),
    }


def create_uploaded_data_table():
    """Create durable storage for user-uploaded datasets used by reports and AI."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dashboard_uploaded_data (
                        upload_id BIGSERIAL PRIMARY KEY,
                        filename TEXT NOT NULL,
                        sheet_name TEXT NOT NULL DEFAULT 'Dataset',
                        row_number INTEGER NOT NULL,
                        row_data JSONB NOT NULL,
                        uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
    finally:
        conn.close()


def save_uploaded_dataset(dataframe, filename, sheet_name="Dataset"):
    """Persist every row of an uploaded dataset in PostgreSQL."""
    if dataframe is None or dataframe.empty:
        return 0
    create_uploaded_data_table()
    rows = []
    for row_number, row in enumerate(dataframe.to_dict(orient="records"), start=1):
        normalized = {
            str(key): (None if pd.isna(value) else value)
            for key, value in row.items()
        }
        rows.append(
            (
                str(filename),
                str(sheet_name),
                row_number,
                Json(normalized, dumps=lambda value: json.dumps(value, default=str)),
            )
        )

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM dashboard_uploaded_data WHERE filename = %s AND sheet_name = %s",
                    (str(filename), str(sheet_name)),
                )
                execute_values(
                    cursor,
                    "INSERT INTO dashboard_uploaded_data (filename, sheet_name, row_number, row_data) VALUES %s",
                    rows,
                )
        return len(rows)
    finally:
        conn.close()


def load_uploaded_datasets():
    """Load all durable user uploads as named DataFrames for AI and reports."""
    create_uploaded_data_table()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT filename, sheet_name, row_data FROM dashboard_uploaded_data ORDER BY uploaded_at, upload_id"
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    datasets = {}
    for filename, sheet_name, row_data in rows:
        key = f"Upload: {filename} [{sheet_name}]"
        datasets.setdefault(key, []).append(row_data)
    return {
        key: pd.DataFrame(records)
        for key, records in datasets.items()
    }


def replace_dashboard_snapshot(data):
    """Persist the parsed upload model used by the Command Center."""
    create_dashboard_tables()
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                for table in (
                    "dashboard_energy",
                    "dashboard_solar",
                    "dashboard_transformers",
                    "dashboard_sources",
                ):
                    cursor.execute(f"TRUNCATE TABLE {table}")

                energy = data.get("energy")
                if energy is not None and not energy.empty:
                    rows = [
                        (
                            str(row.get("location", "")),
                            row.get("daily_kwh"),
                            row.get("mtd_kwh"),
                        )
                        for _, row in energy.iterrows()
                    ]
                    execute_values(
                        cursor,
                        "INSERT INTO dashboard_energy "
                        "(location, daily_kwh, mtd_kwh) VALUES %s",
                        rows,
                    )

                solar = data.get("solar")
                if solar is not None and not solar.empty:
                    rows = [
                        (
                            str(row.get("source", "")),
                            row.get("daily_kwh"),
                            row.get("mtd_kwh"),
                        )
                        for _, row in solar.iterrows()
                    ]
                    execute_values(
                        cursor,
                        "INSERT INTO dashboard_solar "
                        "(source, daily_kwh, mtd_kwh) VALUES %s",
                        rows,
                    )

                transformers = data.get("transformers")
                if transformers is not None and not transformers.empty:
                    rows = [
                        (
                            str(row.get("transformer", "")),
                            None if row.get("sensor_id") is None else str(row.get("sensor_id")),
                            row.get("daily_kwh"),
                            row.get("loading_percent"),
                            row.get("health_indicator"),
                            row.get("mtd_kwh"),
                        )
                        for _, row in transformers.iterrows()
                    ]
                    execute_values(
                        cursor,
                        "INSERT INTO dashboard_transformers "
                        "(transformer, sensor_id, daily_kwh, loading_percent, "
                        "health_indicator, mtd_kwh) VALUES %s",
                        rows,
                    )

                sources = data.get("sources", [])
                if sources:
                    execute_values(
                        cursor,
                        "INSERT INTO dashboard_sources "
                        "(source_name, filename) VALUES %s",
                        [(str(name), str(filename)) for name, filename in sources],
                    )
    finally:
        conn.close()


def load_dashboard_snapshot():
    """Load the latest normalized Command Center snapshot from PostgreSQL."""
    create_dashboard_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT location, daily_kwh, mtd_kwh FROM dashboard_energy"
            )
            energy = cursor.fetchall()
            cursor.execute(
                "SELECT source, daily_kwh, mtd_kwh FROM dashboard_solar"
            )
            solar = cursor.fetchall()
            cursor.execute(
                "SELECT transformer, sensor_id, daily_kwh, loading_percent, "
                "health_indicator, mtd_kwh FROM dashboard_transformers"
            )
            transformers = cursor.fetchall()
            cursor.execute(
                "SELECT source_name, filename FROM dashboard_sources"
            )
            sources = cursor.fetchall()
    finally:
        conn.close()

    return {
        "energy": __import__("pandas").DataFrame(
            energy, columns=["location", "daily_kwh", "mtd_kwh"]
        ),
        "solar": __import__("pandas").DataFrame(
            solar, columns=["source", "daily_kwh", "mtd_kwh"]
        ),
        "transformers": __import__("pandas").DataFrame(
            transformers,
            columns=[
                "transformer", "sensor_id", "daily_kwh", "loading_percent",
                "health_indicator", "mtd_kwh",
            ],
        ),
        "sources": sources,
        "air": __import__("pandas").DataFrame(),
        "environment": __import__("pandas").DataFrame(),
        "pf": __import__("pandas").DataFrame(),
        "energy_history": __import__("pandas").DataFrame(),
    }


def get_dashboard_source_summary():
    """Return read-only counts and source metadata for persisted dashboard data."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            counts = {}
            for table in (
                "dashboard_energy",
                "dashboard_solar",
                "dashboard_transformers",
                "dashboard_sources",
            ):
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT source_name, filename FROM dashboard_sources ORDER BY filename"
            )
            sources = cursor.fetchall()
        return {"counts": counts, "sources": sources, "database": "solar_monitoring"}
    finally:
        conn.close()


def create_admin_config_table():
    """
    Create the admin_config table if it does not already exist.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_config (
            id SERIAL PRIMARY KEY,
            config_key VARCHAR(100) UNIQUE NOT NULL,
            config_value TEXT,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()

    cursor.close()
    conn.close()


def set_config(config_key, config_value, description=""):
    """
    Insert or update an admin configuration value.
    """

    create_admin_config_table()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO admin_config
            (config_key, config_value, description)
        VALUES (%s, %s, %s)
        ON CONFLICT (config_key)
        DO UPDATE SET
            config_value = EXCLUDED.config_value,
            description = EXCLUDED.description,
            updated_at = CURRENT_TIMESTAMP;
    """, (
        config_key,
        str(config_value),
        description
    ))

    conn.commit()

    cursor.close()
    conn.close()


def get_config(config_key, default=None):
    """
    Get one configuration value.
    """

    create_admin_config_table()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT config_value
        FROM admin_config
        WHERE config_key = %s;
    """, (config_key,))

    result = cursor.fetchone()

    cursor.close()
    conn.close()

    if result is None:
        return default

    return result[0]


def get_all_config():
    """
    Get all admin configuration settings.
    """

    create_admin_config_table()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            config_key,
            config_value,
            description,
            updated_at
        FROM admin_config
        ORDER BY config_key;
    """)

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows

def create_question_history_table():
    """
    Create the AI question history table.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS question_history (
            id SERIAL PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            data_signature TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()

    cursor.close()
    conn.close()


def save_question_history(question, answer, data_signature=""):
    """
    Save an AI question and its answer.
    """

    create_question_history_table()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO question_history
            (question, answer, data_signature)
        VALUES (%s, %s, %s);
    """, (
        question,
        answer,
        data_signature
    ))

    conn.commit()

    cursor.close()
    conn.close()


def get_question_history(limit=20):
    """
    Get recent AI question history.
    """

    create_question_history_table()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            question,
            answer,
            data_signature,
            created_at
        FROM question_history
        ORDER BY created_at DESC
        LIMIT %s;
    """, (limit,))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows

def clear_question_history():
    """
    Delete all saved AI question history.
    """

    create_question_history_table()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM question_history;
    """)

    conn.commit()

    cursor.close()
    conn.close()

def get_previous_answer(question, data_signature=""):
    """
    Return the previous answer for the same question
    and the same data version.
    """

    create_question_history_table()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT answer
        FROM question_history
        WHERE LOWER(TRIM(question)) = LOWER(TRIM(%s))
        AND data_signature = %s
        ORDER BY created_at DESC
        LIMIT 1;
    """, (
        question,
        data_signature
    ))

    result = cursor.fetchone()

    cursor.close()
    conn.close()

    if result is None:
        return None

    return result[0]
if __name__ == "__main__":

    try:

        conn = get_connection()

        print("DATABASE CONNECTION SUCCESSFUL")

        conn.close()

        create_admin_config_table()
        create_question_history_table()

        print("ADMIN CONFIG TABLE READY")
        print("QUESTION HISTORY TABLE READY")

    except Exception as e:

        print("DATABASE ERROR")
        print(e)

    