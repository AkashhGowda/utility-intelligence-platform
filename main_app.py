
import glob
import hashlib
import io
import json
from pathlib import Path
from datetime import datetime
from urllib import parse, request

import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from services.data_service import (
    load_file,
    clean_data,
    validate_data,
    save_uploaded_data,
    load_saved_data,
    get_uploaded_files,
    UPLOAD_DIR,
    get_data_summary,
    delete_uploaded_file,
    load_excel_sheets,
    validate_workbook_sheets,
    save_uploaded_workbook,
    load_saved_workbook,
)
from services.ai_agent import OllamaUnavailableError, ask_ai, build_ai_context, get_ai_status
from database import (
    get_question_history,
    get_previous_answer,
    save_question_history,
    clear_question_history,
    load_dashboard_snapshot,
    load_dashboard_tables,
    empty_dashboard_tables,
    load_uploaded_datasets,
    save_uploaded_dataset,
    get_dashboard_source_summary,
    replace_dashboard_snapshot,
    read_solar_time_logs,
)

from ingest_solar_excel import ingest_uploaded_file, render_excel_uploader

# Optional PDF/Excel exports
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False
from services.config_service import (
    get_app_config,
    update_config,
)
from services.admin_ui import render_admin_control_center
from services.admin_service import get_utilities


# Keep chart semantics stable across the Utility workspace.  These values mirror
# the established Streamlit theme palette in .streamlit/config.toml.
CHART_COLORS = {
    "actual": "#2563EB",
    "target": "#F59E0B",
    "forecast": "#7C3AED",
    "solar": "#F59E0B",
    "grid": "#2563EB",
    "water": "#0891B2",
    "air": "#0F766E",
    "energy": "#2563EB",
    "power": "#2563EB",
    "healthy": "#10B981",
    "warning": "#F59E0B",
    "anomaly": "#EF4444",
}
CHART_FALLBACK_COLORS = ["#2563EB", "#14B8A6", "#F59E0B", "#7C3AED", "#10B981", "#EF4444"]
STATUS_COLORS = {
    "Normal": "#16A34A",
    "Warning": "#F59E0B",
    "Critical": "#DC2626",
}
STATUS_ORDER = ["Normal", "Warning", "Critical"]


def semantic_chart_colors(series_names, default="energy"):
    """Return deterministic colors for Streamlit multi-series chart legends."""
    colors = []
    for index, name in enumerate(series_names):
        label = str(name).lower()
        if "actual" in label:
            color_key = "actual"
        elif "target" in label or "budget" in label or "plan" in label:
            color_key = "target"
        elif "forecast" in label or "prediction" in label:
            color_key = "forecast"
        elif "solar" in label:
            color_key = "solar"
        elif "grid" in label:
            color_key = "grid"
        elif "water" in label:
            color_key = "water"
        elif "air" in label or "humidity" in label:
            color_key = "air"
        elif "alert" in label or "anomaly" in label:
            color_key = "anomaly"
        elif "warning" in label:
            color_key = "warning"
        elif "power" in label or "energy" in label or "kwh" in label:
            color_key = "power"
        else:
            color_key = None
        colors.append(CHART_COLORS[color_key] if color_key else CHART_FALLBACK_COLORS[index % len(CHART_FALLBACK_COLORS)])
    return colors or [CHART_COLORS[default]]


def _target_column(frame, actual_column):
    candidates = [
        f"{actual_column}_target",
        f"target_{actual_column}",
        "target",
        "target_value",
    ]
    return next((column for column in candidates if column in frame.columns), None)


def _status_chart_frame(frame, category_column, actual_column, target_column=None):
    chart = frame[[category_column, actual_column]].copy()
    chart[actual_column] = pd.to_numeric(chart[actual_column], errors="coerce")
    chart = chart.dropna(subset=[category_column, actual_column])

    target_column = target_column or _target_column(frame, actual_column)
    if target_column and target_column in frame.columns:
        chart["Target"] = pd.to_numeric(frame.loc[chart.index, target_column], errors="coerce")
    else:
        chart["Target"] = np.nan

    ratio = chart[actual_column].div(chart["Target"].replace(0, np.nan))
    chart["Status"] = np.select(
        [ratio.notna() & (ratio <= 1), ratio.notna() & (ratio <= 1.10)],
        ["Normal", "Warning"],
        default="Critical",
    )
    chart.loc[chart["Target"].isna(), "Status"] = "Normal"
    return chart, target_column


def render_status_bar_chart(
    frame,
    category_column,
    actual_column,
    title=None,
    target_column=None,
    height=320,
):
    """Render existing utility values with dynamic target/status encoding."""
    chart, target_column = _status_chart_frame(
        frame, category_column, actual_column, target_column
    )
    if chart.empty:
        st.info("No chart data is available.")
        return

    if title:
        st.markdown(f"### {title}")
    st.markdown(
        "<span style='color:#16A34A;font-weight:600'>● Normal</span> &nbsp; "
        "<span style='color:#F59E0B;font-weight:600'>● Warning</span> &nbsp; "
        "<span style='color:#DC2626;font-weight:600'>● Critical</span> &nbsp; "
        "<span style='color:#F59E0B;font-weight:600'>- Target</span>",
        unsafe_allow_html=True,
    )

    tooltip = [
        alt.Tooltip(f"{category_column}:N", title=category_column.replace("_", " ").title()),
        alt.Tooltip(f"{actual_column}:Q", title="Actual", format=",.2f"),
        alt.Tooltip("Target:Q", title="Target", format=",.2f"),
        alt.Tooltip("Status:N", title="Status"),
    ]
    bars = alt.Chart(chart).mark_bar().encode(
        x=alt.X(f"{category_column}:N", title=None, sort="-y"),
        y=alt.Y(f"{actual_column}:Q", title="Actual", scale=alt.Scale(zero=True)),
        color=alt.Color(
            "Status:N",
            scale=alt.Scale(domain=STATUS_ORDER, range=[STATUS_COLORS[item] for item in STATUS_ORDER]),
            legend=alt.Legend(title="Status"),
        ),
        tooltip=tooltip,
    )
    chart_view = bars.properties(height=height)

    if target_column and chart["Target"].notna().any():
        target_marks = alt.Chart(chart[chart["Target"].notna()]).mark_tick(
            color=CHART_COLORS["target"], thickness=3, size=24
        ).encode(
            x=alt.X(f"{category_column}:N", title=None, sort="-y"),
            y=alt.Y("Target:Q", title="Actual"),
            tooltip=tooltip,
        )
        chart_view = chart_view + target_marks

    st.altair_chart(chart_view, use_container_width=True)


def sign_out():
    # Clear identity and navigation state before returning to the login screen.
    for key in list(st.session_state.keys()):
        st.session_state.pop(key, None)
    st.rerun()


def current_user_is_admin() -> bool:
    return str(st.session_state.get("user_role", "")).upper() == "ADMIN"


@st.cache_data(ttl=30, show_spinner=False)
def load_ai_time_logs(plant_name=None, site_location=None):
    """Reuse the read-only time-series query during rapid chat reruns."""
    try:
        frame = read_solar_time_logs(plant_name=plant_name, site_location=site_location)
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def render_ai_assistant():
    """Render the chat interface using the existing utility AI agent."""
    if "ai_assistant_messages" not in st.session_state:
        st.session_state["ai_assistant_messages"] = []

    with st.sidebar.expander("CHAT HISTORY", expanded=True):
        if st.button("Clear Conversation", key="clear_ai_assistant_conversation"):
            st.session_state["ai_assistant_messages"] = []
            st.rerun()
        for message in st.session_state["ai_assistant_messages"]:
            if message.get("role") == "user":
                st.caption(f"• {message.get('content', '')[:80]}")

    st.title("🤖 Utility Intelligence AI")
    st.caption(
        "Ask questions about energy, solar, utilities, transformers, environment, "
        "electrical quality, anomalies, and reports."
    )
    ai_status = get_ai_status()
    if ai_status["available"]:
        st.success(str(ai_status["message"]))
    else:
        st.warning(
            f"General AI reasoning is unavailable: {ai_status['message']} "
            "Exact calculations still work from the loaded data."
        )

    for message in st.session_state["ai_assistant_messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input(
        "Ask the AI Assistant about your plant, utilities, energy, solar, alerts or reports...",
        key="ai_assistant_input",
    )
    if not question or not question.strip():
        return

    question = question.strip()
    st.session_state["ai_assistant_messages"].append(
        {"role": "user", "content": question}
    )
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing your utility data..."):
            named_dataframes = {
                str(source_name): dataframe.copy()
                for source_name, dataframe in data.items()
                if isinstance(dataframe, pd.DataFrame) and not dataframe.empty
            }
            try:
                named_dataframes.update(load_uploaded_datasets())
            except Exception as exc:
                st.warning(f"Newly uploaded AI data could not be loaded from PostgreSQL: {exc}")
            time_logs = load_ai_time_logs(
                plant_name=st.session_state.get("plant"),
                site_location=st.session_state.get("location"),
            )
            if not time_logs.empty:
                named_dataframes["Solar telemetry"] = time_logs.copy()
            question_text = question.lower()
            keyword_groups = {
                "solar": ("solar", "generation", "inverter"),
                "air": ("air", "compressed"),
                "environment": ("temperature", "humidity", "environment"),
                "transformer": ("transformer", "loading"),
                "pf": ("power factor", "pf", "reactive"),
                "energy": ("energy", "consumption", "power"),
            }
            selected_dataframes = []
            for source_name, dataframe in named_dataframes.items():
                source_text = f"{source_name} {' '.join(map(str, dataframe.columns))}".lower()
                if any(term in question_text for terms in keyword_groups.values() for term in terms):
                    if any(term in question_text and term in source_text for terms in keyword_groups.values() for term in terms):
                        selected_dataframes.append(dataframe)
            if not selected_dataframes:
                selected_dataframes = list(named_dataframes.values())
            ai_dataframe = pd.concat(selected_dataframes, ignore_index=True, sort=False) if selected_dataframes else pd.DataFrame()
            data_source = data.get("data_source", "PostgreSQL dashboard snapshot")
            recent_context = "\n".join(
                f"{message.get('role', 'unknown')}: {message.get('content', '')}"
                for message in st.session_state["ai_assistant_messages"][:-1][-6:]
            )

            if ai_dataframe.empty:
                answer = "No utility data is currently available for analysis."
            else:
                data_context = build_ai_context(named_dataframes)
                data_signature = hashlib.sha256(data_context.encode("utf-8")).hexdigest()
                try:
                    answer = get_previous_answer(
                        question,
                        data_signature,
                        username=st.session_state.get("username"),
                    )
                except Exception:
                    answer = None

                if not answer:
                    try:
                        answer = ask_ai(
                            question,
                            data_context,
                            ai_dataframe,
                            conversation_context=recent_context,
                        )
                    except OllamaUnavailableError:
                        answer = (
                            "AI Assistant is currently unavailable. "
                            "Please check the configured AI model/API connection."
                        )
                    except Exception:
                        answer = (
                            "AI Assistant is currently unavailable. "
                            "Please check the configured AI model/API connection."
                        )

                    if answer:
                        try:
                            save_question_history(
                                question,
                                answer,
                                data_signature,
                                username=st.session_state.get("username"),
                            )
                        except Exception:
                            pass

                if answer:
                    st.caption(f"Data source: {data_source}")

        st.markdown(answer)

    st.session_state["ai_assistant_messages"].append(
        {"role": "assistant", "content": answer}
    )


st.set_page_config(
    page_title="Automated Utility Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -----------------------------
# Styling
# -----------------------------
st.markdown("""
<style>

/* =========================================================
   UTILITY INTELLIGENCE — ENTERPRISE VISUAL SYSTEM
   ========================================================= */

:root {
    --ui-navy: #12355B;
    --ui-blue: #2563EB;
    --ui-cyan: #0891B2;
    --ui-teal: #0F766E;
    --ui-green: #16A34A;
    --ui-purple: #7C3AED;
    --ui-orange: #F59E0B;
    --ui-red: #DC2626;
    --ui-bg: #F4F7FB;
    --ui-card: #FFFFFF;
    --ui-border: #E2E8F0;
    --ui-text: #172033;
    --ui-muted: #64748B;
}

/* ---------------------------------------------------------
   MAIN APPLICATION
   --------------------------------------------------------- */

.stApp {
    background: var(--ui-bg);
    color: var(--ui-text);
}

/* Main content width */

.block-container {
    padding-top: 1.4rem;
    padding-bottom: 2rem;
    max-width: 1500px;
}

/* ---------------------------------------------------------
   HEADINGS
   --------------------------------------------------------- */

h1 {
    color: var(--ui-navy) !important;
    font-weight: 750 !important;
    letter-spacing: -0.5px;
}

h2 {
    color: var(--ui-navy) !important;
    font-weight: 700 !important;
}

h3 {
    color: #1E3A5F !important;
    font-weight: 650 !important;
}

/* ---------------------------------------------------------
   SIDEBAR
   --------------------------------------------------------- */

section[data-testid="stSidebar"] {
    background: #20252B;
}

section[data-testid="stSidebar"] * {
    color: #F8FAFC;
}

/* Sidebar radio */

section[data-testid="stSidebar"]
div[role="radiogroup"] {
    gap: 5px;
}

/* Navigation options */

section[data-testid="stSidebar"]
div[role="radiogroup"] label {
    border-radius: 10px;
    padding: 8px 10px;
    transition: all 0.18s ease;
}

/* Navigation hover */

section[data-testid="stSidebar"]
div[role="radiogroup"] label:hover {
    background: rgba(255,255,255,0.10);
}

/* Selected navigation */

section[data-testid="stSidebar"]
div[role="radiogroup"]
label[data-checked="true"] {
    background: #303840;
    border-left: 3px solid #67E8F9;
}

/* Sidebar divider */

section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.16);
}

/* ---------------------------------------------------------
   METRIC CARDS
   --------------------------------------------------------- */

div[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid #D9E2EC;
    border-radius: 14px;
    padding: 16px 18px;
    min-height: 105px;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    position: relative;
    overflow: hidden;
}

div[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.10);
}


div[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 7px 18px rgba(15, 23, 42, 0.10);
}

div[data-testid="stMetricLabel"] {
    color: #334155 !important;
    opacity: 1 !important;
    font-size: 0.85rem !important;
    font-weight: 700 !important;
}

div[data-testid="stMetricLabel"] * {
    color: #334155 !important;
    opacity: 1 !important;
}

div[data-testid="stMetricValue"] {
    color: #12355B !important;
    opacity: 1 !important;
    font-weight: 750 !important;
}

div[data-testid="stMetricValue"] * {
    color: #12355B !important;
    opacity: 1 !important;
}
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] p {
    color: #F8FAFC !important;
}

section[data-testid="stSidebar"] label {
    color: #F8FAFC !important;
}

/* ---------------------------------------------------------
   CONTAINERS / CARDS
   --------------------------------------------------------- */

div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px;
}

/* ---------------------------------------------------------
   BUTTONS
   --------------------------------------------------------- */

.stButton > button {
    border-radius: 9px;
    border: 1px solid #CBD5E1;
    font-weight: 600;
    transition: all 0.18s ease;
}

.stButton > button:hover {
    border-color: var(--ui-blue);
    color: var(--ui-blue);
    transform: translateY(-1px);
}

/* ---------------------------------------------------------
   DOWNLOAD BUTTONS
   --------------------------------------------------------- */

.stDownloadButton > button {
    border-radius: 9px;
    font-weight: 600;
}

/* ---------------------------------------------------------
   DATAFRAMES
   --------------------------------------------------------- */

div[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--ui-border);
}

/* ---------------------------------------------------------
   INPUTS
   --------------------------------------------------------- */

.stTextInput input,
.stNumberInput input,
.stSelectbox,
.stMultiSelect {
    border-radius: 9px;
}

/* ---------------------------------------------------------
   ALERT / STATUS COLORS
   --------------------------------------------------------- */

div[data-testid="stAlert"] {
    border-radius: 11px;
}

/* ---------------------------------------------------------
   EXPANDERS
   --------------------------------------------------------- */

details {
    border-radius: 11px !important;
    border: 1px solid var(--ui-border) !important;
}

/* ---------------------------------------------------------
   LINKS
   --------------------------------------------------------- */

a {
    color: var(--ui-blue);
}

/* ---------------------------------------------------------
   SMALL SCREEN POLISH
   --------------------------------------------------------- */

@media (max-width: 900px) {

    .block-container {
        padding-left: 1rem;
        padding-right: 1rem;
    }

}

</style>
""", unsafe_allow_html=True)

DATA_DIR = Path(__file__).resolve().parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
SEARCH_PATHS = [DATA_DIR, UPLOAD_DIR]

# -----------------------------
# Helpers
# -----------------------------
def clean_name(x):
    return str(x).strip().lower().replace("\n", " ").replace("_", " ")

def find_file(patterns):
    for p in patterns:
        for base_dir in SEARCH_PATHS:
            matches = glob.glob(str(base_dir / p))
            if matches:
                return matches[0]
            matches = glob.glob(str(base_dir / "**" / p), recursive=True)
            if matches:
                return matches[0]
    return None

def read_sheet(path, sheet, header=None):
    try:
        if str(path).lower().endswith(".csv"):
            return pd.read_csv(path, header=header)

        df = pd.read_excel(
            path,
            sheet_name=sheet,
            header=header
        )

        # Remove completely empty columns
        df = df.dropna(axis=1, how="all")

        # Remove Excel-generated empty columns
        df = df.loc[
            :,
            ~df.columns.astype(str).str.startswith("Unnamed")
        ]

        # Remove completely empty rows
        df = df.dropna(how="all")

        # Clean mixed object columns
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].apply(
                    lambda x: str(x).strip()
                    if pd.notna(x)
                    else None
                )

        return df

    except Exception as e:
        print(f"Could not read sheet {sheet}: {e}")
        return pd.DataFrame()


