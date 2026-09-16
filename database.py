import os

import psycopg2
from psycopg2.extras import execute_values


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "solar_monitoring"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD") or "admin123",
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
                    CREATE TABLE IF NOT EXISTS dashboard_sources (
                        source_name TEXT NOT NULL,
                        filename TEXT NOT NULL
                    );
                """)
    finally:
        conn.close()


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

    