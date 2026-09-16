import io
import os
import pandas as pd
import psycopg2
import streamlit as st

from database import replace_dashboard_snapshot

# ==========================================
# CONFIGURATION
# ==========================================

# Update these variables or set them via environment variables
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "solar_monitoring")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "admin123")
DB_PORT = os.getenv("DB_PORT", "5432")

EXCEL_FILE = "solar_daily_data.xlsx"

# EXCEL SHEET -> LOCATION
SOLAR_LOCATIONS = {
    "60KW Solar ( Above ATS)": {
        "location_id": 1,
        "location_name": "60KW Solar (Above ATS)"
    },
    "20KW Solar (Above Canteen )": {
        "location_id": 2,
        "location_name": "20KW Solar (Above Canteen)"
    },
    "110KW Solar (Above LT Room)": {
        "location_id": 3,
        "location_name": "110KW Solar (Above LT Room)"
    },
    "230Kw Solar kit( chiller area 3": {
        "location_id": 4,
        "location_name": "230KW Solar Kit (Chiller Area 3 to 6)"
    },
    "40 kW Solar (PECVD Pump Room)": {
        "location_id": 5,
        "location_name": "40KW Solar (PECVD Pump Room)"
    },
    "180kw Solar (hexa AHU area)": {
        "location_id": 6,
        "location_name": "180KW Solar (Hexa AHU Area)"
    },
    "Solar Near STP": {
        "location_id": 7,
        "location_name": "Solar Near STP"
    },
    "Solar Near Gate-1 Pathway Stair": {
        "location_id": 8,
        "location_name": "Solar Near Gate-1 Pathway Staircase"
    },
    "Solar Near Parking Area": {
        "location_id": 9,
        "location_name": "Solar Near Parking Area"
    }
}

# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT
    )
    return conn

# ==========================================
# CREATE TABLES
# ==========================================

def ensure_column(conn, table_name, column_name, column_sql):
    """Add a column to a table if it is missing."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
            """,
            (table_name, column_name),
        )
        if cursor.fetchone() is None:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
    conn.commit()