def parse_solar_csv(csv_path):
    try:
        raw = pd.read_csv(csv_path)
        table = raw.copy()
        if table.empty:
            return pd.DataFrame()

        start_index = None
        for idx, row in table.iterrows():
            if row.astype(str).str.contains("Locations", case=False, na=False).any():
                start_index = idx + 1
                break

        if start_index is None:
            return pd.DataFrame()

        data = table.iloc[start_index:].copy()
        rows = []
        for _, row in data.iterrows():
            loc = None
            for value in row.tolist()[:2]:
                if pd.notna(value) and str(value).strip() not in {"", "nan", "NaN"}:
                    if "location" not in str(value).lower() and "sr. no." not in str(value).lower():
                        loc = str(value).strip()
                        break
            if loc is None:
                continue
            numeric_values = pd.to_numeric(row.iloc[2:], errors="coerce").dropna()
            if numeric_values.empty:
                continue
            daily = float(numeric_values.iloc[-1])
            rows.append({"source": loc, "daily_kwh": daily, "mtd_kwh": daily})

        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


def parse_daily_power_csv(csv_path):
    try:
        raw = pd.read_csv(csv_path)
        if raw.empty:
            return pd.DataFrame()

        rows = []
        for _, row in raw.iterrows():
            loc = row.iloc[0] if len(row) > 0 else None
            if pd.isna(loc):
                continue
            loc_text = str(loc).strip()
            if loc_text in {"", "Locations", "Sr. No.", "nan"}:
                continue
            numeric_values = pd.to_numeric(row.iloc[1:], errors="coerce").dropna()
            if numeric_values.empty:
                continue
            rows.append({"location": loc_text, "daily_kwh": float(numeric_values.iloc[-1]), "mtd_kwh": float(numeric_values.sum())})

        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

def numeric(v):
    try:
        return float(v)
    except Exception:
        return np.nan

def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def discover_files():
    files = []
    for base_dir in SEARCH_PATHS:
        if base_dir.exists():
            files.extend(glob.glob(str(base_dir / "*.xlsx")))
            files.extend(glob.glob(str(base_dir / "*.csv")))
    return sorted(set(files))

# -----------------------------
# Load real project data
# -----------------------------
@st.cache_data(show_spinner=False)
def load_project_data():
    result = {
        "energy": pd.DataFrame(),
        "transformers": pd.DataFrame(),
        "solar": pd.DataFrame(),
        "air": pd.DataFrame(),
        "environment": pd.DataFrame(),
        "pf": pd.DataFrame(),
        "sources": [],
    }

    # ---------- Tata Power daily ----------
    tata = find_file(["Daily_Tata_Power_Systems_LTD_17-Aug-26.xlsx"])
    if tata:
        try:
            df = read_sheet(tata, "Formulas_Overview", header=None)
            rows = []
            for i in range(4, len(df)):
                loc = df.iloc[i, 1] if df.shape[1] > 1 else None
                daily = numeric(df.iloc[i, 3]) if df.shape[1] > 3 else np.nan
                mtd = numeric(df.iloc[i, 4]) if df.shape[1] > 4 else np.nan
                if pd.notna(loc) and pd.notna(daily):
                    rows.append({"location": str(loc).strip(), "daily_kwh": daily, "mtd_kwh": mtd})
            result["energy"] = pd.DataFrame(rows)

            # Progressive daily history
            prog = read_sheet(tata, "Formulas_Progressive Report", header=None)
            if not prog.empty and prog.shape[1] > 3:
                loc_col = 2
                date_cols = []
                for j in range(3, prog.shape[1]):
                    if pd.notna(prog.iloc[3, j]):
                        try:
                            d = pd.to_datetime(prog.iloc[3, j])
                            date_cols.append((j, d))
                        except Exception:
                            pass
                hist = []
                for i in range(4, len(prog)):
                    loc = prog.iloc[i, loc_col]
                    if pd.isna(loc):
                        continue
                    for j, d in date_cols:
                        v = numeric(prog.iloc[i, j])
                        if pd.notna(v):
                            hist.append({"date": d, "location": str(loc).strip(), "kwh": v})
                if hist:
                    result["energy_history"] = pd.DataFrame(hist)
                else:
                    result["energy_history"] = pd.DataFrame()
            else:
                result["energy_history"] = pd.DataFrame()

            result["sources"].append(("Tata Power Daily", tata))
        except Exception:
            result["energy_history"] = pd.DataFrame()
    else:
        result["energy_history"] = pd.DataFrame()

    # ---------- Hexa / Vega ----------
    hv = find_file(["Daily_Hexa_and_Vega_power_consumption_17-Aug-26.xlsx"])
    hv_csv = find_file(["*Daily*Power*Consumption*.csv", "*Daily*Power*Consumption*.xlsx*", "*Daily*Power*Consumption*.*"])
    main = pd.DataFrame()
    hv_df = pd.DataFrame()
    if hv_csv:
        hv_df = parse_daily_power_csv(hv_csv)
        if hv_df.empty and hv:
            try:
                df = read_sheet(hv, "Daily Sheet", header=None)
                rows = []
                if not df.empty:
                    for i in range(2, len(df)):
                        loc = df.iloc[i, 0]
                        if pd.isna(loc):
                            continue
                        vals = []
                        for j in range(3, df.shape[1]):
                            v = numeric(df.iloc[i, j])
                            if pd.notna(v):
                                vals.append(v)
                        if vals:
                            rows.append({"location": str(loc).strip(), "daily_kwh": vals[-1], "mtd_kwh": np.nan})
                hv_df = pd.DataFrame(rows)
            except Exception:
                pass

    if not hv_df.empty:
        result["energy"] = pd.concat([result["energy"], hv_df.rename(columns={"location": "location"})], ignore_index=True)
        result["energy"] = result["energy"].drop_duplicates(subset=["location"], keep="last")

    if hv:
        try:
            main = read_sheet(hv, "Main Sheet", header=None)
            trs = []
            if not main.empty:
                for i in range(4, len(main)):
                    loc = str(main.iloc[i, 1]).strip() if main.shape[1] > 1 and pd.notna(main.iloc[i,1]) else ""
                    if "transformer" in loc.lower():
                        daily = numeric(main.iloc[i, 4])
                        mtd = numeric(main.iloc[i, 5])
                        sensor = main.iloc[i, 3] if main.shape[1] > 3 else None
                        if pd.notna(daily):
                            trs.append({"transformer": loc, "sensor_id": sensor, "daily_kwh": daily, "mtd_kwh": mtd})
            if trs:
                result["transformers"] = pd.DataFrame(trs)
            result["sources"].append(("Hexa & Vega", hv))
        except Exception:
            pass

    # ---------- Solar ----------
    solar = find_file([
        "Solar_Generation_-_U2_17-Aug-26.xlsx",
        "Solar_Generation_-_U2_17-Aug-26 (1).xlsx",
    ])
    solar_csv = find_file(["*Solar*Report*.csv", "*Monthly*Solar*.csv", "*Solar*Generation*.csv", "*Solar*U2*.csv"])
    if solar_csv:
        solar_df = parse_solar_csv(solar_csv)
        if not solar_df.empty:
            result["solar"] = solar_df
            result["sources"].append(("Solar Generation", solar_csv))
    elif solar:
        try:
            df = read_sheet(solar, "Solar daily sheet", header=None)
            rows = []
            for i in range(4, len(df)):
                loc = df.iloc[i, 1] if df.shape[1] > 1 else None
                daily = numeric(df.iloc[i, 3]) if df.shape[1] > 3 else np.nan
                mtd = numeric(df.iloc[i, 4]) if df.shape[1] > 4 else np.nan
                if pd.notna(loc) and pd.notna(daily):
                    rows.append({"source": str(loc).strip(), "daily_kwh": daily, "mtd_kwh": mtd})
            result["solar"] = pd.DataFrame(rows)
            result["sources"].append(("Solar Generation", solar))
        except Exception:
            pass

    # ---------- Air / utilities ----------
    air = find_file([
        "Tata_Power_Air_Report_-_U2_17-Aug-26.xlsx",
        "*Tata*Power*Air*Report*.xlsx",
    ])
    if air:
        try:
            df = read_sheet(air, "Summary Report", header=None)
            rows = []
            for i in range(4, len(df)):
                loc = df.iloc[i, 2] if df.shape[1] > 2 else None
                avg_flow = numeric(df.iloc[i, 3]) if df.shape[1] > 3 else np.nan
                total = numeric(df.iloc[i, 4]) if df.shape[1] > 4 else np.nan
                if pd.notna(loc):
                    rows.append({"utility": str(loc).strip(), "avg_flow_m3_hr": avg_flow, "total_m3": total})
            result["air"] = pd.DataFrame(rows)
            result["sources"].append(("Air / Utilities", air))
        except Exception:
            pass

    # ---------- Environment ----------
    env = find_file(["Tata_Power_Solar_Systems_Ltd_Humidity___Temperature_-_U2_17-Aug-26.xlsx"])
    if env:
        try:
            hum = read_sheet(env, "Humidity", header=None)
            temp = read_sheet(env, "Temperature", header=None)

            # Columns begin at row 2; timestamp at column 1.
            env_rows = []
            if not hum.empty:
                locations = list(hum.iloc[2])
                for j in range(2, hum.shape[1]):
                    loc = hum.iloc[2, j] if j < len(locations) else None
                    if pd.isna(loc) or str(loc).strip() == "nan":
                        continue
                    vals = pd.to_numeric(hum.iloc[3:, j], errors="coerce").dropna()
                    tvals = pd.to_numeric(temp.iloc[3:, j], errors="coerce").dropna() if not temp.empty and j < temp.shape[1] else pd.Series(dtype=float)
                    if len(vals):
                        env_rows.append({
                            "location": str(loc).strip(),
                            "humidity_avg": float(vals.mean()),
                            "humidity_max": float(vals.max()),
                            "temperature_avg": float(tvals.mean()) if len(tvals) else np.nan,
                            "temperature_max": float(tvals.max()) if len(tvals) else np.nan,
                            "humidity_target": 60.0,
                            "temperature_target": 30.0,
                        })
            result["environment"] = pd.DataFrame(env_rows)
            result["sources"].append(("Humidity & Temperature", env))
        except Exception:
            pass

    # ---------- Unit 1 / 5 PF & Demand ----------
    unit = find_file(["Unit_-1_and_5_daily_Tata_Power_Systems_LTD_17-Aug-26.xlsx"])
    if unit:
        try:
            pf = read_sheet(unit, "PF & Demand", header=None)
            # Search all cells for the known PF / demand columns and collect numeric time-series rows.
            records = []
            for i in range(4, len(pf)):
                row = pf.iloc[i]
                for j, value in enumerate(row):
                    if isinstance(value, (int, float, np.number)) and pd.notna(value):
                        # Store raw numeric values for a simple technical view.
                        records.append({"row": i, "column": j, "value": float(value)})
            result["pf"] = pd.DataFrame(records)
            result["sources"].append(("Unit 1 & Unit 5", unit))
        except Exception:
            pass

    return result
def load_uploaded_master_data():
    """
    Load the most recently uploaded Excel workbook and map
    its worksheets into the application's existing data model.
    """

    result = {
        "energy": pd.DataFrame(),
        "transformers": pd.DataFrame(),
        "solar": pd.DataFrame(),
        "air": pd.DataFrame(),
        "environment": pd.DataFrame(),
        "pf": pd.DataFrame(),
        "sources": [],
        "energy_history": pd.DataFrame(),
    }

    uploaded_files = get_uploaded_files()

    uploaded_data_files = [
        filename
        for filename in uploaded_files
        if str(filename).lower().endswith((".csv", ".xlsx", ".xls"))
    ]

    if not uploaded_data_files:
        return None

    # Build the dashboard model from every saved upload. The uploader can
    # produce CSV exports whose wide date layout is the source of truth for
    # grid, Hexa/Vega, and transformer readings.
    csv_energy_rows = []
    csv_transformer_rows = []
    csv_solar_rows = []
    csv_air_rows = []
    csv_history_rows = []

    for saved_filename in uploaded_data_files:
        saved_path = UPLOAD_DIR / saved_filename
        result["sources"].append(("Uploaded File", saved_filename))

        if not saved_filename.lower().endswith(".csv"):
            continue

        try:
            raw_csv = pd.read_csv(saved_path, header=0)
        except Exception:
            continue

        utility_column = next(
            (
                column for column in raw_csv.columns
                if str(column).strip().lower() in {"utility", "utility_name", "source"}
            ),
            None,
        )
        total_air_column = next(
            (
                column for column in raw_csv.columns
                if str(column).strip().lower() in {"total_m3", "total_m3_per_day", "total_flow_m3"}
            ),
            None,
        )
        if utility_column is not None and total_air_column is not None:
            average_air_column = next(
                (
                    column for column in raw_csv.columns
                    if str(column).strip().lower() in {"avg_flow_m3_hr", "average_flow_m3_hr", "avg_flow"}
                ),
                None,
            )
            air_rows = pd.DataFrame(
                {
                    "utility": raw_csv[utility_column].astype(str).str.strip(),
                    "avg_flow_m3_hr": (
                        pd.to_numeric(raw_csv[average_air_column], errors="coerce")
                        if average_air_column is not None else np.nan
                    ),
                    "total_m3": pd.to_numeric(
                        raw_csv[total_air_column].astype(str).str.replace(",", "", regex=False),
                        errors="coerce",
                    ),
                }
            )
            csv_air_rows.append(air_rows.dropna(subset=["utility", "total_m3"]))
            continue

        solar_layout = False
        location_column = next(
            (
                column
                for column in raw_csv.columns
                if str(column).strip().lower() in {"locations", "location"}
            ),
            None,
        )
        if location_column is None:
            try:
                raw_csv = pd.read_csv(saved_path, header=2)
                location_column = next(
                    (
                        column
                        for column in raw_csv.columns
                        if str(column).strip().lower()
                        in {"locations", "location"}
                    ),
                    None,
                )
                solar_layout = location_column is not None
            except Exception:
                continue

        date_columns = []
        for column in raw_csv.columns:
            parsed_date = pd.to_datetime(
                str(column),
                format="%d-%b-%y" if solar_layout else "%d/%m/%Y",
                errors="coerce",
            )
            numeric_values = pd.to_numeric(
                raw_csv[column].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
            if pd.notna(parsed_date) and numeric_values.notna().sum() > 1:
                date_columns.append((column, parsed_date, numeric_values))

        if solar_layout and date_columns:
            _, _, latest_values = max(
                date_columns,
                key=lambda item: (item[2].notna().sum(), item[1]),
            )
            total_column = next(
                (
                    column
                    for column in raw_csv.columns
                    if str(column).strip().lower() in {"total", "mtd", "month to date"}
                ),
                None,
            )
            total_values = (
                pd.to_numeric(raw_csv[total_column], errors="coerce")
                if total_column is not None
                else pd.Series(np.nan, index=raw_csv.index)
            )
            solar_rows = pd.DataFrame(
                {
                    "source": raw_csv[location_column].astype(str).str.strip(),
                    "daily_kwh": latest_values,
                    "mtd_kwh": total_values,
                }
            )
            csv_solar_rows.append(
                solar_rows[
                    solar_rows["source"].str.lower().ne("total")
                    & solar_rows["daily_kwh"].notna()
                ]
            )
            continue

        if not date_columns:
            # Solar exports have metadata rows before their actual header.
            try:
                solar_csv = pd.read_csv(saved_path, header=2)
                location_column = next(
                    (
                        column
                        for column in solar_csv.columns
                        if str(column).strip().lower() in {"locations", "location"}
                    ),
                    None,
                )
                solar_dates = []
                for column in solar_csv.columns:
                    parsed_date = pd.to_datetime(
                        str(column), format="%d-%b-%y", errors="coerce"
                    )
                    values = pd.to_numeric(
                        solar_csv[column], errors="coerce"
                    )
                    if pd.notna(parsed_date) and values.notna().sum() > 1:
                        solar_dates.append((column, parsed_date, values))

                if location_column is not None and solar_dates:
                    latest_column, _, latest_values = max(
                        solar_dates, key=lambda item: item[1]
                    )
                    total_column = next(
                        (
                            column
                            for column in solar_csv.columns
                            if str(column).strip().lower() in {"total", "mtd", "month to date"}
                        ),
                        None,
                    )
                    total_values = (
                        pd.to_numeric(solar_csv[total_column], errors="coerce")
                        if total_column is not None
                        else pd.Series(np.nan, index=solar_csv.index)
                    )
                    solar_rows = pd.DataFrame(
                        {
                            "source": solar_csv[location_column].astype(str).str.strip(),
                            "daily_kwh": latest_values,
                            "mtd_kwh": total_values,
                        }
                    )
                    csv_solar_rows.append(
                        solar_rows[
                            solar_rows["source"].str.lower().ne("total")
                            & solar_rows["daily_kwh"].notna()
                        ]
                    )
            except (StopIteration, ValueError, TypeError):
                pass
            continue

        latest_column, latest_date, latest_values = max(
            date_columns,
            key=lambda item: (item[2].notna().sum(), item[1]),
        )
        locations = raw_csv[location_column].astype(str).str.strip()
        total_column = next(
            (
                column
                for column in raw_csv.columns
                if str(column).strip().lower() in {"total", "mtd", "month to date"}
            ),
            None,
        )
        total_values = (
            pd.to_numeric(raw_csv[total_column], errors="coerce")
            if total_column is not None
            else pd.Series(np.nan, index=raw_csv.index)
        )
        valid_rows = pd.DataFrame(
            {
                "location": locations,
                "daily_kwh": latest_values,
                "mtd_kwh": total_values,
            }
        )
        valid_rows = valid_rows[
            valid_rows["location"].str.lower().ne("total")
            & valid_rows["daily_kwh"].notna()
        ]
        if valid_rows.empty:
            continue

        csv_energy_rows.append(valid_rows)
        history_rows = pd.DataFrame(
            {
                "date": latest_date,
                "location": locations,
                "kwh": latest_values,
            }
        )
        csv_history_rows.append(
            history_rows[
                history_rows["location"].str.lower().ne("total")
                & history_rows["kwh"].notna()
            ]
        )
        transformer_rows = valid_rows[
            valid_rows["location"].str.contains("transformer", case=False, na=False)
        ].copy()
        if not transformer_rows.empty:
            transformer_rows = transformer_rows.rename(
                columns={"location": "transformer"}
            )
            transformer_rows["sensor_id"] = np.nan
            transformer_rows["loading_percent"] = np.nan
            transformer_rows["health_indicator"] = np.nan
            transformer_rows["mtd_kwh"] = np.nan
            csv_transformer_rows.append(transformer_rows)

    if csv_energy_rows or csv_solar_rows or csv_air_rows:
        if csv_energy_rows:
            energy_df = pd.concat(csv_energy_rows, ignore_index=True)
            if "mtd_kwh" in energy_df.columns:
                result["energy"] = (
                    energy_df.groupby("location", as_index=False)
                    .agg(
                        daily_kwh=("daily_kwh", "sum"),
                        mtd_kwh=("mtd_kwh", "max"),
                    )
                )
            else:
                result["energy"] = (
                    energy_df.groupby("location", as_index=False)["daily_kwh"]
                    .sum()
                    .assign(mtd_kwh=np.nan)
                )
        if csv_transformer_rows:
            result["transformers"] = pd.concat(
                csv_transformer_rows, ignore_index=True
            )
        if csv_solar_rows:
            result["solar"] = pd.concat(
                csv_solar_rows, ignore_index=True
            )
        if csv_air_rows:
            result["air"] = pd.concat(csv_air_rows, ignore_index=True)
        if csv_history_rows:
            result["energy_history"] = pd.concat(
                csv_history_rows, ignore_index=True
            )
        return result

    active_workbook = st.session_state.get(
        "active_workbook"
    )

    if not active_workbook:
        active_file_path = DATA_DIR / "active_workbook.txt"

        if active_file_path.exists():
            active_workbook = (
                active_file_path
                .read_text()
                .strip()
            )

    if active_workbook in uploaded_data_files:
        filename = active_workbook
    else:
        filename = uploaded_data_files[-1]

    # Some uploaded solar reports are exported as CSV with metadata rows
    # before the actual table header. Convert that wide report into the
    # normalized solar frame used by the Command Center.
    if filename.lower().endswith(".csv"):
        try:
            csv_path = UPLOAD_DIR / filename
            csv_data = pd.read_csv(csv_path, header=2)
            location_column = next(
                (
                    column
                    for column in csv_data.columns
                    if str(column).strip().lower() in {"locations", "location"}
                ),
                None,
            )
            date_columns = []
            for column in csv_data.columns:
                parsed_date = pd.to_datetime(
                    str(column), format="%d-%b-%y", errors="coerce"
                )
                numeric_count = pd.to_numeric(
                    csv_data[column], errors="coerce"
                ).notna().sum()
                if pd.notna(parsed_date) and numeric_count > 1:
                    date_columns.append((column, parsed_date))

            if location_column is None or not date_columns:
                return None

            latest_column, latest_date = max(
                date_columns, key=lambda item: item[1]
            )
            solar_rows = pd.DataFrame(
                {
                    "source": csv_data[location_column].astype(str).str.strip(),
                    "daily_kwh": pd.to_numeric(
                        csv_data[latest_column], errors="coerce"
                    ),
                }
            )
            total_column = next(
                (
                    column
                    for column in csv_data.columns
                    if str(column).strip().lower() == "total"
                ),
                None,
            )
            solar_rows["mtd_kwh"] = (
                pd.to_numeric(csv_data[total_column], errors="coerce")
                if total_column is not None
                else np.nan
            )
            solar_rows = solar_rows[
                solar_rows["source"].str.lower().ne("total")
                & solar_rows["daily_kwh"].notna()
            ]

            if solar_rows.empty:
                return None

            result["solar"] = solar_rows.reset_index(drop=True)
            result["sources"].append(("Uploaded Solar CSV", filename))
            return result
        except Exception as e:
            st.error(
                f"UPLOADED CSV ERROR: {type(e).__name__}: {e}"
            )
            return None

    try:

        workbook = load_saved_workbook(
            filename
        )

    except Exception as e:

        st.error(
            f"MASTER WORKBOOK ERROR: "
            f"{type(e).__name__}: {e}"
        )

        return None

    if not workbook:
        return None
    # =========================================================
    # ELECTRICAL METERS → ENERGY
    # =========================================================

    electrical = workbook.get("Electrical_Meters")

    if (
        isinstance(electrical, pd.DataFrame)
        and not electrical.empty
    ):

        electrical = electrical.copy()

        if "date" in electrical.columns:
            electrical["date"] = pd.to_datetime(
                electrical["date"],
                errors="coerce"
            )

        if "kwh" in electrical.columns:
            electrical["kwh"] = pd.to_numeric(
                electrical["kwh"],
                errors="coerce"
            )

        if (
            "date" in electrical.columns
            and "location" in electrical.columns
            and "kwh" in electrical.columns
        ):

            valid = electrical.dropna(
                subset=[
                    "date",
                    "location",
                    "kwh"
                ]
            ).copy()

            if not valid.empty:

                latest_date = valid["date"].max()

                latest = valid[
                    valid["date"] == latest_date
                ].copy()

                energy_rows = (
                    latest[
                        [
                            "location",
                            "kwh"
                        ]
                    ]
                    .groupby(
                        "location",
                        as_index=False
                    )
                    .sum()
                )

                energy_rows = energy_rows.rename(
                    columns={
                        "kwh": "daily_kwh"
                    }
                )

                energy_rows["mtd_kwh"] = np.nan

                result["energy"] = energy_rows

                # -------------------------------------------------
                # DAILY ENERGY HISTORY
                # -------------------------------------------------

                history = (
                    valid[
                        [
                            "date",
                            "location",
                            "kwh"
                        ]
                    ]
                    .groupby(
                        [
                            "date",
                            "location"
                        ],
                        as_index=False
                    )
                    .sum()
                )

                history = history.rename(
                    columns={
                        "kwh": "kwh"
                    }
                )

                result["energy_history"] = history

    # =========================================================
    # SOLAR
    # =========================================================

    solar = workbook.get("Solar")

    if (
        isinstance(solar, pd.DataFrame)
        and not solar.empty
    ):

        solar = solar.copy()

        if "date" in solar.columns:
            solar["date"] = pd.to_datetime(
                solar["date"],
                errors="coerce"
            )

        if "daily_kwh" in solar.columns:
            solar["daily_kwh"] = pd.to_numeric(
                solar["daily_kwh"],
                errors="coerce"
            )

        required = [
            "date",
            "source",
            "daily_kwh"
        ]

        if all(
            column in solar.columns
            for column in required
        ):

            valid_solar = solar.dropna(
                subset=required
            ).copy()

            if not valid_solar.empty:

                latest_date = valid_solar["date"].max()

                latest_solar = valid_solar[
                    valid_solar["date"] == latest_date
                ].copy()

                solar_rows = (
                    latest_solar[
                        [
                            "source",
                            "daily_kwh"
                        ]
                    ]
                    .groupby(
                        "source",
                        as_index=False
                    )
                    .sum()
                )

                solar_rows["mtd_kwh"] = np.nan

                result["solar"] = solar_rows

    # =========================================================
    # TRANSFORMERS
    # =========================================================

    transformers = workbook.get("Transformers")

    if (
        isinstance(transformers, pd.DataFrame)
        and not transformers.empty
    ):

        transformers = transformers.copy()

        if "date" in transformers.columns:
            transformers["date"] = pd.to_datetime(
                transformers["date"],
                errors="coerce"
            )

        if "daily_kwh" in transformers.columns:
            transformers["daily_kwh"] = pd.to_numeric(
                transformers["daily_kwh"],
                errors="coerce"
            )

        if (
            "date" in transformers.columns
            and "transformer" in transformers.columns
            and "daily_kwh" in transformers.columns
        ):

            valid_tr = transformers.dropna(
                subset=[
                    "date",
                    "transformer",
                    "daily_kwh"
                ]
            ).copy()

            if not valid_tr.empty:

                latest_date = valid_tr["date"].max()

                latest_tr = valid_tr[
                    valid_tr["date"] == latest_date
                ].copy()

                tr_rows = latest_tr[
                    [
                        "transformer",
                        "sensor_id",
                        "daily_kwh"
                    ]
                ].copy()

                if "loading_percent" in latest_tr.columns:
                    tr_rows["loading_percent"] = (
                        pd.to_numeric(
                            latest_tr[
                                "loading_percent"
                            ],
                            errors="coerce"
                        )
                    )
                else:
                    tr_rows["loading_percent"] = np.nan

                if "health_indicator" in latest_tr.columns:
                    tr_rows["health_indicator"] = (
                        pd.to_numeric(
                            latest_tr[
                                "health_indicator"
                            ],
                            errors="coerce"
                        )
                    )
                else:
                    tr_rows["health_indicator"] = np.nan

                tr_rows["mtd_kwh"] = np.nan

                result["transformers"] = tr_rows

    # =========================================================
    # COMPRESSED AIR → UTILITIES
    # =========================================================

    air = workbook.get("Compressed_Air")

    if (
        isinstance(air, pd.DataFrame)
        and not air.empty
    ):

        air = air.copy()

        if "date" in air.columns:
            air["date"] = pd.to_datetime(
                air["date"],
                errors="coerce"
            )

        if "date" in air.columns:

            latest_date = air["date"].max()

            latest_air = air[
                air["date"] == latest_date
            ].copy()

            if not latest_air.empty:

                utility_rows = []

                for column in [
                    "pure_air_m3",
                    "fad___module_line_m3",
                    "fad___cell_line_m3",
                ]:

                    if column not in latest_air.columns:
                        continue

                    value = pd.to_numeric(
                        latest_air[column],
                        errors="coerce"
                    ).sum()

                    utility_rows.append(
                        {
                            "utility": column,
                            "avg_flow_m3_hr": np.nan,
                            "total_m3": value,
                        }
                    )

                result["air"] = pd.DataFrame(
                    utility_rows
                )

    # =========================================================
    # ENVIRONMENT
    # =========================================================

    environment = workbook.get("Environment")

    if (
        isinstance(environment, pd.DataFrame)
        and not environment.empty
    ):

        environment = environment.copy()

        if "timestamp" in environment.columns:
            environment["timestamp"] = pd.to_datetime(
                environment["timestamp"],
                errors="coerce"
            )

        if "humidity_percent" in environment.columns:
            environment["humidity_percent"] = pd.to_numeric(
                environment["humidity_percent"],
                errors="coerce"
            )

        if "temperature_c" in environment.columns:
            environment["temperature_c"] = pd.to_numeric(
                environment["temperature_c"],
                errors="coerce"
            )

        if "location" in environment.columns:

            grouped_rows = []

            for location, group in environment.groupby(
                "location"
            ):

                grouped_rows.append(
                    {
                        "location": str(location),

                        "humidity_avg": (
                            float(
                                group[
                                    "humidity_percent"
                                ].mean()
                            )
                            if "humidity_percent"
                            in group.columns
                            else np.nan
                        ),

                        "humidity_max": (
                            float(
                                group[
                                    "humidity_percent"
                                ].max()
                            )
                            if "humidity_percent"
                            in group.columns
                            else np.nan
                        ),

                        "temperature_avg": (
                            float(
                                group[
                                    "temperature_c"
                                ].mean()
                            )
                            if "temperature_c"
                            in group.columns
                            else np.nan
                        ),

                        "temperature_max": (
                            float(
                                group[
                                    "temperature_c"
                                ].max()
                            )
                            if "temperature_c"
                            in group.columns
                            else np.nan
                        ),

                        "humidity_target": 60.0,
                        "temperature_target": 30.0,
                    }
                )

            result["environment"] = pd.DataFrame(
                grouped_rows
            )

    # =========================================================
    # SOURCE INFORMATION
    # =========================================================

    result["sources"].append(
        (
            "Uploaded Master Workbook",
            filename
        )
    )

    return result

def load_dashboard_data():
    """Read operational panels from PostgreSQL without a static-file fallback."""
    try:
        snapshot = load_dashboard_tables()
        snapshot["data_source"] = "PostgreSQL dashboard tables"
        return snapshot
    except Exception as exc:
        st.warning(
            "PostgreSQL dashboard data is currently unavailable. "
            f"Check DATABASE_URL or DB_* settings. ({exc})"
        )
        return empty_dashboard_tables()


data = load_dashboard_data()

# -----------------------------
# Login System
# -----------------------------
# ============================================================
# COMMON PLATFORM LOGIN SYSTEM
# ============================================================

from services.login_service import (
    authenticate_user,
    get_login_options,
    get_user_applications,
)


# Initialize login session state
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user_role" not in st.session_state:
    st.session_state.user_role = None

if "username" not in st.session_state:
    st.session_state.username = None

if "user_full_name" not in st.session_state:
    st.session_state.user_full_name = None

if "user_applications" not in st.session_state:
    st.session_state.user_applications = []


# ------------------------------------------------------------
# LOGIN PAGE
# ------------------------------------------------------------

if not st.session_state.logged_in:

    st.markdown(
        """
        <style>
        .login-title {
            text-align: center;
            font-size: 42px;
            font-weight: 700;
            margin-top: 80px;
        }

        .login-subtitle {
            text-align: center;
            color: #888888;
            font-size: 18px;
            margin-bottom: 40px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="login-title">⚡ Utility Intelligence Platform</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="login-subtitle">'
        'Common Enterprise Login'
        '</div>',
        unsafe_allow_html=True
    )

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        try:
            login_options = get_login_options()
        except Exception:
            login_options = {"plants": [], "locations": [], "user_types": []}

        if not all(login_options.values()):
            st.error("Login options could not be loaded from PostgreSQL. Please contact an administrator.")
            st.stop()

        with st.form("common_login_form"):

            username = st.text_input(
                "User ID",
                placeholder="Enter your User ID"
            )

            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password"
            )

            plant = st.selectbox("Plant", login_options["plants"])

            location = st.selectbox("Location", login_options["locations"])

            user_type = st.selectbox("User Type", login_options["user_types"])

            login_button = st.form_submit_button(
                "🔐 Login",
                use_container_width=True
            )

        if login_button:

            if not username or not password:
                st.error("Please enter User ID and Password.")

            else:

                try:

                    user = authenticate_user(
                        username.strip(),
                        password,
                        plant,
                        location,
                        user_type,
                    )

                    if not user:
                        st.error(
                            "Invalid User ID, Password, Plant, Location, or User Type."
                        )
                        st.stop()

                    applications = get_user_applications(username.strip())
                    if not applications and str(user["user_type"]).upper() != "ADMIN":
                        st.error("No active applications are assigned to this account.")
                        st.stop()

                    st.session_state.logged_in = True
                    st.session_state.username = user["username"]
                    st.session_state.user_full_name = user["full_name"]
                    st.session_state.user_role = user["user_type"]
                    st.session_state.plant = user["plant_name"]
                    st.session_state.location = user["location_name"]
                    st.session_state.user_applications = applications

                    st.rerun()

                except Exception as e:
                    st.error(f"Login system error: {str(e)}")

    st.stop()


# ============================================================
# USER IS LOGGED IN
# ============================================================

# ============================================================
# ADMIN CONFIGURATION
# ============================================================

if (
    st.session_state.user_role == "ADMIN"
    and st.session_state.get("active_application", "Admin Control Center")
    == "Admin Control Center"
):

    with st.sidebar.expander("⚙️ Admin", expanded=False):

        st.markdown("### Application Settings")

        app_config = get_app_config()
        try:
            admin_options = get_login_options()
        except Exception:
            admin_options = {"plants": [], "locations": []}
        plant_options = admin_options.get("plants", [])
        location_options = admin_options.get("locations", [])

        if location_options and st.session_state.get("selected_location") not in location_options:
            st.session_state.selected_location = location_options[0]
        if plant_options and st.session_state.get("selected_plant") not in plant_options:
            st.session_state.selected_plant = plant_options[0]
        if "selected_line" not in st.session_state:
            st.session_state.selected_line = "None"

        if not location_options or not plant_options:
            st.warning("Plant and location options are unavailable from PostgreSQL.")
            st.stop()

        selected_location = st.selectbox("Location", location_options, key="selected_location")

        selected_plant = st.selectbox("Plant", plant_options, key="selected_plant")

        selected_line = st.selectbox(
            "Line",
            ["None", "Vega", "Hexa"],
            index=0,
            key="selected_line",
        )

        ai_enabled = st.toggle(
            "Enable AI Agent",
            value=app_config.get("ai_enabled", True),
        )

        daily_reports_enabled = st.toggle(
            "Enable Daily Reports",
            value=app_config.get("daily_reports_enabled", True),
        )

        monthly_reports_enabled = st.toggle(
            "Enable Monthly Reports",
            value=app_config.get("monthly_reports_enabled", True),
        )

        data_upload_enabled = st.toggle(
            "Enable Data Upload",
            value=app_config.get("data_upload_enabled", True),
        )

        user_registration_enabled = st.toggle(
            "Enable User Registration",
            value=app_config.get("user_registration_enabled", True),
        )

        alert_threshold = st.number_input(
            "Alert Threshold",
            min_value=0.0,
            max_value=100.0,
            value=float(app_config.get("alert_threshold", 80.0)),
            step=1.0,
        )

        if st.button(
            "💾 Save Configuration",
            use_container_width=True
        ):

            update_config(
                "ai_enabled",
                str(ai_enabled).lower()
            )

            update_config(
                "daily_reports_enabled",
                str(daily_reports_enabled).lower()
            )

            update_config(
                "monthly_reports_enabled",
                str(monthly_reports_enabled).lower()
            )

            update_config(
                "data_upload_enabled",
                str(data_upload_enabled).lower()
            )

            update_config(
                "user_registration_enabled",
                str(user_registration_enabled).lower()
            )

            update_config(
                "alert_threshold",
                str(alert_threshold)
            )

            update_config(
                "selected_location",
                selected_location
            )

            update_config(
                "selected_plant",
                selected_plant
            )

            update_config(
                "selected_line",
                selected_line
            )

            st.success(
                "✅ Admin configuration saved successfully."
            )

            st.rerun()


# -----------------------------

# -----------------------------
# Enterprise application navigation
# -----------------------------

st.sidebar.markdown("## ⚡ Utility Intelligence")
st.sidebar.caption("Solar Asset Management")

assigned_codes = {
    str(row[6]).strip().upper()
    for row in st.session_state.get("user_applications", [])
    if len(row) > 6 and row[6]
}
is_admin = str(st.session_state.get("user_role", "")).upper() == "ADMIN"

application_options = []
if "UTILITY" in assigned_codes:
    application_options.append("Utility")
if "SIMULATION" in assigned_codes:
    application_options.append("Simulation")
if "EL_DATA" in assigned_codes:
    application_options.append("EL Data")

if not application_options and not is_admin:
    st.sidebar.warning("No applications are assigned to this account.")
    st.stop()

default_application = application_options[0] if application_options else "Admin Control Center"
application_selector_options = (
    ["Admin Control Center"] if is_admin else []
) + application_options
if "active_application" not in st.session_state:
    st.session_state.active_application = (
        "Admin Control Center" if is_admin else default_application
    )
if st.session_state.active_application not in application_selector_options:
    st.session_state.active_application = "Admin Control Center" if is_admin else default_application
if "application_selector" not in st.session_state:
    st.session_state.application_selector = st.session_state.active_application
if st.session_state.application_selector not in application_selector_options:
    st.session_state.application_selector = st.session_state.active_application


def select_application() -> None:
    st.session_state.active_application = st.session_state.application_selector


if is_admin and st.session_state.get("active_application") == "Admin Control Center":
    st.sidebar.markdown("### ADMIN")
    st.sidebar.caption("Use the application selector below to switch context.")

st.sidebar.markdown("### APPLICATIONS")
if application_selector_options:
    st.sidebar.radio(
        "Application context",
        application_selector_options,
        format_func=lambda value: f"▣ {value}",
        label_visibility="collapsed",
        key="application_selector",
        on_change=select_application,
    )
else:
    st.sidebar.caption("No operational applications are assigned to this account.")
selected_application = st.session_state.get("application_selector", default_application)
st.session_state.active_application = selected_application
if selected_application == "Admin Control Center":
    st.session_state.active_application = "Admin Control Center"
    render_admin_control_center()
    st.sidebar.divider()
    st.sidebar.markdown(
        f"**Signed in as**\n\n{st.session_state.get('user_full_name', 'Authenticated user')}"
    )
    if st.sidebar.button("Sign out", use_container_width=True):
        sign_out()
    st.stop()

if selected_application == "Simulation":
    page = "Simulation"
elif selected_application == "EL Data":
    page = "EL Data"
elif selected_application == "Utility":
    utility_pages = [
        "Command Center",
        "Energy",
        "Solar",
        "Hexa & Vega",
        "Transformers",
        "Utilities",
        "Environment",
        "Electrical Quality",
        "Alerts & Anomalies",
        "Intelligent Insights",
        "Daily Report",
        "Management Reports",
        "Data Upload",
        "Data Sources",
        "AI Assistant",
    ]
    if "command_center_navigation" not in st.session_state:
        st.session_state.command_center_navigation = "Command Center"
    page = st.sidebar.radio(
        "Utility Navigation",
        utility_pages,
        label_visibility="collapsed",
        key="command_center_navigation",
    )
    with st.sidebar.expander("Configured Utilities", expanded=True):
        try:
            configured_utilities = get_utilities()
        except Exception:
            configured_utilities = pd.DataFrame()
        if configured_utilities.empty:
            st.caption("No utilities configured yet.")
        else:
            for _, utility in configured_utilities.iterrows():
                utility_name = str(utility.get("name") or "Unnamed utility")
                utility_type = str(utility.get("type") or "Utility")
                st.markdown(f"**{utility_name}**  \n{utility_type}")
else:
    st.error("The selected application is not available for this account.")
    st.stop()

st.sidebar.divider()
st.sidebar.markdown(
    f"**Signed in as**\n\n{st.session_state.get('user_full_name', 'Authenticated user')}"
)
if st.sidebar.button("Sign out", use_container_width=True):
    sign_out()

st.sidebar.markdown(
    """
    <div style="
        margin-top: 18px;
        padding: 10px 12px;
        border-radius: 10px;
        background: rgba(255,255,255,0.07);
        border: 1px solid rgba(255,255,255,0.10);
        font-size: 11px;
        color: #CBD5E1;
    ">
        <div style="
            color: #67E8F9;
            font-weight: 700;
            margin-bottom: 3px;
        ">
            ● SYSTEM ONLINE
        </div>

        Data → AI → Insights → Reports
    </div>
    """,
    unsafe_allow_html=True
)

st.sidebar.divider()
# -----------------------------
# Reporting Period
# -----------------------------

import datetime as dt

st.sidebar.subheader("📅 Reporting Period")

period_option = st.sidebar.selectbox(
    "Quick Select",
    [
        "Today",
        "Last 7 Days",
        "Month to Date",
        "Custom"
    ]
)

def latest_data_date(dataset):
    dates = []
    for dataframe in dataset.values():
        if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
            continue
        for column in ("date", "datetime", "timestamp", "log_date"):
            if column in dataframe.columns:
                parsed = pd.to_datetime(dataframe[column], errors="coerce").dropna()
                if not parsed.empty:
                    dates.append(parsed.max().date())
    return max(dates) if dates else None


data_end_date = latest_data_date(data) or dt.date.today()

if period_option == "Today":

    start_date = data_end_date
    end_date = data_end_date

elif period_option == "Last 7 Days":

    start_date = data_end_date - dt.timedelta(days=6)
    end_date = data_end_date

elif period_option == "Month to Date":

    start_date = data_end_date.replace(day=1)
    end_date = data_end_date

else:

    start_date = st.sidebar.date_input(
        "Start Date",
        value=dt.date(2026, 8, 1)
    )

    end_date = st.sidebar.date_input(
        "End Date",
        value=data_end_date
    )

if start_date > end_date:
    st.sidebar.error("Start date cannot be after end date.")
else:
    st.sidebar.success(
        f"{start_date.strftime('%d %b %Y')} → "
        f"{end_date.strftime('%d %b %Y')}"
    )
st.sidebar.caption("Operational data is loaded from PostgreSQL.")

if page == "Simulation":
    st.title("Simulation")
    st.caption("Simulation application")
    st.info("The Simulation application is available to this account through PostgreSQL application access.")
    st.stop()

if page == "EL Data":
    st.title("EL Data")
    st.caption("EL Data application")
    st.info("The EL Data application is available to this account through PostgreSQL application access.")
    st.stop()

# -----------------------------
# Common calculations
# -----------------------------
energy = data["energy"].copy()
solar_df = data["solar"].copy()
tr_df = data["transformers"].copy()
air_df = data["air"].copy()
env_df = data["environment"].copy()

def find_energy_value(keyword):
    if energy.empty:
        return np.nan

    if "location" not in energy.columns:
        return np.nan

    if "daily_kwh" not in energy.columns:
        return np.nan

    m = energy[
        energy["location"]
        .astype(str)
        .str.lower()
        .str.contains(
            keyword.lower(),
            na=False
        )
    ]

    return (
        float(m["daily_kwh"].sum())
        if not m.empty
        else np.nan
    )
grid = find_energy_value("66kv")
hexa = find_energy_value("hexa")
vega = find_energy_value("vega")
transformer_total = float(tr_df["daily_kwh"].sum()) if not tr_df.empty else np.nan
solar_total = float(solar_df["daily_kwh"].sum()) if not solar_df.empty else np.nan
air_total = float(air_df["total_m3"].sum()) if not air_df.empty else np.nan

# If solar generation is the active upload focus, keep the dashboard strictly solar-only
# and suppress all unrelated utility metrics as N/A.
source_names = [str(item).lower() for item in data.get("sources", [])]
solar_focus_mode = any("solar generation" in name for name in source_names)
if solar_focus_mode:
    grid = np.nan
    hexa = np.nan
    vega = np.nan
    transformer_total = np.nan
    air_total = np.nan

# Fixed thresholds based on project specification
HUMIDITY_TARGET = 60.0
TEMP_TARGET = 30.0
PF_TARGET = 0.90

def make_alerts():
    alerts = []

    if not env_df.empty:
        for _, r in env_df.iterrows():
            if pd.notna(r.get("humidity_avg")) and r["humidity_avg"] > HUMIDITY_TARGET:
                diff = r["humidity_avg"] - HUMIDITY_TARGET
                sev = "High" if diff >= 10 else "Medium"
                alerts.append({
                    "severity": sev,
                    "type": "Environment",
                    "title": "Humidity Above Target",
                    "location": r["location"],
                    "actual": round(r["humidity_avg"], 2),
                    "target": HUMIDITY_TARGET,
                    "description": f"{r['location']} humidity is {r['humidity_avg']:.2f}% vs {HUMIDITY_TARGET:.0f}% target."
                })
            if pd.notna(r.get("temperature_avg")) and r["temperature_avg"] > TEMP_TARGET:
                alerts.append({
                    "severity": "Medium",
                    "type": "Environment",
                    "title": "Temperature Above Target",
                    "location": r["location"],
                    "actual": round(r["temperature_avg"], 2),
                    "target": TEMP_TARGET,
                    "description": f"{r['location']} temperature is {r['temperature_avg']:.2f}°C vs {TEMP_TARGET:.0f}°C target."
                })

    if not tr_df.empty:
        for _, r in tr_df.iterrows():
            if pd.notna(r["daily_kwh"]):
                # Flag unusually high transformer consumers for attention.
                if r["daily_kwh"] >= tr_df["daily_kwh"].quantile(0.75):
                    alerts.append({
                        "severity": "Medium",
                        "type": "Energy",
                        "title": "High Transformer Consumption",
                        "location": r["transformer"],
                        "actual": round(r["daily_kwh"], 2),
                        "target": None,
                        "description": f"{r['transformer']} is among the highest transformer consumers."
                    })

    return pd.DataFrame(alerts)

alerts_df = make_alerts()

# -----------------------------
# Header
# -----------------------------
st.markdown(
    "## Automated Utility Intelligence"
)

st.caption(
    "Enterprise Utility Operations & Daily Reporting Platform"
)
st.caption("Ingest → Store → Analyze → Visualize → Alert → Report → Insights")


def describe_weather_code(code):
    code = int(code) if str(code).isdigit() else 0
    mapping = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Freezing drizzle",
        57: "Heavy freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        80: "Rain showers",
        81: "Heavy rain showers",
        82: "Violent rain showers",
        85: "Snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Severe thunderstorm",
    }
    return mapping.get(code, "Variable conditions")


def fetch_weather_context(_location_name="Bangalore"):
    """Fetch the Bangalore daily weather context used to explain solar anomalies."""
    lat = 12.848611
    lon = 77.675556
    try:
        weather_url = (
            "https://api.open-meteo.com/v1/forecast?"
            + parse.urlencode({
                "latitude": lat,
                "longitude": lon,
                "daily": "weather_code,daylight_duration,sunshine_duration,rain_sum,temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "past_days": 1,
                "forecast_days": 0,
            })
        )
        with request.urlopen(weather_url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        daily = data.get("daily") or {}
        values = [
            {
                "date": daily.get("time", [None])[idx],
                "weather_code": daily.get("weather_code", [None])[idx],
                "daylight_duration": daily.get("daylight_duration", [None])[idx],
                "sunshine_duration": daily.get("sunshine_duration", [None])[idx],
                "rain_sum": daily.get("rain_sum", [None])[idx],
                "temperature_2m_max": daily.get("temperature_2m_max", [None])[idx],
                "temperature_2m_min": daily.get("temperature_2m_min", [None])[idx],
            }
            for idx in range(len(daily.get("time", [])))
        ]
        if not values:
            return {}

        latest = values[-1]
        return {
            "source": "open-meteo",
            "date": latest.get("date"),
            "conditions": describe_weather_code(latest.get("weather_code")),
            "daylight_duration_seconds": latest.get("daylight_duration"),
            "sunshine_duration_seconds": latest.get("sunshine_duration"),
            "rain_sum_mm": latest.get("rain_sum"),
            "temperature_c_max": latest.get("temperature_2m_max"),
            "temperature_c_min": latest.get("temperature_2m_min"),
            "temperature_c": latest.get("temperature_2m_max"),
            "precipitation_mm": latest.get("rain_sum"),
            "humidity_pct": None,
            "cloud_cover_pct": None,
        }
    except Exception:
        return {}


def classify_anomaly_risk(issue, weather_context=None):
    """Classify the anomaly as weather-driven, plant-side, or mixed review depending on context."""
    issue_text = (issue or "").lower()
    cond = (weather_context.get("conditions") if weather_context else "").lower()
    cloud_cover = weather_context.get("cloud_cover_pct") if weather_context else None

    weather_keywords = ["cloudy", "rain", "overcast", "fog", "storm", "mist"]
    plant_keywords = [
        "inverter", "communication", "string", "dc", "fault", "soiling",
        "shading", "module", "thermal", "cable", "disconnect", "reactive",
        "power factor"
    ]

    if cloud_cover is not None:
        try:
            cloud_cover = float(cloud_cover)
        except (TypeError, ValueError):
            cloud_cover = None

    if cloud_cover is not None and cloud_cover > 60:
        if any(keyword in issue_text for keyword in plant_keywords):
            return "Mixed / review"
        return "Weather-driven"

    if any(keyword in cond for keyword in weather_keywords):
        if any(keyword in issue_text for keyword in plant_keywords):
            return "Mixed / review"
        return "Weather-driven"

    if any(keyword in issue_text for keyword in plant_keywords):
        return "Plant-side likely"

    return "Mixed / review"


def render_risk_badge(risk):
    """Display a compact color-coded badge for anomaly risk."""
    risk = risk or "Mixed / review"
    palette = {
        "Weather-driven": {"bg": "#e8f5e9", "fg": "#1b5e20", "border": "#81c784"},
        "Plant-side likely": {"bg": "#fff3e0", "fg": "#e65100", "border": "#ffb74d"},
        "Mixed / review": {"bg": "#f3e5f5", "fg": "#6a1b9a", "border": "#ba68c8"},
    }
    colors = palette.get(risk, {"bg": "#f5f5f5", "fg": "#424242", "border": "#bdbdbd"})
    st.markdown(
        f"<span style='display:inline-block; padding:4px 10px; border-radius:999px; "
        f"background:{colors['bg']}; color:{colors['fg']}; border:1px solid {colors['border']}; "
        f"font-weight:600; font-size:0.82rem;'> {risk} </span>",
        unsafe_allow_html=True,
    )


def severity_cell_style(value):
    """Return HTML styling for a severity cell."""
    palette = {
        "High": {"bg": "#ffebee", "fg": "#b71c1c", "border": "#ef5350"},
        "Medium": {"bg": "#fff8e1", "fg": "#b45309", "border": "#fbbf24"},
        "Low": {"bg": "#e8f5e9", "fg": "#1b5e20", "border": "#66bb6a"},
    }
    colors = palette.get(str(value).strip().title(), {"bg": "#f5f5f5", "fg": "#424242", "border": "#bdbdbd"})
    return (
        f"background-color: {colors['bg']}; color: {colors['fg']}; "
        f"border: 1px solid {colors['border']}; font-weight: 600; padding: 4px 8px; border-radius: 999px;"
    )


def render_severity_badge(severity):
    """Render a compact severity badge for anomaly cards."""
    severity = str(severity or "Low").strip().title()
    palette = {
        "High": {"bg": "#fbe9e7", "fg": "#b71c1c", "border": "#ef5350"},
        "Medium": {"bg": "#fff8e1", "fg": "#b45309", "border": "#fbbf24"},
        "Low": {"bg": "#e8f5e9", "fg": "#1b5e20", "border": "#66bb6a"},
    }
    colors = palette.get(severity, {"bg": "#f5f5f5", "fg": "#424242", "border": "#bdbdbd"})
    st.markdown(
        f"<span style='display:inline-block; padding:4px 10px; border-radius:999px; "
        f"background:{colors['bg']}; color:{colors['fg']}; border:1px solid {colors['border']}; "
        f"font-weight:700; font-size:0.82rem;'> {severity} </span>",
        unsafe_allow_html=True,
    )


def build_solar_anomaly_report():
    """Analyze solar time-series data for abnormal generation and operation conditions."""
    weather_context = fetch_weather_context("Bangalore")
    weather_note = ""
    if weather_context:
        temp = weather_context.get("temperature_c")
        cloud = weather_context.get("cloud_cover_pct")
        precipitation = weather_context.get("precipitation_mm")
        conditions = weather_context.get("conditions")
        parts = [f"{conditions}"]
        if temp is not None:
            parts.append(f"{temp}°C")
        if cloud is not None:
            parts.append(f"cloud cover {cloud}%")
        if precipitation is not None:
            parts.append(f"precipitation {precipitation} mm")
        weather_note = " Weather context: " + ", ".join(parts) + "."

    df = read_solar_time_logs()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "location",
                "risk",
                "issue",
                "severity",
                "evidence",
                "root_cause",
                "recommended_action",
            ]
        )

    df = df.copy()
    df["log_timestamp"] = pd.to_datetime(
        df["log_date"].astype(str) + " " + df["log_timestamp"].astype(str),
        errors="coerce",
    )
    df["kwh"] = pd.to_numeric(df["kwh"], errors="coerce").fillna(0)
    df["power_factor"] = pd.to_numeric(df["power_factor"], errors="coerce")
    df["kw"] = pd.to_numeric(df["kw"], errors="coerce")
    df["kva"] = pd.to_numeric(df["kva"], errors="coerce")

    anomalies = []

    daylight = df[df["log_timestamp"].notna() & df["log_timestamp"].dt.hour.between(10, 15)]
    if not daylight.empty:
        zero_day = daylight[daylight["kwh"] <= 0]
        for location, group in zero_day.groupby("location_name", dropna=False):
            if group.empty:
                continue
            sample = group.sort_values("log_timestamp").head(3)
            evidence = "; ".join(
                f"{ts.strftime('%H:%M')}={val:.2f}kWh"
                for ts, val in zip(sample["log_timestamp"], sample["kwh"])
            )
            weather_root = "Soiling, shading, inverter trip, or DC string faults are the primary suspects."
            if weather_context and weather_context.get("cloud_cover_pct") not in (None, ""):
                cloud_cover = float(weather_context.get("cloud_cover_pct") or 0)
                if cloud_cover > 70:
                    weather_root = "Persistent cloud cover and low irradiance can suppress output during the day, so the generation drop may be weather-driven or coupled with a plant-side issue."
            issue_name = "Sudden generation drop / zero output during daylight"
            anomalies.append({
                "location": location or "Unknown",
                "risk": classify_anomaly_risk(issue_name, weather_context),
                "issue": issue_name,
                "severity": "High",
                "evidence": evidence,
                "root_cause": weather_root + weather_note,
                "recommended_action": "Check irradiance conditions, clean modules, inspect inverter alarms, and verify DC voltage/current and connector integrity before escalating maintenance.",
            })

    low_pf = df[df["power_factor"].notna() & (df["power_factor"] < 0.8)]
    for location, group in low_pf.groupby("location_name", dropna=False):
        sample = group.sort_values("log_timestamp").head(3)
        evidence = "; ".join(
            f"{ts.strftime('%H:%M')} PF={pf:.2f}"
            for ts, pf in zip(sample["log_timestamp"], sample["power_factor"])
        )
        root_cause = "Reactive power instability, inverter PF regulation issue, cable/connection problems, or abnormal operating conditions near the inverter."
        if weather_context and weather_context.get("temperature_c") is not None:
            temp = float(weather_context.get("temperature_c") or 0)
            if temp > 33:
                root_cause = "High ambient temperature and elevated inverter loading could be reducing PF while the system remains close to thermal or operational limits."
        issue_name = "Low power factor / reactive power imbalance"
        anomalies.append({
            "location": location or "Unknown",
            "risk": classify_anomaly_risk(issue_name, weather_context),
            "issue": issue_name,
            "severity": "Medium",
            "evidence": evidence,
            "root_cause": root_cause + weather_note,
            "recommended_action": "Review inverter PF settings, inspect capacitor/filter health, and verify AC/DC side cable integrity and terminal tightness.",
        })

    stale = []
    for location, group in df.groupby("location_name", dropna=False):
        group = group.sort_values("log_timestamp")
        group["gap_hours"] = group["log_timestamp"].diff().dt.total_seconds() / 3600
        if group["gap_hours"].max() is pd.NaT:
            continue
        if pd.notna(group["gap_hours"].max()) and group["gap_hours"].max() > 4:
            stale.append((location, group["gap_hours"].max()))
    for location, gap in stale:
        issue_name = "Inverter communication loss / stale timestamps"
        anomalies.append({
            "location": location or "Unknown",
            "risk": classify_anomaly_risk(issue_name, weather_context),
            "issue": issue_name,
            "severity": "High",
            "evidence": f"Largest timestamp gap: {gap:.1f} hours",
            "root_cause": "Communication interruption, logger outage, or inverter disconnect causing missing generation updates." + weather_note,
            "recommended_action": "Check inverter ethernet/SCADA connectivity, verify logger uptime, and confirm device clocks are synchronized before restarting communications.",
        })

    daily = df.groupby(["location_name", "log_date"], dropna=False)["kwh"].sum().reset_index()
    if not daily.empty:
        benchmark = daily.groupby("location_name")["kwh"].median().to_dict()
        for _, row in daily.iterrows():
            location = row["location_name"]
            total = float(row["kwh"])
            baseline = benchmark.get(location, 0)
            if baseline and total < (baseline * 0.7):
                weather_root = "Dust accumulation, partial shading, thermal issues, or failing string components suppressing normal output."
                if weather_context and weather_context.get("cloud_cover_pct") is not None:
                    cloud_cover = float(weather_context.get("cloud_cover_pct") or 0)
                    if cloud_cover > 60:
                        weather_root = "Weather-driven irradiance reduction is likely contributing to the underperformance, while plant-side issues should still be checked."
                issue_name = "Underperformance vs expected MTD/daily benchmark"
                anomalies.append({
                    "location": location or "Unknown",
                    "risk": classify_anomaly_risk(issue_name, weather_context),
                    "issue": issue_name,
                    "severity": "Medium",
                    "evidence": f"Daily generation {total:.2f}kWh vs median benchmark {baseline:.2f}kWh",
                    "root_cause": weather_root + weather_note,
                    "recommended_action": "Schedule module cleaning and thermal imaging, inspect for shadowing from vegetation or roof structures, and review weather-adjusted expected generation before dispatching maintenance.",
                })

    if not anomalies:
        return pd.DataFrame(
            columns=["location", "risk", "issue", "severity", "evidence", "root_cause", "recommended_action"]
        )

    final = pd.DataFrame(anomalies)
    final = final.sort_values(["severity", "location"], ascending=[False, True])
    return final.reset_index(drop=True)


# -----------------------------
# Command Center
# -----------------------------
# -----------------------------
# Command Center
# -----------------------------
if page == "Command Center":

    st.markdown("## ⚡ Command Center")
    st.caption(
        "Real-time overview of utility operations, consumption, "
        "generation and system health."
    )

    # =========================================================
    # KPI CARDS
    # =========================================================

    c1, c2, c3, c4 = st.columns(4)

    if solar_focus_mode:
        c1.metric(
            "☀️ Solar Generation",
            f"{solar_total:,.0f} kWh" if pd.notna(solar_total) else "N/A",
            border=True,
            delta_color="green",
        )
        c2.metric("⚡ Grid Energy", "N/A", border=True, delta_color="blue")
        c3.metric("🔌 Transformer Consumption", "N/A", border=True, delta_color="violet")
        c4.metric("Active Alerts", len(alerts_df), icon="⚠️", border=True)
    else:
        c1.metric(
            "⚡ Grid Energy",
            f"{grid:,.0f} kWh" if pd.notna(grid) else "N/A",
            border=True,
            delta_color="blue",
        )

        c2.metric(
            "☀️ Solar Generation",
            f"{solar_total:,.0f} kWh"
            if pd.notna(solar_total)
            else "N/A",
            border=True,
            delta_color="green",
        )

        c3.metric(
            "🔌 Transformer Consumption",
            f"{transformer_total:,.0f} kWh"
            if pd.notna(transformer_total)
            else "N/A",
            border=True,
            delta_color="violet",
        )
        c4.metric(
            "Active Alerts",
            len(alerts_df),
            icon="⚠️",
            border=True,
        )

    # =========================================================
    # SECOND KPI ROW
    # =========================================================

    c5, c6, c7, c8 = st.columns(4)

    if solar_focus_mode:
        c5.metric("Hexa Consumption", "N/A", icon="🏭", border=True)
        c6.metric("Vega Consumption", "N/A", icon="🏗️", border=True)
        c7.metric("Compressed Air", "N/A", icon="💨", border=True)
        c8.metric("Data Sources", len(data["sources"]), icon="📁", border=True)
    else:
        c5.metric(
            "Hexa Consumption",
            f"{hexa:,.0f} kWh" if pd.notna(hexa) else "N/A",
            icon="🏭",
            border=True,
        )

        c6.metric(
            "Vega Consumption",
            f"{vega:,.0f} kWh" if pd.notna(vega) else "N/A",
            icon="🏗️",
            border=True,
        )

        c7.metric(
            "Compressed Air",
            f"{air_total:,.0f} m³"
            if pd.notna(air_total)
            else "N/A",
            icon="💨",
            border=True,
        )

        c8.metric(
            "Data Sources",
            len(data["sources"]),
            icon="📁",
            border=True,
        )

    st.markdown("")

    # =========================================================
    # MAIN ANALYTICS AREA
    # =========================================================

    left, right = st.columns([1.6, 1])

    # ---------------------------------------------------------
    # ENERGY OVERVIEW
    # ---------------------------------------------------------

    with left:

        st.markdown("### 📈 Energy Overview")

        if solar_focus_mode:
            overview = pd.DataFrame({
                "Metric": ["Solar"],
                "Daily Value": [solar_total],
            }).dropna()
        else:
            overview = pd.DataFrame({
                "Metric": [
                    "Grid",
                    "Solar",
                    "Transformer",
                    "Hexa",
                    "Vega",
                ],
                "Daily Value": [
                    grid,
                    solar_total,
                    transformer_total,
                    hexa,
                    vega,
                ],
            }).dropna()

        if not overview.empty:
            render_status_bar_chart(overview, "Metric", "Daily Value")

        else:

            st.info(
                "Energy overview is not available."
            )

    # ---------------------------------------------------------
    # TOP CONSUMERS
    # ---------------------------------------------------------

    with right:

        st.markdown("### 🏆 Top Consumers")

        if (
            not tr_df.empty
            and "daily_kwh" in tr_df.columns
        ):

            top = (
                tr_df
                .sort_values(
                    "daily_kwh",
                    ascending=False
                )
                .head(5)
                .copy()
            )

            st.dataframe(
                top,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.info(
                "No consumer data is available."
            )

    # =========================================================
    # OPERATIONAL STATUS
    # =========================================================

    st.markdown("### 🚦 Intelligent Operational Status")

    if alerts_df.empty:

        st.success(
            "✅ No major anomalies detected in the imported dataset."
        )

    else:

        for _, alert in alerts_df.head(8).iterrows():

            severity = str(
                alert.get("severity", "")
            ).strip().lower()

            if severity == "high":

                st.error(
                    f"🔴 **{alert.get('title', 'Alert')}** — "
                    f"{alert.get('description', '')}"
                )

            elif severity == "medium":

                st.warning(
                    f"🟠 **{alert.get('title', 'Alert')}** — "
                    f"{alert.get('description', '')}"
                )

            else:

                st.info(
                    f"🔵 **{alert.get('title', 'Alert')}** — "
                    f"{alert.get('description', '')}"
                )

    # =========================================================
    # MANAGEMENT SNAPSHOT
    # =========================================================

    st.markdown("### 📋 Management Snapshot")

    snapshot_left, snapshot_right = st.columns(2)

    with snapshot_left:

        st.markdown(
            "**Energy Position**"
        )

        if (
            pd.notna(grid)
            and pd.notna(solar_total)
            and grid > 0
        ):

            solar_share = (
                solar_total / grid
            ) * 100

            st.write(
                f"Solar contribution is approximately "
                f"**{solar_share:.1f}%** of the reported grid-energy figure."
            )

        else:

            st.write(
                "Solar contribution cannot be calculated "
                "from the current dataset."
            )

    with snapshot_right:

        st.markdown(
            "**System Health**"
        )

        if alerts_df.empty:

            st.write(
                "🟢 Operations currently show no major alerts."
            )

        else:

            high_alerts = int(
                (
                    alerts_df["severity"]
                    .astype(str)
                    .str.lower()
                    == "high"
                ).sum()
            )

            st.write(
                f"🔴 **{high_alerts} high-severity alert(s)** "
                f"require attention."
            )

# -----------------------------
# Energy
# -----------------------------
elif page == "Energy":
    st.subheader("Energy Monitoring")
    st.write("Real energy values parsed from the Tata Power and Hexa/Vega workbooks.")

    if energy.empty or not {"location", "daily_kwh"}.issubset(energy.columns):
        st.warning("No energy data found. Put the Excel files inside the data folder.")
    else:
        st.dataframe(energy, use_container_width=True, hide_index=True)

        chart = energy[["location", "daily_kwh"]].dropna().sort_values("daily_kwh", ascending=False).head(15)
        st.markdown("### Daily Consumption by Source")
        render_status_bar_chart(chart, "location", "daily_kwh")

        if "energy_history" in data and not data["energy_history"].empty:
            st.markdown("### Historical Energy Trend")
            hist = data["energy_history"].copy()
            locations = st.multiselect(
                "Select sources",
                sorted(hist["location"].unique()),
                default=list(sorted(hist["location"].unique()))[:3]
            )
            if locations:
                h = hist[hist["location"].isin(locations)]
                pivot = h.pivot_table(index="date", columns="location", values="kwh", aggfunc="sum")
                st.line_chart(pivot, color=semantic_chart_colors(pivot.columns))

# -----------------------------
# Solar
# -----------------------------
elif page == "Solar":
    st.subheader("Solar Generation")
    if solar_df.empty:
        st.warning("Solar workbook not found.")
    else:
        total_daily = solar_df["daily_kwh"].sum()
        total_mtd = solar_df["mtd_kwh"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Daily Solar", f"{total_daily:,.2f} kWh")
        c2.metric("MTD Solar", f"{total_mtd:,.2f} kWh")
        c3.metric("Solar Sources", len(solar_df))

        render_status_bar_chart(solar_df, "source", "daily_kwh")
        st.dataframe(solar_df, use_container_width=True, hide_index=True)

    st.markdown("### ☀️ Solar Anomaly Detection & Diagnostics")
    weather_context = fetch_weather_context("Bangalore")
    if weather_context:
        weather_summary = (
            f"{weather_context.get('conditions', 'Weather conditions')} — "
            f"{weather_context.get('temperature_c_max')}°C max / "
            f"{weather_context.get('temperature_c_min')}°C min, "
            f"rain {weather_context.get('rain_sum_mm')} mm, "
            f"sunshine {weather_context.get('sunshine_duration_seconds')} s"
        )
        st.caption(f"Live weather context: {weather_summary}")

        weather_cols = st.columns(5)
        weather_metrics = [
            ("Condition", weather_context.get("conditions", "N/A")),
            ("Max Temp", f"{weather_context.get('temperature_c_max')}°C" if weather_context.get("temperature_c_max") is not None else "N/A"),
            ("Min Temp", f"{weather_context.get('temperature_c_min')}°C" if weather_context.get("temperature_c_min") is not None else "N/A"),
            ("Daylight", f"{weather_context.get('daylight_duration_seconds')} s" if weather_context.get("daylight_duration_seconds") is not None else "N/A"),
            ("Rain", f"{weather_context.get('rain_sum_mm')} mm" if weather_context.get("rain_sum_mm") is not None else "N/A"),
        ]
        for idx, (label, value) in enumerate(weather_metrics):
            with weather_cols[idx]:
                st.markdown(f"**{label}**")
                st.write(value)
    else:
        st.caption("Live weather context unavailable; using default anomaly logic.")

    anomaly_df = build_solar_anomaly_report()
    if anomaly_df.empty:
        st.success("No solar anomalies detected in the current time-series logs.")
    else:
        severity_counts = anomaly_df["severity"].value_counts().to_dict()
        col1, col2, col3 = st.columns(3)
        col1.metric("High Severity", int(severity_counts.get("High", 0)))
        col2.metric("Medium Severity", int(severity_counts.get("Medium", 0)))
        col3.metric("Total Findings", len(anomaly_df))

        display_df = anomaly_df[["location", "risk", "issue", "severity", "evidence", "root_cause", "recommended_action"]].copy()
        display_df["severity"] = display_df["severity"].astype(str).str.title()
        styled_df = display_df.style.map(
            lambda v: severity_cell_style(v) if v is not None and str(v).strip() else "",
            subset=["severity"],
        )
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        for _, row in anomaly_df.head(5).iterrows():
            severity = str(row.get("severity", "Low")).strip().title()
            if severity == "High":
                st.error(f"**{row['location']}** — {row['issue']}")
            elif severity == "Medium":
                st.warning(f"**{row['location']}** — {row['issue']}")
            else:
                st.success(f"**{row['location']}** — {row['issue']}")
            render_severity_badge(severity)
            render_risk_badge(row.get('risk', 'Mixed / review'))
            st.write(f"Evidence: {row['evidence']}")
            st.write(f"Likely root cause: {row['root_cause']}")
            st.write(f"Recommended action: {row['recommended_action']}")
            st.markdown("---")

# -----------------------------
# Hexa & Vega
# -----------------------------
elif page == "Hexa & Vega":
    st.subheader("Hexa & Vega Power Consumption")
    if energy.empty or not {"location", "daily_kwh"}.issubset(energy.columns):
        st.warning("Hexa/Vega data not found.")
    else:
        rows = energy[
            energy["location"].astype(str).str.contains(
                "Hexa|Vega", case=False, na=False
            )
        ].copy()
        if rows.empty:
            st.warning("Hexa/Vega data not found.")
        else:
            render_status_bar_chart(rows, "location", "daily_kwh")
            st.dataframe(rows, use_container_width=True, hide_index=True)

# -----------------------------
# Transformers
# -----------------------------
elif page == "Transformers":
    st.subheader("Transformer Performance")
    if tr_df.empty:
        st.warning("Transformer data not found.")
    else:
        render_status_bar_chart(tr_df, "transformer", "daily_kwh")
        st.dataframe(tr_df.sort_values("daily_kwh", ascending=False), use_container_width=True, hide_index=True)

        top = tr_df.sort_values("daily_kwh", ascending=False).iloc[0]
        st.info(
            f"Top transformer consumer: {top['transformer']} — "
            f"{top['daily_kwh']:,.2f} kWh for the selected day."
        )

# -----------------------------
# Utilities
# -----------------------------
elif page == "Utilities":
    st.subheader("Utilities — Air / Water / Flow")
    if air_df.empty:
        try:
            configured_utilities = get_utilities()
        except Exception:
            configured_utilities = pd.DataFrame()
        if configured_utilities.empty:
            st.warning("Air/utility data not found and no utilities have been configured.")
        else:
            st.info("Configured utility assets are shown below. Upload telemetry to populate measurements.")
            st.dataframe(
                configured_utilities[
                    ["code", "name", "type", "unit", "plant", "location", "active"]
                ].rename(
                    columns={
                        "code": "Code",
                        "name": "Utility",
                        "type": "Type",
                        "unit": "Unit",
                        "plant": "Plant",
                        "location": "Location",
                        "active": "Active",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.dataframe(air_df, use_container_width=True, hide_index=True)
        chart = air_df[["utility", "total_m3"]].dropna()
        if not chart.empty:
            render_status_bar_chart(chart, "utility", "total_m3")

# -----------------------------
# Environment
# -----------------------------
elif page == "Environment":
    st.subheader("Environment Monitoring")
    if env_df.empty:
        st.warning("Environment workbook not found.")
    else:
        display = env_df.copy()
        display["humidity_status"] = np.where(
            display["humidity_avg"] > HUMIDITY_TARGET, "Above Target", "Within Target"
        )
        display["temperature_status"] = np.where(
            display["temperature_avg"] > TEMP_TARGET, "Above Target", "Within Target"
        )
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.markdown("### Humidity")
        hum = display[["location", "humidity_avg"]].dropna().sort_values("humidity_avg", ascending=False)
        render_status_bar_chart(display, "location", "humidity_avg", target_column="humidity_target")

        st.markdown("### Temperature")
        tmp = display[["location", "temperature_avg"]].dropna()
        render_status_bar_chart(display, "location", "temperature_avg", target_column="temperature_target")

# -----------------------------
# Electrical Quality
# -----------------------------
elif page == "Electrical Quality":
    st.subheader("Electrical Quality — PF & Demand")
    st.info("The Unit 1 / Unit 5 workbook is connected. Raw PF/Demand numeric records are available below.")
    if data["pf"].empty:
        st.warning("PF & Demand data not found.")
    else:
        st.dataframe(data["pf"].head(1000), use_container_width=True, hide_index=True)

# -----------------------------
# Alerts
# -----------------------------
elif page == "Alerts & Anomalies":
    st.subheader("Exception & Anomaly Detection")
    if alerts_df.empty:
        st.success("No alerts.")
    else:
        counts = alerts_df["severity"].value_counts()
        a,b,c = st.columns(3)
        a.metric("High", int(counts.get("High", 0)))
        b.metric("Medium", int(counts.get("Medium", 0)))
        c.metric("Total", len(alerts_df))

        st.dataframe(alerts_df, use_container_width=True, hide_index=True)

# -----------------------------
# Insights
# -----------------------------
elif page == "Intelligent Insights":
    st.subheader("Intelligent Insights")
    st.caption("Rule-based insights generated from the imported project data.")

    if pd.notna(grid):
        st.write(f"• Grid energy is approximately **{grid:,.2f} kWh** for the selected daily dataset.")
    if pd.notna(solar_total):
        st.write(f"• Solar generation is approximately **{solar_total:,.2f} kWh**.")
    if not tr_df.empty:
        top = tr_df.sort_values("daily_kwh", ascending=False).iloc[0]
        st.write(f"• **{top['transformer']}** is the highest transformer consumer at **{top['daily_kwh']:,.2f} kWh**.")
    if not env_df.empty:
        high_h = env_df.sort_values("humidity_avg", ascending=False).iloc[0]
        st.write(f"• **{high_h['location']}** has the highest average humidity at **{high_h['humidity_avg']:.2f}%**, above the 60% target.")
    if pd.notna(air_total):
        st.write(f"• Compressed-air/utility totalizer data contains approximately **{air_total:,.2f} m³** in the daily summary.")

    st.markdown("### Recommended Actions")
    st.write("1. Investigate high-consumption transformers.")
    st.write("2. Review locations where humidity exceeds the configured target.")
    st.write("3. Review low power-factor intervals from the PF/Demand workbook.")
    st.write("4. Compare solar generation against plant consumption to identify additional savings opportunities.")

# -----------------------------
# Daily Report
# -----------------------------
elif page == "Daily Report":
    st.subheader("Automated Daily Report")

    report_date = st.date_input("Report date", value=datetime(2026, 8, 17).date())

    st.markdown("## Executive Summary")
    summary = pd.DataFrame({
        "Metric": [
            "Grid Energy",
            "Solar Generation",
            "Transformer Consumption",
            "Hexa Consumption",
            "Vega Consumption",
            "Compressed Air",
            "Active Alerts",
        ],
        "Value": [
            f"{grid:,.2f} kWh" if pd.notna(grid) else "N/A",
            f"{solar_total:,.2f} kWh" if pd.notna(solar_total) else "N/A",
            f"{transformer_total:,.2f} kWh" if pd.notna(transformer_total) else "N/A",
            f"{hexa:,.2f} kWh" if pd.notna(hexa) else "N/A",
            f"{vega:,.2f} kWh" if pd.notna(vega) else "N/A",
            f"{air_total:,.2f} m³" if pd.notna(air_total) else "N/A",
            str(len(alerts_df)),
        ],
    })
    st.table(summary)

    st.markdown("## Top Consumers")
    if not tr_df.empty:
        st.dataframe(tr_df.sort_values("daily_kwh", ascending=False).head(5), use_container_width=True, hide_index=True)

    st.markdown("## Alerts")
    if not alerts_df.empty:
        st.dataframe(alerts_df, use_container_width=True, hide_index=True)

    # CSV/Excel export
    report_csv = summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Summary CSV",
        report_csv,
        file_name=f"daily_report_{report_date}.csv",
        mime="text/csv",
    )

    if REPORTLAB_OK:
        if st.button("Generate PDF Report"):
            pdf_path = Path(f"daily_report_{report_date}.pdf")
            c = canvas.Canvas(str(pdf_path), pagesize=A4)
            width, height = A4
            y = height - 50
            c.setFont("Helvetica-Bold", 16)
            c.drawString(40, y, "Automated Utility Intelligence")
            y -= 25
            c.setFont("Helvetica", 10)
            c.drawString(40, y, f"Daily Report — {report_date}")
            y -= 35
            for _, row in summary.iterrows():
                c.drawString(50, y, f"{row['Metric']}: {row['Value']}")
                y -= 18
            c.save()
            st.success("PDF generated.")
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "Download PDF",
                    f.read(),
                    file_name=pdf_path.name,
                    mime="application/pdf",
                )
        else:
            st.warning("Install reportlab to enable PDF generation.")


# =========================================================
# DAILY & MONTHLY MANAGEMENT REPORT
# =========================================================

elif page == "Management Reports":

    st.subheader("📊 Daily & Monthly Management Reports")

    st.write(
        "Generate management reports directly from the "
        "uploaded utility data."
    )

    # -----------------------------------------------------
    # LOAD UPLOADED DATA
    # -----------------------------------------------------

    uploaded_files = get_uploaded_files()

    report_dataframes = []

    for filename in uploaded_files:

        try:

            uploaded_df = load_saved_data(filename)

            if (
                isinstance(uploaded_df, pd.DataFrame)
                and not uploaded_df.empty
            ):

                report_dataframes.append(
                    uploaded_df.copy()
                )

        except Exception as e:

            st.warning(
                f"Could not load {filename}: {e}"
            )

    # -----------------------------------------------------
    # CHECK DATA
    # -----------------------------------------------------

    if not report_dataframes:

        st.info(
            "No uploaded utility data is available. "
            "Please upload a CSV or Excel file from "
            "Data Upload."
        )

    else:

        report_df = pd.concat(
            report_dataframes,
            ignore_index=True,
            sort=False
        )

        # -------------------------------------------------
        # CHECK DATE COLUMN
        # -------------------------------------------------

        if "date" not in report_df.columns:

            st.error(
                "The uploaded data does not contain a "
                "'date' column."
            )

        else:

            report_df["date"] = pd.to_datetime(
                report_df["date"],
                errors="coerce"
            )

            report_df = report_df.dropna(
                subset=["date"]
            )

            # -------------------------------------------------
            # REPORT TYPE
            # -------------------------------------------------

            report_type = st.radio(
                "Report Type",
                [
                    "Daily Report",
                    "Monthly Report"
                ],
                horizontal=True,
                key="management_report_type"
            )

            # =================================================
            # DAILY REPORT
            # =================================================

            if report_type == "Daily Report":

                available_dates = sorted(
                    report_df["date"].dt.date.unique()
                )

                if not available_dates:

                    st.warning(
                        "No valid dates are available "
                        "in the uploaded data."
                    )

                else:

                    selected_date = st.selectbox(
                        "Select Report Date",
                        available_dates,
                        index=len(available_dates) - 1,
                        key="management_daily_date"
                    )

                    daily_df = report_df[
                        report_df["date"].dt.date
                        == selected_date
                    ].copy()

                    st.markdown(
                        f"### 📅 Daily Report — {selected_date}"
                    )

                    # -----------------------------------------
                    # NUMERIC COLUMNS
                    # -----------------------------------------

                    energy_total = 0
                    water_total = 0
                    solar_total = 0

                    if (
                        "energy_consumption_kwh"
                        in daily_df.columns
                    ):

                        energy_total = pd.to_numeric(
                            daily_df[
                                "energy_consumption_kwh"
                            ],
                            errors="coerce"
                        ).sum()

                    if (
                        "water_consumption_liters"
                        in daily_df.columns
                    ):

                        water_total = pd.to_numeric(
                            daily_df[
                                "water_consumption_liters"
                            ],
                            errors="coerce"
                        ).sum()

                    if (
                        "solar_generation_kwh"
                        in daily_df.columns
                    ):

                        solar_total = pd.to_numeric(
                            daily_df[
                                "solar_generation_kwh"
                            ],
                            errors="coerce"
                        ).sum()

                    # -----------------------------------------
                    # SUMMARY
                    # -----------------------------------------

                    col1, col2, col3 = st.columns(3)

                    with col1:

                        st.metric(
                            "Energy Consumption",
                            f"{energy_total:,.0f} kWh"
                        )

                    with col2:

                        st.metric(
                            "Water Consumption",
                            f"{water_total:,.0f} L"
                        )

                    with col3:

                        st.metric(
                            "Solar Generation",
                            f"{solar_total:,.0f} kWh"
                        )

                    st.markdown("### 🏭 Unit-wise Consumption")

                    if (
                        "unit" in daily_df.columns
                        and
                        "energy_consumption_kwh"
                        in daily_df.columns
                    ):

                        unit_report = (
                            daily_df[
                                [
                                    "unit",
                                    "energy_consumption_kwh"
                                ]
                            ]
                            .copy()
                        )

                        unit_report[
                            "energy_consumption_kwh"
                        ] = pd.to_numeric(
                            unit_report[
                                "energy_consumption_kwh"
                            ],
                            errors="coerce"
                        )

                        unit_report = (
                            unit_report
                            .sort_values(
                                "energy_consumption_kwh",
                                ascending=False
                            )
                            .reset_index(drop=True)
                        )

                        st.dataframe(
                            unit_report,
                            use_container_width=True,
                            hide_index=True
                        )

                    # -----------------------------------------
                    # FULL DAILY DATA
                    # -----------------------------------------

                    with st.expander(
                        "View Daily Data"
                    ):

                        st.dataframe(
                            daily_df,
                            use_container_width=True,
                            hide_index=True
                        )

                                        # -----------------------------------------
                    # DOWNLOAD DAILY REPORTS
                    # -----------------------------------------

                    st.markdown("### 📥 Download Daily Report")

                    # -----------------------------------------
                    # DAILY CSV
                    # -----------------------------------------

                    daily_csv = daily_df.to_csv(
                        index=False
                    ).encode("utf-8")

                    st.download_button(
                        "⬇️ Download Daily Report CSV",
                        daily_csv,
                        file_name=(
                            f"daily_report_"
                            f"{selected_date}.csv"
                        ),
                        mime="text/csv",
                        key="download_daily_management_report"
                    )

                    # -----------------------------------------
                    # DAILY EXCEL
                    # -----------------------------------------

                    daily_excel_buffer = io.BytesIO()

                    with pd.ExcelWriter(
                        daily_excel_buffer,
                        engine="openpyxl"
                    ) as writer:

                        daily_df.to_excel(
                            writer,
                            index=False,
                            sheet_name="Daily Data"
                        )

                        if (
                            "unit" in daily_df.columns
                            and
                            "energy_consumption_kwh"
                            in daily_df.columns
                        ):

                            unit_report.to_excel(
                                writer,
                                index=False,
                                sheet_name="Unit Summary"
                            )

                    daily_excel_buffer.seek(0)

                    st.download_button(
                        "📊 Download Daily Report Excel",
                        daily_excel_buffer.getvalue(),
                        file_name=(
                            f"daily_report_"
                            f"{selected_date}.xlsx"
                        ),
                        mime=(
                            "application/vnd.openxmlformats-"
                            "officedocument.spreadsheetml.sheet"
                        ),
                        key="download_daily_management_excel"
                    )

                    # -----------------------------------------
                    # DAILY PDF
                    # -----------------------------------------

                    if REPORTLAB_OK:

                        daily_pdf_buffer = io.BytesIO()

                        pdf = canvas.Canvas(
                            daily_pdf_buffer,
                            pagesize=A4
                        )

                        width, height = A4

                        y = height - 50

                        pdf.setFont(
                            "Helvetica-Bold",
                            18
                        )

                        pdf.drawString(
                            40,
                            y,
                            "Utility Intelligence"
                        )

                        y -= 28

                        pdf.setFont(
                            "Helvetica",
                            11
                        )

                        pdf.drawString(
                            40,
                            y,
                            f"Daily Management Report — "
                            f"{selected_date}"
                        )

                        y -= 40

                        pdf.setFont(
                            "Helvetica-Bold",
                            12
                        )

                        pdf.drawString(
                            40,
                            y,
                            "Summary"
                        )

                        y -= 25

                        pdf.setFont(
                            "Helvetica",
                            11
                        )

                        pdf.drawString(
                            50,
                            y,
                            f"Energy Consumption: "
                            f"{energy_total:,.0f} kWh"
                        )

                        y -= 20

                        pdf.drawString(
                            50,
                            y,
                            f"Water Consumption: "
                            f"{water_total:,.0f} L"
                        )

                        y -= 20

                        pdf.drawString(
                            50,
                            y,
                            f"Solar Generation: "
                            f"{solar_total:,.0f} kWh"
                        )

                        y -= 35

                        pdf.setFont(
                            "Helvetica-Bold",
                            12
                        )

                        pdf.drawString(
                            40,
                            y,
                            "Unit-wise Energy Consumption"
                        )

                        y -= 25

                        pdf.setFont(
                            "Helvetica",
                            10
                        )

                        if (
                            "unit" in daily_df.columns
                            and
                            "energy_consumption_kwh"
                            in daily_df.columns
                        ):

                            for _, row in unit_report.iterrows():

                                unit = row["unit"]

                                energy = row[
                                    "energy_consumption_kwh"
                                ]

                                pdf.drawString(
                                    50,
                                    y,
                                    f"{unit}: "
                                    f"{energy:,.0f} kWh"
                                )

                                y -= 18

                                if y < 60:

                                    pdf.showPage()

                                    y = height - 50

                                    pdf.setFont(
                                        "Helvetica",
                                        10
                                    )

                        pdf.save()

                        daily_pdf_buffer.seek(0)

                        st.download_button(
                            "📄 Download Daily Report PDF",
                            daily_pdf_buffer.getvalue(),
                            file_name=(
                                f"daily_report_"
                                f"{selected_date}.pdf"
                            ),
                            mime="application/pdf",
                            key="download_daily_management_pdf"
                        )

                    else:

                        st.warning(
                            "PDF download is unavailable "
                            "because ReportLab is not installed."
                        )
            # =================================================
            # MONTHLY REPORT
            # =================================================

            else:

                report_df["month"] = (
                    report_df["date"]
                    .dt.to_period("M")
                    .astype(str)
                )

                available_months = sorted(
                    report_df["month"].unique()
                )

                if not available_months:

                    st.warning(
                        "No valid months are available."
                    )

                else:

                    selected_month = st.selectbox(
                        "Select Report Month",
                        available_months,
                        index=len(available_months) - 1,
                        key="management_month"
                    )

                    monthly_df = report_df[
                        report_df["month"]
                        == selected_month
                    ].copy()

                    st.markdown(
                        f"### 📆 Monthly Report — "
                        f"{selected_month}"
                    )

                    # -----------------------------------------
                    # MONTHLY TOTALS
                    # -----------------------------------------

                    monthly_energy = 0
                    monthly_water = 0
                    monthly_solar = 0

                    if (
                        "energy_consumption_kwh"
                        in monthly_df.columns
                    ):

                        monthly_energy = pd.to_numeric(
                            monthly_df[
                                "energy_consumption_kwh"
                            ],
                            errors="coerce"
                        ).sum()

                    if (
                        "water_consumption_liters"
                        in monthly_df.columns
                    ):

                        monthly_water = pd.to_numeric(
                            monthly_df[
                                "water_consumption_liters"
                            ],
                            errors="coerce"
                        ).sum()

                    if (
                        "solar_generation_kwh"
                        in monthly_df.columns
                    ):

                        monthly_solar = pd.to_numeric(
                            monthly_df[
                                "solar_generation_kwh"
                            ],
                            errors="coerce"
                        ).sum()

                    # -----------------------------------------
                    # SUMMARY METRICS
                    # -----------------------------------------

                    col1, col2, col3 = st.columns(3)

                    with col1:

                        st.metric(
                            "Monthly Energy",
                            f"{monthly_energy:,.0f} kWh"
                        )

                    with col2:

                        st.metric(
                            "Monthly Water",
                            f"{monthly_water:,.0f} L"
                        )

                    with col3:

                        st.metric(
                            "Monthly Solar",
                            f"{monthly_solar:,.0f} kWh"
                        )

                    # -----------------------------------------
                    # UNIT RANKING
                    # -----------------------------------------

                    st.markdown(
                        "### 🏆 Top Energy Consumers"
                    )

                    if (
                        "unit" in monthly_df.columns
                        and
                        "energy_consumption_kwh"
                        in monthly_df.columns
                    ):

                        monthly_unit_report = (
                            monthly_df[
                                [
                                    "unit",
                                    "energy_consumption_kwh"
                                ]
                            ]
                            .copy()
                        )

                        monthly_unit_report[
                            "energy_consumption_kwh"
                        ] = pd.to_numeric(
                            monthly_unit_report[
                                "energy_consumption_kwh"
                            ],
                            errors="coerce"
                        )

                        monthly_unit_report = (
                            monthly_unit_report
                            .groupby(
                                "unit",
                                as_index=False
                            )[
                                "energy_consumption_kwh"
                            ]
                            .sum()
                            .sort_values(
                                "energy_consumption_kwh",
                                ascending=False
                            )
                            .reset_index(drop=True)
                        )

                        st.dataframe(
                            monthly_unit_report,
                            use_container_width=True,
                            hide_index=True
                        )

                    # -----------------------------------------
                    # DAILY TREND
                    # -----------------------------------------

                    st.markdown(
                        "### 📈 Daily Energy Trend"
                    )

                    if (
                        "energy_consumption_kwh"
                        in monthly_df.columns
                    ):

                        monthly_daily = (
                            monthly_df
                            .groupby(
                                monthly_df[
                                    "date"
                                ].dt.date
                            )[
                                "energy_consumption_kwh"
                            ]
                            .sum()
                            .reset_index()
                        )

                        monthly_daily.columns = [
                            "date",
                            "energy_consumption_kwh"
                        ]

                        st.line_chart(
                            monthly_daily.set_index(
                                "date"
                            ),
                            color=CHART_COLORS["energy"],
                        )

                    # -----------------------------------------
                    # FULL MONTHLY DATA
                    # -----------------------------------------

                    with st.expander(
                        "View Monthly Data"
                    ):

                        st.dataframe(
                            monthly_df.drop(
                                columns=["month"],
                                errors="ignore"
                            ),
                            use_container_width=True,
                            hide_index=True
                        )

                                       # -----------------------------------------
                    # DOWNLOAD MONTHLY REPORTS
                    # -----------------------------------------

                    st.markdown("### 📥 Download Monthly Report")

                    # Remove helper column before exporting
                    monthly_export_df = (
                        monthly_df
                        .drop(
                            columns=["month"],
                            errors="ignore"
                        )
                        .copy()
                    )

                    # -----------------------------------------
                    # MONTHLY CSV
                    # -----------------------------------------

                    monthly_csv = (
                        monthly_export_df
                        .to_csv(index=False)
                        .encode("utf-8")
                    )

                    st.download_button(
                        "⬇️ Download Monthly Report CSV",
                        monthly_csv,
                        file_name=(
                            f"monthly_report_"
                            f"{selected_month}.csv"
                        ),
                        mime="text/csv",
                        key="download_monthly_management_report"
                    )

                    # -----------------------------------------
                    # MONTHLY EXCEL
                    # -----------------------------------------

                    monthly_excel_buffer = io.BytesIO()

                    with pd.ExcelWriter(
                        monthly_excel_buffer,
                        engine="openpyxl"
                    ) as writer:

                        monthly_export_df.to_excel(
                            writer,
                            index=False,
                            sheet_name="Monthly Data"
                        )

                        if (
                            "unit" in monthly_unit_report.columns
                            and
                            "energy_consumption_kwh"
                            in monthly_unit_report.columns
                        ):

                            monthly_unit_report.to_excel(
                                writer,
                                index=False,
                                sheet_name="Unit Summary"
                            )

                        monthly_daily.to_excel(
                            writer,
                            index=False,
                            sheet_name="Daily Trend"
                        )

                    monthly_excel_buffer.seek(0)

                    st.download_button(
                        "📊 Download Monthly Report Excel",
                        monthly_excel_buffer.getvalue(),
                        file_name=(
                            f"monthly_report_"
                            f"{selected_month}.xlsx"
                        ),
                        mime=(
                            "application/vnd.openxmlformats-"
                            "officedocument.spreadsheetml.sheet"
                        ),
                        key="download_monthly_management_excel"
                    )

                    # -----------------------------------------
                    # MONTHLY PDF
                    # -----------------------------------------

                    if REPORTLAB_OK:

                        monthly_pdf_buffer = io.BytesIO()

                        pdf = canvas.Canvas(
                            monthly_pdf_buffer,
                            pagesize=A4
                        )

                        width, height = A4

                        y = height - 50

                        pdf.setFont(
                            "Helvetica-Bold",
                            18
                        )

                        pdf.drawString(
                            40,
                            y,
                            "Utility Intelligence"
                        )

                        y -= 28

                        pdf.setFont(
                            "Helvetica",
                            11
                        )

                        pdf.drawString(
                            40,
                            y,
                            f"Monthly Management Report — "
                            f"{selected_month}"
                        )

                        y -= 40

                        pdf.setFont(
                            "Helvetica-Bold",
                            12
                        )

                        pdf.drawString(
                            40,
                            y,
                            "Monthly Summary"
                        )

                        y -= 25

                        pdf.setFont(
                            "Helvetica",
                            11
                        )

                        pdf.drawString(
                            50,
                            y,
                            f"Energy Consumption: "
                            f"{monthly_energy:,.0f} kWh"
                        )

                        y -= 20

                        pdf.drawString(
                            50,
                            y,
                            f"Water Consumption: "
                            f"{monthly_water:,.0f} L"
                        )

                        y -= 20

                        pdf.drawString(
                            50,
                            y,
                            f"Solar Generation: "
                            f"{monthly_solar:,.0f} kWh"
                        )

                        y -= 35

                        pdf.setFont(
                            "Helvetica-Bold",
                            12
                        )

                        pdf.drawString(
                            40,
                            y,
                            "Top Energy Consumers"
                        )

                        y -= 25

                        pdf.setFont(
                            "Helvetica",
                            10
                        )

                        if (
                            "unit"
                            in monthly_unit_report.columns
                            and
                            "energy_consumption_kwh"
                            in monthly_unit_report.columns
                        ):

                            for _, row in (
                                monthly_unit_report.iterrows()
                            ):

                                unit = row["unit"]

                                energy = row[
                                    "energy_consumption_kwh"
                                ]

                                pdf.drawString(
                                    50,
                                    y,
                                    f"{unit}: "
                                    f"{energy:,.0f} kWh"
                                )

                                y -= 18

                                if y < 60:

                                    pdf.showPage()

                                    y = height - 50

                                    pdf.setFont(
                                        "Helvetica",
                                        10
                                    )

                        y -= 20

                        pdf.setFont(
                            "Helvetica-Bold",
                            12
                        )

                        pdf.drawString(
                            40,
                            y,
                            "Daily Energy Trend"
                        )

                        y -= 25

                        pdf.setFont(
                            "Helvetica",
                            10
                        )

                        for _, row in monthly_daily.iterrows():

                            date_value = row["date"]

                            energy_value = row[
                                "energy_consumption_kwh"
                            ]

                            pdf.drawString(
                                50,
                                y,
                                f"{date_value}: "
                                f"{energy_value:,.0f} kWh"
                            )

                            y -= 16

                            if y < 60:

                                pdf.showPage()

                                y = height - 50

                                pdf.setFont(
                                    "Helvetica",
                                    10
                                )

                        pdf.save()

                        monthly_pdf_buffer.seek(0)

                        st.download_button(
                            "📄 Download Monthly Report PDF",
                            monthly_pdf_buffer.getvalue(),
                            file_name=(
                                f"monthly_report_"
                                f"{selected_month}.pdf"
                            ),
                            mime="application/pdf",
                            key="download_monthly_management_pdf"
                        )

                    else:

                        st.warning(
                            "PDF download is unavailable "
                            "because ReportLab is not installed."
                        )

                    # =================================================
                    # MANAGEMENT INSIGHTS
                    # =================================================

                    st.markdown("## 🧠 Management Insights")

                    # -----------------------------------------
                    # HIGHEST CONSUMING UNIT
                    # -----------------------------------------

                    if (
                        "unit" in monthly_df.columns
                        and
                        "energy_consumption_kwh"
                        in monthly_df.columns
                    ):

                        insight_unit_df = (
                            monthly_df[
                                [
                                    "unit",
                                    "energy_consumption_kwh"
                                ]
                            ]
                            .copy()
                        )

                        insight_unit_df[
                            "energy_consumption_kwh"
                        ] = pd.to_numeric(
                            insight_unit_df[
                                "energy_consumption_kwh"
                            ],
                            errors="coerce"
                        )

                        insight_unit_df = (
                            insight_unit_df
                            .dropna(
                                subset=[
                                    "energy_consumption_kwh"
                                ]
                            )
                            .groupby(
                                "unit",
                                as_index=False
                            )[
                                "energy_consumption_kwh"
                            ]
                            .sum()
                            .sort_values(
                                "energy_consumption_kwh",
                                ascending=False
                            )
                        )

                        if not insight_unit_df.empty:

                            top_unit = insight_unit_df.iloc[0]

                            st.info(
                                f"🏆 **Highest Energy Consumer:** "
                                f"{top_unit['unit']} with "
                                f"{top_unit['energy_consumption_kwh']:,.0f} kWh."
                            )

                    # -----------------------------------------
                    # HIGHEST CONSUMPTION DAY
                    # -----------------------------------------

                    if (
                        "date" in monthly_df.columns
                        and
                        "energy_consumption_kwh"
                        in monthly_df.columns
                    ):

                        daily_insight = (
                            monthly_df
                            .groupby(
                                monthly_df["date"].dt.date
                            )[
                                "energy_consumption_kwh"
                            ]
                            .sum()
                            .sort_values(
                                ascending=False
                            )
                        )

                        if not daily_insight.empty:

                            highest_day = daily_insight.index[0]
                            highest_day_value = daily_insight.iloc[0]

                            st.info(
                                f"📈 **Highest Consumption Day:** "
                                f"{highest_day} with "
                                f"{highest_day_value:,.0f} kWh."
                            )

                    # -----------------------------------------
                    # SOLAR CONTRIBUTION
                    # -----------------------------------------

                    if monthly_energy > 0:

                        solar_percentage = (
                            monthly_solar
                            / monthly_energy
                        ) * 100

                        st.info(
                            f"☀️ **Solar Contribution:** "
                            f"{solar_percentage:.1f}% of total "
                            f"energy consumption."
                        )

                    # -----------------------------------------
                    # MANAGEMENT RECOMMENDATIONS
                    # -----------------------------------------

                    st.markdown(
                        "### 💡 Recommended Management Actions"
                    )

                    recommendations = []

                    if (
                        "unit" in monthly_df.columns
                        and
                        "energy_consumption_kwh"
                        in monthly_df.columns
                        and not insight_unit_df.empty
                    ):

                        recommendations.append(
                            f"Review energy usage at "
                            f"{top_unit['unit']}, the highest "
                            f"consuming unit."
                        )

                    if (
                        monthly_solar > 0
                        and monthly_energy > 0
                    ):

                        recommendations.append(
                            "Continue monitoring solar generation "
                            "against total plant consumption."
                        )

                    if (
                        "water_consumption_liters"
                        in monthly_df.columns
                        and monthly_water > 0
                    ):

                        recommendations.append(
                            "Monitor water consumption trends "
                            "for opportunities to reduce usage."
                        )

                    if not recommendations:

                        recommendations.append(
                            "Continue monitoring utility "
                            "consumption trends."
                        )

                    for recommendation in recommendations:

                        st.write(
                            f"• {recommendation}"
                        )


# -----------------------------
# Data Upload
# -----------------------------

elif page == "Data Upload":

    if not current_user_is_admin():
        st.error("Only administrators may upload or delete shared utility data.")
        st.stop()

    st.subheader("📁 Data Ingestion & Validation")

    st.write(
        "Upload one utility Excel workbook or a CSV file. "
        "Excel workbooks can contain multiple utility sheets."
    )

    st.caption(
        "Current site context: "
        f"{st.session_state.get('selected_location', '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100')} / "
        f"{st.session_state.get('selected_plant', 'TATA POWER SOLAR UNIT-1')} / "
        f"{st.session_state.get('selected_line', 'Vega')}"
    )

    uploaded = st.file_uploader(
        "Upload CSV or Excel file",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key="utility_data_uploader"
    )

    if uploaded:

        for file in uploaded:

            st.markdown(f"### 📄 {file.name}")
            workbook_sheets = None
            workbook_validation = None
            workbook_validated = False

            try:

                # -------------------------------------------------
                # LOAD FILE
                # -------------------------------------------------

                if file.name.lower().endswith(
                    (".xlsx", ".xls")
                ):

                    workbook_sheets = load_excel_sheets(
                        file
                    )

                    st.success(
                        f"Excel workbook loaded successfully: "
                        f"{file.name}"
                    )

                    # -------------------------------------------------
                    # WORKBOOK SUMMARY
                    # -------------------------------------------------

                    st.markdown(
                        "### 📚 Workbook Sheets"
                    )

                    sheet_summary = []

                    for sheet_name, sheet_df in (
                        workbook_sheets.items()
                    ):

                        sheet_summary.append(
                            {
                                "Sheet": sheet_name,
                                "Rows": len(sheet_df),
                                "Columns": len(sheet_df.columns),
                            }
                        )

                    sheet_summary_df = pd.DataFrame(
                        sheet_summary
                    )

                    st.dataframe(
                        sheet_summary_df,
                        use_container_width=True,
                        hide_index=True
                    )

                    st.markdown("### ✅ Workbook Validation")
                    workbook_validation = validate_workbook_sheets(workbook_sheets)
                    st.dataframe(
                        workbook_validation,
                        use_container_width=True,
                        hide_index=True,
                    )
                    validation_key = f"validated_workbook_{file.name}"
                    if st.button("Validate Workbook", key=f"validate_{file.name}"):
                        has_errors = bool((workbook_validation["Status"] == "ERROR").any())
                        st.session_state[validation_key] = not has_errors
                        if has_errors:
                            st.error("Workbook validation failed. Correct the ERROR sheets before importing.")
                        else:
                            st.success("Workbook validation passed. Import is available.")
                    workbook_validated = st.session_state.get(validation_key, False)
                    if not workbook_validated:
                        st.info("Select Validate Workbook before importing this file.")

                    # -------------------------------------------------
                    # SHEET PREVIEW
                    # -------------------------------------------------

                    selected_sheet = st.selectbox(
                        "Preview Sheet",
                        list(workbook_sheets.keys()),
                        key=f"preview_sheet_{file.name}"
                    )

                    df = workbook_sheets[
                        selected_sheet
                    ].copy()

                    st.info(
                        f"Showing sheet: {selected_sheet}"
                    )

                else:

                    df = load_file(file)

                    st.success(
                        f"File loaded successfully: "
                        f"{file.name}"
                    )

                # -------------------------------------------------
                # CLEAN DATA
                # -------------------------------------------------

                cleaned_df = clean_data(
                    df
                )

                # -------------------------------------------------
                # SUMMARY
                # -------------------------------------------------

                summary = get_data_summary(
                    cleaned_df
                )

                col1, col2, col3, col4 = st.columns(4)

                col1.metric(
                    "Rows",
                    summary["rows"]
                )

                col2.metric(
                    "Columns",
                    summary["columns"]
                )

                col3.metric(
                    "Missing Values",
                    summary["missing_values"]
                )

                col4.metric(
                    "Duplicate Rows",
                    summary["duplicate_rows"]
                )

                # -------------------------------------------------
                # DATA PREVIEW
                # -------------------------------------------------

                st.markdown(
                    "### 🔍 Data Preview"
                )

                st.dataframe(
                    cleaned_df.head(20),
                    use_container_width=True,
                    hide_index=True
                )

                # -------------------------------------------------
                # VALIDATION
                # -------------------------------------------------

                errors, warnings = validate_data(
                    cleaned_df
                )

                if errors:

                    for error in errors:

                        st.error(
                            error
                        )

                if warnings:

                    st.warning(
                        "Data validation warnings:"
                    )

                    for warning in warnings:

                        st.write(
                            f"• {warning}"
                        )

                import_ready = not errors and (workbook_sheets is None or workbook_validated)
                if import_ready:

                    st.success(
                        "✅ Data validation completed successfully."
                    )

                    # -------------------------------------------------
                    # SAVE
                    # -------------------------------------------------

                    if st.button(
                        f"💾 Save {file.name}",
                        key=f"save_{file.name}"
                    ):

                        try:

                            if workbook_sheets is not None:
                                saved_path = save_uploaded_workbook(
                                    workbook_sheets,
                                    file.name
                                )
                            else:
                                saved_path = save_uploaded_data(
                                    cleaned_df,
                                    file.name
                                )

                            if workbook_sheets is not None:
                                for sheet_name, sheet_frame in workbook_sheets.items():
                                    save_uploaded_dataset(sheet_frame, file.name, sheet_name)
                            else:
                                save_uploaded_dataset(cleaned_df, file.name, "Dataset")
                            
                            st.session_state["active_workbook"] = saved_path.name

                            with open(DATA_DIR / "active_workbook.txt", "w") as f:
                                f.write(saved_path.name)

                            solar_records = 0
                            if workbook_sheets is not None:
                                try:
                                    file.seek(0)
                                    solar_records = ingest_uploaded_file(
                                        file,
                                        st.session_state.get("selected_location", "78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100"),
                                        st.session_state.get("selected_plant", "TATA POWER SOLAR UNIT-1"),
                                        st.session_state.get("selected_line", "Vega"),
                                    )
                                except Exception:
                                    solar_records = 0

                            # Always rebuild the complete dashboard model from the
                            # saved upload set. Solar ingestion updates telemetry;
                            # this normalized snapshot updates air, environment,
                            # energy, solar, and other dashboard sections together.
                            dashboard_snapshot = load_uploaded_master_data()
                            if dashboard_snapshot is not None:
                                replace_dashboard_snapshot(dashboard_snapshot)

                            st.success(
                                "✅ Data saved successfully!"
                            )

                            st.info(
                                f"Stored as: {saved_path.name}"
                            )

                            processed_rows = (
                                sum(len(sheet) for sheet in workbook_sheets.values())
                                if workbook_sheets
                                else len(cleaned_df)
                            )
                            st.session_state["last_upload_summary"] = {
                                "filename": saved_path.name,
                                "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "sheets": list(workbook_sheets) if workbook_sheets else ["Single dataset"],
                                "rows_processed": int(processed_rows),
                                "rows_inserted": int(solar_records or processed_rows),
                                "rows_skipped": 0,
                            }

                            

                            st.session_state[
                               "uploaded_data"
                            ] = cleaned_df

                            st.rerun()


                        except Exception as e:

                            st.error(
                                f"Could not save file: {e}"
                            )

            except Exception as e:

                st.error(
                    f"Could not process {file.name}: {e}"
                )

    render_excel_uploader(
        selected_location=st.session_state.get("selected_location", "78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100"),
        selected_plant=st.session_state.get("selected_plant", "TATA POWER SOLAR UNIT-1"),
        selected_line=st.session_state.get("selected_line", "Vega"),
    )

    # ---------------------------------------------------------
    # SAVED FILES
    # ---------------------------------------------------------

    st.divider()

    st.subheader(
        "🗂️ Saved Data Files"
    )

    try:

        saved_files = get_uploaded_files()

        if not saved_files:

            st.info(
                "No uploaded files have been permanently stored yet."
            )

        else:

            for filename in saved_files:

                col1, col2 = st.columns([4, 1])

                col1.write(
                    f"📄 {filename}"
                )

                if col2.button(
                    "Delete",
                    key=f"delete_{filename}"
                ):

                    try:

                        delete_uploaded_file(
                            filename
                        )

                        st.success(
                            f"{filename} deleted successfully."
                        )

                        st.rerun()

                    except Exception as e:

                        st.error(
                            f"Could not delete {filename}: {e}"
                        )

    except Exception as e:

        st.error(
            f"Could not read saved files: {e}"
        )


# -----------------------------
# Data Sources
# -----------------------------
elif page == "Data Sources":
    st.subheader("Imported Data Sources")

    last_upload = st.session_state.get("last_upload_summary")
    if last_upload:
        st.info(
            f"Latest upload: {last_upload['filename']} at {last_upload['uploaded_at']} | "
            f"{last_upload['rows_inserted']} rows stored | "
            f"Sheets: {', '.join(last_upload['sheets'])}"
        )

    try:
        source_summary = get_dashboard_source_summary()
        counts = source_summary["counts"]
        source_rows = [
            {"Source": "PostgreSQL", "Status": "Connected", "Database": source_summary["database"], "Rows": sum(counts.values())},
            {"Source": "Energy snapshot", "Status": "Available" if counts["dashboard_energy"] else "No data", "Database": "dashboard_energy", "Rows": counts["dashboard_energy"]},
            {"Source": "Solar snapshot", "Status": "Available" if counts["dashboard_solar"] else "No data", "Database": "dashboard_solar", "Rows": counts["dashboard_solar"]},
            {"Source": "Transformer snapshot", "Status": "Available" if counts["dashboard_transformers"] else "No data", "Database": "dashboard_transformers", "Rows": counts["dashboard_transformers"]},
        ]
        st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)
        if source_summary["sources"]:
            st.markdown("#### Persisted upload sources")
            st.dataframe(
                pd.DataFrame(source_summary["sources"], columns=["Source", "Filename"]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No imported PostgreSQL dashboard sources are available.")
    except Exception:
        st.error("The persisted PostgreSQL data-source summary is unavailable.")

    st.markdown("### Expected project files")
    st.write("""
    - Daily_Tata_Power_Systems_LTD_17-Aug-26.xlsx
    - Daily_Hexa_and_Vega_power_consumption_17-Aug-26.xlsx
    - Solar_Generation_-_U2_17-Aug-26.xlsx
    - Tata_Power_Air_Report_-_U2_17-Aug-26.xlsx
    - Tata_Power_Solar_Systems_Ltd_Humidity___Temperature_-_U2_17-Aug-26.xlsx
    - Unit_-1_and_5_daily_Tata_Power_Systems_LTD_17-Aug-26.xlsx
    """)
elif page == "AI Assistant":
    render_ai_assistant()
    st.stop()

    # ---------------------------------------------------------
    # SESSION STATE
    # ---------------------------------------------------------

    if "selected_question" not in st.session_state:
        st.session_state["selected_question"] = ""

    # ---------------------------------------------------------
    # QUESTION HISTORY
    # ---------------------------------------------------------

    history = get_question_history(20)

    if history:

        st.markdown("### 🕘 Previous Questions")

        # -----------------------------------------------------
        # CLEAR HISTORY
        # -----------------------------------------------------

        if st.button(
            "🗑️ Clear History",
            key="clear_question_history"
        ):

            clear_question_history()

            st.session_state["selected_question"] = ""

            st.rerun()

        # -----------------------------------------------------
        # PREVIOUS QUESTIONS
        # -----------------------------------------------------

        for item in history:

            previous_question = item[1]

            if st.button(
                previous_question,
                key=f"history_{item[0]}"
            ):

                st.session_state["selected_question"] = (
                    previous_question
                )

    # ---------------------------------------------------------
    # QUESTION INPUT
    #
    # IMPORTANT:
    # This stays OUTSIDE "if history"
    # so it remains visible after clearing history.
    # ---------------------------------------------------------

    question = st.text_input(
        "Ask your question",
        value=st.session_state.get(
            "selected_question",
            ""
        ),
        placeholder=(
            "Example: Which location has the highest "
            "energy consumption?"
        ),
        key="ai_question_input"
    )

    # ---------------------------------------------------------
    # ASK AI
    # ---------------------------------------------------------

    if question.strip():

        with st.spinner(
            "Analyzing your utility data..."
        ):

            # Use the same PostgreSQL-backed data shown by the operational panels.
            database_dataframes = [
                dataframe.copy()
                for dataframe in data.values()
                if isinstance(dataframe, pd.DataFrame) and not dataframe.empty
            ]

            ai_dataframe = (
                pd.concat(database_dataframes, ignore_index=True, sort=False)
                if database_dataframes
                else pd.DataFrame()
            )
            data_source = "PostgreSQL dashboard tables"

            # -------------------------------------------------
            # CHECK DATA
            # -------------------------------------------------

            if ai_dataframe.empty:

                st.warning(
                    "No utility data is available "
                    "for the AI Assistant."
                )

                st.stop()

            # -------------------------------------------------
            # CREATE AI DATA CONTEXT
            # -------------------------------------------------

            data_context = ai_dataframe.to_string(
                index=False
            )

            # -------------------------------------------------
            # CREATE DATA SIGNATURE
            # -------------------------------------------------

            data_signature = hashlib.sha256(
                data_context.encode("utf-8")
            ).hexdigest()

            # -------------------------------------------------
            # CHECK PREVIOUS ANSWER
            # -------------------------------------------------

            previous_answer = get_previous_answer(
                question,
                data_signature
            )

            if previous_answer:

                answer = previous_answer

            else:

                # -------------------------------------------------
                # ASK AI USING CURRENT DATA
                # -------------------------------------------------

                try:
                    answer = ask_ai(
                        question,
                        data_context,
                        ai_dataframe
                    )
                except OllamaUnavailableError as error:
                    st.warning(str(error))
                    answer = None

                # Keep older cached AI modules from rendering an offline
                # connection message as if it were a real answer.
                if (
                    isinstance(answer, str)
                    and "ollama" in answer.lower()
                    and (
                        "not running" in answer.lower()
                        or "unavailable" in answer.lower()
                    )
                ):
                    st.warning(
                        "The local AI service is unavailable. "
                        "Start Ollama with `ollama serve` to enable AI answers."
                    )
                    answer = None

                # -------------------------------------------------
                # SAVE QUESTION + ANSWER
                # -------------------------------------------------

                if answer:
                    save_question_history(
                        question,
                        answer,
                        data_signature
                    )

            # -------------------------------------------------
            # DISPLAY ANSWER
            # -------------------------------------------------

            st.markdown(
                "### 🤖 AI Answer"
            )

            if answer:
                st.write(answer)
            else:
                st.info(
                    "No AI answer was generated because the local AI service "
                    "is offline."
                )

            if answer:
                st.caption(
                    f"Answer generated from: {data_source}"
                )

    