def create_tables(conn):
    cursor = conn.cursor()

    # Locations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solar_locations (
            location_id INTEGER PRIMARY KEY,
            location_name TEXT NOT NULL,
            site_location TEXT DEFAULT 'Bangalore',
            plant_name TEXT DEFAULT 'TPREL-Bangalore',
            line_name TEXT DEFAULT 'Vega',
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'system',
            modified_by TEXT DEFAULT 'system'
        )
    """)

    # Daily summary
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solar_daily_summary (
            summary_id SERIAL PRIMARY KEY,
            location_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            generation_kwh REAL NOT NULL,
            site_location TEXT DEFAULT 'Bangalore',
            plant_name TEXT DEFAULT 'TPREL-Bangalore',
            line_name TEXT DEFAULT 'Vega',

            UNIQUE(location_id, log_date),

            FOREIGN KEY(location_id)
                REFERENCES solar_locations(location_id)
        )
    """)

    # Time logs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solar_time_logs (
            log_id SERIAL PRIMARY KEY,
            location_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            log_timestamp TEXT NOT NULL,
            kwh REAL,
            kvah REAL,
            kw REAL,
            kva REAL,
            current REAL,
            power_factor REAL,
            site_location TEXT DEFAULT 'Bangalore',
            plant_name TEXT DEFAULT 'TPREL-Bangalore',
            line_name TEXT DEFAULT 'Vega',

            UNIQUE(
                location_id,
                log_date,
                log_timestamp
            ),

            FOREIGN KEY(location_id)
                REFERENCES solar_locations(location_id)
        )
    """)

    ensure_column(conn, "solar_locations", "site_location", "site_location TEXT DEFAULT 'Bangalore'")
    ensure_column(conn, "solar_locations", "plant_name", "plant_name TEXT DEFAULT 'TPREL-Bangalore'")
    ensure_column(conn, "solar_locations", "line_name", "line_name TEXT DEFAULT 'Vega'")
    ensure_column(conn, "solar_daily_summary", "site_location", "site_location TEXT DEFAULT 'Bangalore'")
    ensure_column(conn, "solar_daily_summary", "plant_name", "plant_name TEXT DEFAULT 'TPREL-Bangalore'")
    ensure_column(conn, "solar_daily_summary", "line_name", "line_name TEXT DEFAULT 'Vega'")
    ensure_column(conn, "solar_time_logs", "site_location", "site_location TEXT DEFAULT 'Bangalore'")
    ensure_column(conn, "solar_time_logs", "plant_name", "plant_name TEXT DEFAULT 'TPREL-Bangalore'")
    ensure_column(conn, "solar_time_logs", "line_name", "line_name TEXT DEFAULT 'Vega'")
    ensure_column(conn, "solar_time_logs", "kvah", "kvah REAL")
    ensure_column(conn, "solar_time_logs", "kw", "kw REAL")
    ensure_column(conn, "solar_time_logs", "kva", "kva REAL")
    ensure_column(conn, "solar_time_logs", "current", "current REAL")
    ensure_column(conn, "solar_time_logs", "power_factor", "power_factor REAL")

    conn.commit()
    cursor.close()

# ==========================================
# INSERT LOCATIONS
# ==========================================

def insert_locations(conn, selected_location="Bangalore", selected_plant="TPREL-Bangalore", selected_line="Vega"):
    cursor = conn.cursor()

    for sheet_name, location in SOLAR_LOCATIONS.items():
        cursor.execute("""
            INSERT INTO solar_locations
            (
                location_id,
                location_name,
                site_location,
                plant_name,
                line_name
            )
            VALUES (%s, %s, %s, %s, %s)

            ON CONFLICT (location_id)
            DO UPDATE SET
                location_name = EXCLUDED.location_name,
                site_location = EXCLUDED.site_location,
                plant_name = EXCLUDED.plant_name,
                line_name = EXCLUDED.line_name,
                modified_date = CURRENT_TIMESTAMP
        """, (
            location["location_id"],
            location["location_name"],
            selected_location,
            selected_plant,
            selected_line,
        ))

    conn.commit()
    cursor.close()

# ==========================================
# UTILITY HELPERS
# ==========================================

def clean_number(value):
    if value is None or pd.isna(value):
        return None
    try:
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None
            value = value.replace(",", "")
        return float(value)
    except Exception:
        return None

def normalize_text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().lower()


def normalize_line_value(value):
    if value is None:
        return "None"
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower() in {"", "none", "n/a", "na"}:
            return "None"
        return cleaned
    return str(value)


def find_data_header(df):
    for index in range(len(df)):
        row = df.iloc[index]
        values = [normalize_text(value) for value in row.values]

        has_timestamp = any("timestamp" in value for value in values)
        has_kwh = any(value == "kwh" for value in values)
        has_kvah = any(value == "kvah" for value in values)

        if has_timestamp and has_kwh and has_kvah:
            return index
    return None

def find_column(columns, names):
    for column in columns:
        normalized = normalize_text(column).replace(".", "").replace(" ", "").replace("_", "")
        for name in names:
            target = name.lower().replace(".", "").replace(" ", "").replace("_", "")
            if normalized == target:
                return column
    return None

def find_report_date(df):
    for row_index in range(min(len(df), 20)):
        row = df.iloc[row_index]
        for col_index, value in enumerate(row):
            text = normalize_text(value)
            if text == "from:":
                if col_index + 1 < len(row):
                    date_value = row.iloc[col_index + 1]
                    parsed = pd.to_datetime(date_value, errors="coerce", dayfirst=True)
                    if not pd.isna(parsed):
                        return parsed.strftime("%Y-%m-%d")
    return None


def infer_report_date_from_name(file_name):
    if not file_name:
        return None
    matches = [
        m for m in [
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{2}-[A-Za-z]{3}-\d{2})",
            r"(\d{2}[A-Za-z]{3}[\d]{2})",
        ]
    ]
    for pattern in matches:
        search = __import__('re').search(pattern, file_name)
        if search:
            value = search.group(1)
            parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
            if not pd.isna(parsed):
                return parsed.strftime("%Y-%m-%d")
    return None


def line_matches(line_name, selected_line):
    target = normalize_line_value(selected_line).lower()
    if target in {"", "none"}:
        return True
    line = str(line_name or "").strip().lower()
    return target in line or line in target or target.replace(" ", "") in line.replace(" ", "")

# ==========================================
# PROCESS SHEET
# ==========================================

def process_sheet(
    conn,
    excel_file,
    sheet_name,
    location_id,
    selected_location="Bangalore",
    selected_plant="TPREL-Bangalore",
    selected_line="Vega",
):
    print("\n" + "=" * 80)
    print(f"Processing: {sheet_name} | Location ID: {location_id}")
    print("=" * 80)

    try:
        if isinstance(excel_file, pd.ExcelFile):
            df = excel_file.parse(sheet_name, header=None)
        else:
            df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
    except Exception as e:
        print(f"ERROR reading sheet: {e}")
        return 0

    if df.empty:
        print("Sheet is empty.")
        return 0

    print(f"Total Excel rows: {len(df)}")
    
    file_name = getattr(excel_file, "name", "")
    report_date = find_report_date(df)
    if report_date is None:
        report_date = infer_report_date_from_name(file_name)
    if report_date is None:
        print("WARNING: Could not find report From date.")
        return 0
    print(f"Report date: {report_date}")

    header_row = find_data_header(df)
    if header_row is None:
        print("WARNING: Header not found; using fallback summary parser.")
        numeric_values = []
        for row_index, row in df.iterrows():
            row_text = [str(v).strip() if not pd.isna(v) else "" for v in row.tolist()]
            joined = " ".join(row_text).lower()
            if "total" in joined and (line_matches(sheet_name, selected_line) or line_matches(joined, selected_line)):
                for value in row.tolist():
                    if pd.notna(value):
                        try:
                            numeric = float(str(value).replace(',', '').replace('kwh', '').strip())
                            numeric_values.append(numeric)
                        except Exception:
                            pass
        if not numeric_values:
            print("ERROR: Could not detect any numeric solar total in the workbook sheet.")
            return 0

        generation_kwh = max(numeric_values)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO solar_time_logs
            (location_id, log_date, log_timestamp, kwh, site_location, plant_name, line_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (location_id, log_date, log_timestamp)
            DO UPDATE SET kwh = EXCLUDED.kwh,
                          site_location = EXCLUDED.site_location,
                          plant_name = EXCLUDED.plant_name,
                          line_name = EXCLUDED.line_name
            """,
            (
                location_id,
                report_date,
                "00:00:00",
                generation_kwh,
                selected_location,
                selected_plant,
                selected_line,
            ),
        )
        conn.commit()
        cursor.close()
        update_daily_summary(conn, location_id, report_date, selected_location, selected_plant, selected_line)
        print(f"Fallback solar total inserted: {generation_kwh}")
        return 1

    print(f"Data header row: {header_row + 1}")

    headers = df.iloc[header_row].tolist()
    data = df.iloc[header_row + 1:].copy()
    data.columns = headers

    timestamp_col = find_column(data.columns, ["Timestamp"])
    kwh_col = find_column(data.columns, ["kWh"])
    kvah_col = find_column(data.columns, ["kVAh"])
    kw_col = find_column(data.columns, ["kW"])
    kva_col = find_column(data.columns, ["kVA"])
    current_col = find_column(data.columns, ["current"])
    pf_col = find_column(data.columns, ["P.F.", "PF"])

    if timestamp_col is None:
        print("ERROR: Timestamp column not found.")
        return 0

    cursor = conn.cursor()
    inserted = 0
    skipped = 0

    for index, row in data.iterrows():
        try:
            timestamp_value = row[timestamp_col]

            if timestamp_value is None or pd.isna(timestamp_value):
                skipped += 1
                continue

            timestamp_text = str(timestamp_value).strip()
            summary_rows = ["maximum", "minimum", "average", "total"]

            if timestamp_text.lower() in summary_rows:
                skipped += 1
                continue

            parsed_time = pd.to_datetime(timestamp_value, errors="coerce")
            if pd.isna(parsed_time):
                parsed_time = pd.to_datetime(timestamp_text, format="%I:%M:%S %p", errors="coerce")

            if pd.isna(parsed_time):
                skipped += 1
                continue

            log_timestamp = parsed_time.strftime("%H:%M:%S")

            kwh = clean_number(row[kwh_col]) if kwh_col else None
            kvah = clean_number(row[kvah_col]) if kvah_col else None
            kw = clean_number(row[kw_col]) if kw_col else None
            kva = clean_number(row[kva_col]) if kva_col else None
            current = clean_number(row[current_col]) if current_col else None
            power_factor = clean_number(row[pf_col]) if pf_col else None

            cursor.execute("""
                INSERT INTO solar_time_logs
                (
                    location_id,
                    log_date,
                    log_timestamp,
                    kwh,
                    kvah,
                    kw,
                    kva,
                    current,
                    power_factor,
                    site_location,
                    plant_name,
                    line_name
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

                ON CONFLICT (
                    location_id,
                    log_date,
                    log_timestamp
                )
                DO UPDATE SET
                    kwh = EXCLUDED.kwh,
                    kvah = EXCLUDED.kvah,
                    kw = EXCLUDED.kw,
                    kva = EXCLUDED.kva,
                    current = EXCLUDED.current,
                    power_factor = EXCLUDED.power_factor,
                    site_location = EXCLUDED.site_location,
                    plant_name = EXCLUDED.plant_name,
                    line_name = EXCLUDED.line_name
            """, (
                location_id,
                report_date,
                log_timestamp,
                kwh,
                kvah,
                kw,
                kva,
                current,
                power_factor,
                selected_location,
                selected_plant,
                selected_line,
            ))

            inserted += 1

        except Exception as e:
            print(f"Error processing row {index + 1}: {e}")
            skipped += 1

    conn.commit()
    cursor.close()

    update_daily_summary(
        conn,
        location_id,
        report_date,
        selected_location,
        selected_plant,
        selected_line,
    )

    print(f"Rows processed : {inserted}")
    print(f"Rows skipped   : {skipped}")
    return inserted

# ==========================================
# DAILY SUMMARY
# ==========================================

def update_daily_summary(
    conn,
    location_id,
    log_date,
    selected_location="Bangalore",
    selected_plant="TPREL-Bangalore",
    selected_line="Vega",
):
    cursor = conn.cursor()

    cursor.execute("""
        SELECT MAX(kwh)
        FROM solar_time_logs
        WHERE location_id = %s
          AND log_date = %s
          AND kwh IS NOT NULL
    """, (
        location_id,
        log_date
    ))

    result = cursor.fetchone()
    if not result:
        cursor.close()
        return

    generation_kwh = result[0]
    if generation_kwh is None:
        cursor.close()
        return

    cursor.execute("""
        INSERT INTO solar_daily_summary
        (
            location_id,
            log_date,
            generation_kwh,
            site_location,
            plant_name,
            line_name
        )
        VALUES (%s, %s, %s, %s, %s, %s)

        ON CONFLICT (
            location_id,
            log_date
        )
        DO UPDATE SET
            generation_kwh = EXCLUDED.generation_kwh,
            site_location = EXCLUDED.site_location,
            plant_name = EXCLUDED.plant_name,
            line_name = EXCLUDED.line_name
    """, (
        location_id,
        log_date,
        generation_kwh,
        selected_location,
        selected_plant,
        selected_line,
    ))

    conn.commit()
    cursor.close()

# ==========================================
# MAIN ROUTINE
# ==========================================

def build_dashboard_snapshot(
    uploaded_file_name,
    selected_location="Bangalore",
    selected_plant="TPREL-Bangalore",
    selected_line="Vega",
):
    """Build the Command Center snapshot from the just-ingested solar data."""
    conn = get_connection()
    try:
        line_label = normalize_line_value(selected_line)
        if line_label.lower() == "none":
            energy = pd.read_sql_query(
                """
                    SELECT s.location_name AS location,
                           MAX(d.generation_kwh) AS daily_kwh,
                           MAX(d.generation_kwh) AS mtd_kwh
                    FROM solar_daily_summary d
                    JOIN solar_locations s ON s.location_id = d.location_id
                    WHERE d.site_location = %s
                      AND d.plant_name = %s
                    GROUP BY s.location_name
                    ORDER BY s.location_name
                """,
                conn,
                params=(selected_location, selected_plant),
            )
            source_label = "Utility Solar Generation"
        else:
            energy = pd.read_sql_query(
                """
                    SELECT s.location_name AS location,
                           MAX(d.generation_kwh) AS daily_kwh,
                           MAX(d.generation_kwh) AS mtd_kwh
                    FROM solar_daily_summary d
                    JOIN solar_locations s ON s.location_id = d.location_id
                    WHERE d.site_location = %s
                      AND d.plant_name = %s
                      AND d.line_name = %s
                    GROUP BY s.location_name
                    ORDER BY s.location_name
                """,
                conn,
                params=(selected_location, selected_plant, line_label),
            )
            source_label = f"{line_label} Line"
        if energy.empty:
            energy = pd.DataFrame(columns=["location", "daily_kwh", "mtd_kwh"])

        solar = pd.DataFrame(
            [{
                "source": source_label,
                "daily_kwh": float(energy["daily_kwh"].sum()) if not energy.empty else 0.0,
                "mtd_kwh": float(energy["mtd_kwh"].sum()) if not energy.empty else 0.0,
            }]
        )

        return {
            "energy": energy,
            "solar": solar,
            "transformers": pd.DataFrame(),
            "sources": [(f"{source_label} solar upload", uploaded_file_name)],
        }
    finally:
        conn.close()


def ingest_uploaded_file(
    uploaded_file,
    selected_location="Bangalore",
    selected_plant="TPREL-Bangalore",
    selected_line="Vega",
):
    """Read a Streamlit upload and insert all solar sheets into PostgreSQL."""
    if uploaded_file is None:
        raise ValueError("No file uploaded.")

    name = getattr(uploaded_file, "name", "")
    if not name.lower().endswith((".xlsx", ".xls", ".csv")):
        raise ValueError("Please upload an Excel or CSV solar report (.xlsx, .xls, .csv).")

    conn = get_connection()
    try:
        create_tables(conn)
        insert_locations(conn, selected_location, selected_plant, selected_line)

        name_lower = name.lower()
        if name_lower.endswith(".csv"):
            try:
                uploaded_file.seek(0)
            except Exception:
                pass
            if hasattr(uploaded_file, "read"):
                payload = uploaded_file.read()
                try:
                    uploaded_file.seek(0)
                except Exception:
                    pass
                csv_df = pd.read_csv(io.BytesIO(payload), header=None)
            else:
                csv_df = pd.read_csv(uploaded_file, header=None)
            total = 0
            report_date = infer_report_date_from_name(name)
            if report_date is None:
                report_date = pd.Timestamp.today().strftime("%Y-%m-%d")

            for row_index, row in csv_df.iterrows():
                row_values = [value for value in row.tolist() if not pd.isna(value)]
                if len(row_values) < 2:
                    continue
                location_name = str(row.iloc[1]).strip() if len(row) > 1 else ""
                if not location_name or location_name.lower() == "locations" or location_name.lower() == "total":
                    continue
                numeric_values = []
                for val in row.iloc[2:]:
                    if pd.isna(val):
                        continue
                    try:
                        numeric_values.append(float(str(val).replace(',', '').strip()))
                    except Exception:
                        pass
                if not numeric_values:
                    continue
                generation_kwh = numeric_values[-1]

                matched_location = None
                for solar_name, location_meta in SOLAR_LOCATIONS.items():
                    if location_name.lower().strip() == solar_name.lower().strip():
                        matched_location = location_meta
                        break
                if matched_location is None:
                    for solar_name, location_meta in SOLAR_LOCATIONS.items():
                        if location_name.lower().strip() in solar_name.lower().strip() or solar_name.lower().strip() in location_name.lower().strip():
                            matched_location = location_meta
                            break
                if matched_location is None:
                    continue

                location_id = matched_location["location_id"]
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO solar_time_logs
                    (location_id, log_date, log_timestamp, kwh, site_location, plant_name, line_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (location_id, log_date, log_timestamp)
                    DO UPDATE SET kwh = EXCLUDED.kwh,
                                  site_location = EXCLUDED.site_location,
                                  plant_name = EXCLUDED.plant_name,
                                  line_name = EXCLUDED.line_name
                    """,
                    (
                        location_id,
                        report_date,
                        "00:00:00",
                        generation_kwh,
                        selected_location,
                        selected_plant,
                        selected_line,
                    ),
                )
                conn.commit()
                cursor.close()
                update_daily_summary(conn, location_id, report_date, selected_location, selected_plant, selected_line)
                total += 1
            return total

        excel = pd.ExcelFile(uploaded_file)
        total = 0
        matched_sheet = False

        by_line = [
            sheet_name for sheet_name in excel.sheet_names
            if line_matches(sheet_name, selected_line)
        ]

        if by_line:
            target_sheets = by_line
        else:
            target_sheets = excel.sheet_names

        line_label = normalize_line_value(selected_line)
        if line_label.lower() == "vega":
            selected_location_id = 1
        elif line_label.lower() == "hexa":
            selected_location_id = 6
        else:
            selected_location_id = 1
        for sheet_name in target_sheets:
            if sheet_name not in excel.sheet_names:
                continue
            count = process_sheet(
                conn,
                excel,
                sheet_name,
                selected_location_id,
                selected_location,
                selected_plant,
                selected_line,
            )
            total += count
            if count > 0:
                matched_sheet = True

        if not matched_sheet:
            for sheet_name, location in SOLAR_LOCATIONS.items():
                if sheet_name not in excel.sheet_names:
                    continue
                count = process_sheet(
                    conn,
                    excel,
                    sheet_name,
                    location["location_id"],
                    selected_location,
                    selected_plant,
                    selected_line,
                )
                total += count

        snapshot = build_dashboard_snapshot(
            name,
            selected_location,
            selected_plant,
            selected_line,
        )
        replace_dashboard_snapshot(snapshot)
        return total
    finally:
        conn.close()


def render_excel_uploader(
    selected_location="Bangalore",
    selected_plant="TPREL-Bangalore",
    selected_line="Vega",
):
    """Streamlit widget that uploads and inserts a solar Excel file."""
    st.subheader("☀️ Solar Excel Upload")
    uploaded_file = st.file_uploader(
        "Upload solar Excel or CSV report",
        type=["xlsx", "xls", "csv"],
        key=f"solar_excel_uploader_{selected_line}_{selected_plant}"
    )

    if uploaded_file is None:
        return None

    try:
        total_records = ingest_uploaded_file(
            uploaded_file,
            selected_location,
            selected_plant,
            selected_line,
        )

        if total_records == 0:
            st.warning(
                "No solar records were detected for "
                f"{selected_line} ({selected_plant}, {selected_location}). "
                "This workbook does not appear to contain solar-generation data for the selected line. "
                "Please upload a solar report for the correct plant/line."
            )
            return total_records

        st.success(
            f"Processed {total_records} solar records for {selected_line} "
            f"({selected_plant}, {selected_location}) into PostgreSQL."
        )
        st.caption("Command Center dashboard refreshed from the latest upload.")
        return total_records
    except Exception as exc:
        st.error(f"Could not ingest the uploaded file: {exc}")
        return 0


def main():
    print("\n" + "=" * 80)
    print("SOLAR POWER SENSE - POSTGRESQL EXCEL INGESTION")
    print("=" * 80)

    if not os.path.exists(EXCEL_FILE):
        print(f"\nERROR: Excel file not found: {EXCEL_FILE}")
        return

    conn = get_connection()

    try:
        create_tables(conn)
        insert_locations(conn)

        excel = pd.ExcelFile(EXCEL_FILE)
        print("\nExcel sheets found:")
        for sheet in excel.sheet_names:
            print(f"  {sheet}")

        total = 0
        for sheet_name, location in SOLAR_LOCATIONS.items():
            if sheet_name not in excel.sheet_names:
                print(f"\nWARNING: Sheet not found: {sheet_name}")
                continue

            count = process_sheet(
                conn,
                EXCEL_FILE,
                sheet_name,
                location["location_id"]
            )
            total += count

        print("\n" + "=" * 80)
        print(f"TOTAL RECORDS PROCESSED: {total}")
        print("=" * 80)

    finally:
        conn.close()

if __name__ == "__main__":
    main()