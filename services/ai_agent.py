import os
import logging
import requests
import re
import pandas as pd

from services.config_service import is_enabled


logger = logging.getLogger(__name__)


OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11434",
).rstrip("/")
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE_URL}/api/tags"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
# Keep the interactive chat responsive. Deterministic data questions do not use Ollama;
# this is only the bounded fallback for questions that need natural-language reasoning.
OLLAMA_TIMEOUT = min(float(os.getenv("OLLAMA_TIMEOUT", "3.8")), 3.8)
OLLAMA_OFFLINE_MESSAGE = (
    "The local AI service is unavailable. "
    "Make sure Ollama is running and listening at "
    "http://localhost:11434."
)
OLLAMA_MODEL_MESSAGE = (
    f"Ollama is running, but the model `{OLLAMA_MODEL}` is not available. "
    f"Run `ollama pull {OLLAMA_MODEL}` and try again."
)


class OllamaUnavailableError(RuntimeError):
    """Raised when the local Ollama service cannot be reached."""


# =========================================================
# BASIC HELPERS
# =========================================================

def _clean_text(value):
    return str(value).strip().lower()


def _find_column(df, keywords):

    if df is None or df.empty:
        return None

    for column in df.columns:

        name = _clean_text(column)

        for keyword in keywords:

            if keyword in name:
                return column

    return None


def _check_ollama_health():
    """Confirm Ollama is reachable and the configured model is installed."""
    try:
        health_response = requests.get(OLLAMA_TAGS_URL, timeout=0.8)
        health_response.raise_for_status()
        models = health_response.json().get("models", [])
        installed_models = {
            str(model.get("name", "")) for model in models
        }
        model_names = {name.split(":", 1)[0] for name in installed_models}
        if OLLAMA_MODEL not in installed_models and OLLAMA_MODEL not in model_names:
            raise OllamaUnavailableError(OLLAMA_MODEL_MESSAGE)
    except requests.exceptions.ConnectionError as error:
        raise OllamaUnavailableError(OLLAMA_OFFLINE_MESSAGE) from error
    except requests.exceptions.Timeout as error:
        raise OllamaUnavailableError(OLLAMA_OFFLINE_MESSAGE) from error
    except requests.exceptions.HTTPError as error:
        raise OllamaUnavailableError(OLLAMA_OFFLINE_MESSAGE) from error


def get_ai_status():
    """Return the current status of the local AI service for the UI."""
    try:
        _check_ollama_health()
        return {
            "available": True,
            "message": f"AI diagnostic service is available using model {OLLAMA_MODEL}.",
        }
    except OllamaUnavailableError as exc:
        return {
            "available": False,
            "message": str(exc),
        }
    except Exception as exc:
        return {
            "available": False,
            "message": f"AI diagnostic service is unavailable: {exc}",
        }


def build_ai_context(named_dataframes):
    """Build a compact textual summary for AI analysis from DataFrames."""
    if not named_dataframes:
        return "No utility data is available for analysis."

    sections = []
    for name, dataframe in named_dataframes.items():
        if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
            continue

        preview = dataframe.head(25).copy()
        sections.append(f"DATASET: {name}")
        sections.append(f"Rows: {len(dataframe)} | Columns: {', '.join(map(str, dataframe.columns[:20]))}")
        sections.append(preview.to_string(index=False))
        sections.append("---")

    return "\n".join(sections) if sections else "No utility data is available for analysis."


# =========================================================
# EXTRACT DATASET FROM CONTEXT
#
# IMPORTANT:
# Uploaded data is placed FIRST in priority.
# This prevents the original project data from
# overriding the user's uploaded CSV/Excel data.
# =========================================================

def _extract_best_dataframe(data_context):

    if not data_context:
        return None

    try:

        lines = [
            line.rstrip()
            for line in data_context.splitlines()
            if line.strip()
        ]

        # -------------------------------------------------
        # FIRST PRIORITY:
        # Find the LAST uploaded file section.
        #
        # This is important because app.py adds uploaded
        # files after the original project data.
        # -------------------------------------------------

        uploaded_starts = []

        for i, line in enumerate(lines):

            if "UPLOADED FILE:" in line.upper():
                uploaded_starts.append(i)

        candidate_starts = uploaded_starts

        # -------------------------------------------------
        # FALLBACK:
        # If there is no uploaded file, use project data.
        # -------------------------------------------------

        if not candidate_starts:

            candidate_starts = [
                i
                for i, line in enumerate(lines)
                if line.startswith("---")
            ]

        # -------------------------------------------------
        # Search sections from newest/last to oldest.
        # -------------------------------------------------

        for start_index in reversed(candidate_starts):

            section_lines = []

            for line in lines[start_index + 1:]:

                if line.startswith("---"):
                    break

                section_lines.append(line)

            if not section_lines:
                continue

            # -------------------------------------------------
            # Find a line that looks like a dataframe header.
            # -------------------------------------------------

            for header_index, line in enumerate(section_lines):

                parts = re.split(
                    r"\s{2,}|\t+",
                    line.strip()
                )

                parts = [
                    p.strip()
                    for p in parts
                    if p.strip()
                ]

                if len(parts) < 2:
                    continue

                joined = " ".join(parts).lower()

                useful_columns = [
                    "energy_consumption",
                    "energy consumption",
                    "water_consumption",
                    "water consumption",
                    "solar_generation",
                    "solar generation",
                    "temperature",
                    "unit",
                    "location"
                ]

                if not any(
                    keyword in joined
                    for keyword in useful_columns
                ):
                    continue

                header = parts
                rows = []

                for row_line in section_lines[
                    header_index + 1:
                ]:

                    row_parts = re.split(
                        r"\s{2,}|\t+",
                        row_line.strip()
                    )

                    row_parts = [
                        p.strip()
                        for p in row_parts
                        if p.strip()
                    ]

                    if len(row_parts) >= len(header):

                        rows.append(
                            row_parts[:len(header)]
                        )

                if not rows:
                    continue

                df = pd.DataFrame(
                    rows,
                    columns=header
                )

                df.columns = [
                    str(c).strip().lower()
                    for c in df.columns
                ]

                return df

    except Exception:
        return None

    return None


# =========================================================
# NUMERIC COLUMN CLEANING
# =========================================================

def _clean_numeric_column(df, column):

    if column is None:
        return

    df[column] = (
        df[column]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.extract(
            r"(-?\d+(?:\.\d+)?)",
            expand=False
        )
    )

    df[column] = pd.to_numeric(
        df[column],
        errors="coerce"
    )


# =========================================================
# DETERMINISTIC ANSWERS
#
# Exact calculations are handled by Python.
# Ollama is NOT used for arithmetic.
# =========================================================

def _deterministic_answer(
    question,
    data_context,
    dataframe=None
):

    q = _clean_text(question)

    # -----------------------------------------------------
    # USE THE ACTUAL DATAFRAME FROM APP
    # -----------------------------------------------------

    if (
        isinstance(dataframe, pd.DataFrame)
        and not dataframe.empty
    ):
        df = dataframe.copy()

    else:
        df = None

    
    # -----------------------------------------------------
    # IDENTIFY COLUMNS
    # -----------------------------------------------------

    unit_col = _find_column(
        df,
        [
            "unit",
            "location",
            "site"
        ]
    )

    energy_col = _find_column(
        df,
        [
            "energy_consumption",
            "energy consumption",
            "daily_kwh",
            "kwh",
            "energy"
        ]
    )

    water_col = _find_column(
        df,
        [
            "water_consumption",
            "water consumption",
            "water",
            "liters"
        ]
    )

    solar_col = _find_column(
        df,
        [
            "solar_generation",
            "solar generation",
            "solar"
        ]
    )

    temperature_col = _find_column(
        df,
        [
            "temperature_c",
            "temperature"
        ]
    )

    # -----------------------------------------------------
    # CLEAN NUMERIC COLUMNS
    # -----------------------------------------------------

    for column in [
        energy_col,
        water_col,
        solar_col,
        temperature_col
    ]:

        _clean_numeric_column(
            df,
            column
        )

    # =====================================================
    # ENERGY
    # =====================================================

    if energy_col:

        # -------------------------------------------------
        # TOTAL ENERGY
        # -------------------------------------------------

        if (
            "energy" in q
            and (
                "total" in q
                or "overall" in q
            )
            and (
                "consumption" in q
                or "consumed" in q
            )
        ):

            total = df[energy_col].sum()

            return (
                f"The total energy consumption is "
                f"{total:,.0f} kWh."
            )

        # -------------------------------------------------
        # MOST ENERGY
        # -------------------------------------------------

        if (
            "energy" in q
            and (
                "most" in q
                or "highest" in q
                or "maximum" in q
            )
        ):

            idx = df[energy_col].idxmax()

            value = df.loc[
                idx,
                energy_col
            ]

            if unit_col:

                unit = df.loc[
                    idx,
                    unit_col
                ]

                return (
                    f"{unit} consumed the most energy, "
                    f"with {value:,.0f} kWh."
                )

            return (
                f"The highest energy consumption was "
                f"{value:,.0f} kWh."
            )

        # -------------------------------------------------
        # LEAST ENERGY
        # -------------------------------------------------

        if (
            "energy" in q
            and (
                "least" in q
                or "lowest" in q
                or "minimum" in q
            )
        ):

            idx = df[energy_col].idxmin()

            value = df.loc[
                idx,
                energy_col
            ]

            if unit_col:

                unit = df.loc[
                    idx,
                    unit_col
                ]

                return (
                    f"{unit} consumed the least energy, "
                    f"with {value:,.0f} kWh."
                )

            return (
                f"The lowest energy consumption was "
                f"{value:,.0f} kWh."
            )

    # =====================================================
    # WATER
    # =====================================================

    if water_col:

        # -------------------------------------------------
        # TOTAL WATER
        # -------------------------------------------------

        if (
            "water" in q
            and (
                "total" in q
                or "overall" in q
            )
        ):

            total = df[water_col].sum()

            return (
                f"The total water consumption is "
                f"{total:,.0f} liters."
            )

        # -------------------------------------------------
        # MOST WATER
        # -------------------------------------------------

        if (
            "water" in q
            and (
                "most" in q
                or "highest" in q
                or "maximum" in q
            )
        ):

            idx = df[water_col].idxmax()

            value = df.loc[
                idx,
                water_col
            ]

            if unit_col:

                unit = df.loc[
                    idx,
                    unit_col
                ]

                return (
                    f"{unit} had the highest water "
                    f"consumption, at "
                    f"{value:,.0f} liters."
                )

    # =====================================================
    # SOLAR
    # =====================================================

    if solar_col:

        # -------------------------------------------------
        # TOTAL SOLAR
        # -------------------------------------------------

        if (
            "solar" in q
            and (
                "total" in q
                or "overall" in q
            )
        ):

            total = df[solar_col].sum()

            return (
                f"The total solar generation is "
                f"{total:,.0f} kWh."
            )

        # -------------------------------------------------
        # MOST SOLAR
        # -------------------------------------------------

        if (
            "solar" in q
            and (
                "most" in q
                or "highest" in q
                or "maximum" in q
            )
        ):

            idx = df[solar_col].idxmax()

            value = df.loc[
                idx,
                solar_col
            ]

            if unit_col:

                unit = df.loc[
                    idx,
                    unit_col
                ]

                return (
                    f"{unit} had the highest solar "
                    f"generation, at "
                    f"{value:,.0f} kWh."
                )

    # =====================================================
    # TEMPERATURE
    # =====================================================

    if temperature_col:

        # -------------------------------------------------
        # HIGHEST TEMPERATURE
        # -------------------------------------------------

        if (
            "temperature" in q
            and (
                "highest" in q
                or "maximum" in q
                or "hottest" in q
            )
        ):

            idx = df[temperature_col].idxmax()

            value = df.loc[
                idx,
                temperature_col
            ]

            if unit_col:

                unit = df.loc[
                    idx,
                    unit_col
                ]

                return (
                    f"{unit} had the highest "
                    f"temperature, at "
                    f"{value:,.1f} °C."
                )

            return (
                f"The highest temperature was "
                f"{value:,.1f} °C."
            )

    return None


def _question_measure_column(question, dataframe):
    """Choose an actual numeric measure from the supplied application data."""
    if dataframe is None or dataframe.empty:
        return None
    question = _clean_text(question)
    candidates = []
    if "solar" in question or "generation" in question:
        candidates.extend(["generation_kwh", "solar_generation_kwh", "daily_kwh", "kwh"])
    elif "water" in question:
        candidates.extend(["water_consumption_liters", "water_consumption", "water", "liters"])
    elif "air" in question:
        candidates.extend(["total_m3", "air_consumption", "compressed_air"])
    elif "power" in question or "energy" in question or "consumption" in question:
        candidates.extend(["energy_consumption_kwh", "daily_kwh", "kwh", "kw"])
    candidates.extend(["daily_kwh", "generation_kwh", "energy_consumption_kwh", "kwh", "total_m3", "value"])
    return next((column for column in candidates if column in dataframe.columns), None)


def _question_route(question, conversation_context=""):
    """Classify the current question without allowing prior answers to drive it."""
    question_text = _clean_text(question)
    context_text = _clean_text(conversation_context)
    is_follow_up = (
        question_text in {"why", "why?", "what about it", "what about that", "what should we do", "what should we do about it"}
        or question_text.startswith("what about ")
    )

    if is_follow_up and context_text:
        previous_questions = re.findall(r"user:\s*(.+)", context_text)
        if previous_questions:
            question_text = f"{previous_questions[-1]} {question_text}"

    contains = lambda *terms: any(re.search(rf"\b{re.escape(term)}\b", question_text) for term in terms)
    if "transformer" in question_text and "loading" in question_text:
        intent = "transformer_status"
    elif contains("count", "many", "number"):
        intent = "count"
    elif contains("why", "cause", "reason", "anomaly", "anomalies"):
        intent = "diagnostic"
    elif any(term in question_text for term in ("should we", "what should", "what do", "recommend", "reduce")):
        intent = "recommendation"
    elif contains("predict", "forecast", "tomorrow") or "likely to happen" in question_text:
        intent = "prediction"
    elif contains("trend", "increase", "decrease", "changed", "change"):
        intent = "trend"
    elif contains("least", "lowest", "minimum"):
        intent = "lowest_consumption"
    elif contains("highest", "most", "maximum", "top"):
        intent = "highest_consumption"
    elif contains("total", "overall", "sum"):
        intent = "total_consumption"
    elif contains("average", "mean"):
        intent = "average_consumption"
    else:
        intent = "general_data_question"

    if "solar" in question_text or "generation" in question_text:
        metric_terms = ("generation_kwh", "solar_generation_kwh", "daily_kwh", "kwh")
    elif "water" in question_text:
        metric_terms = ("water_consumption_liters", "water_consumption", "water", "liters")
    elif "air" in question_text:
        metric_terms = ("total_m3", "air_consumption", "compressed_air")
    elif "loading" in question_text:
        metric_terms = ("loading_percent",)
    elif "power" in question_text:
        metric_terms = ("kw", "daily_kwh", "kwh", "energy_consumption_kwh")
    else:
        metric_terms = ("energy_consumption_kwh", "daily_kwh", "kwh", "kw")

    if "transformer" in question_text:
        entity = "transformer"
    elif "line" in question_text:
        entity = "line"
    elif "solar" in question_text:
        entity = "solar_location"
    elif "location" in question_text:
        entity = "location"
    else:
        entity = None

    time_phrase = next(
        (phrase for phrase in ("yesterday", "today", "last month", "this month") if phrase in question_text),
        None,
    )
    return {
        "intent": intent,
        "metric_terms": metric_terms,
        "entity": entity,
        "time": time_phrase,
        "question_text": question_text,
    }


def _filter_question_period(dataframe, route):
    """Apply a requested period to dated rows; return data unchanged when undated."""
    if dataframe is None or dataframe.empty or not route.get("time"):
        return dataframe.copy() if isinstance(dataframe, pd.DataFrame) else dataframe

    date_column = next(
        (column for column in ("date", "datetime", "timestamp", "log_date") if column in dataframe.columns),
        None,
    )
    if date_column is None:
        return dataframe.copy()

    result = dataframe.copy()
    dates = pd.to_datetime(result[date_column], errors="coerce")
    available_dates = dates.dropna()
    if available_dates.empty:
        return result.iloc[0:0]

    reference = available_dates.max().normalize()
    period = route["time"]
    if period == "today":
        mask = dates.dt.normalize() == reference
    elif period == "yesterday":
        mask = dates.dt.normalize() == reference - pd.Timedelta(days=1)
    elif period == "this month":
        mask = (dates.dt.year == reference.year) & (dates.dt.month == reference.month)
    else:
        previous = reference.to_period("M") - 1
        mask = (dates.dt.year == previous.year) & (dates.dt.month == previous.month)
    return result.loc[mask.fillna(False)].copy()


def _question_label_column(dataframe, entity):
    preferred = {
        "line": ("line_name", "location", "location_name", "source", "unit"),
        "transformer": ("transformer", "location", "location_name", "unit"),
        "solar_location": ("source", "location", "location_name", "unit"),
        "location": ("location", "location_name", "source", "unit"),
    }
    candidates = preferred.get(entity, ("location", "location_name", "source", "utility", "transformer", "unit"))
    selected = next((column for column in candidates if column in dataframe.columns), None)
    if selected:
        return selected
    return next(
        (
            column for column in dataframe.columns
            if pd.api.types.is_string_dtype(dataframe[column])
        ),
        None,
    )


def _answer_matches_route(answer, route):
    """Reject a response that clearly ignored the routed analysis mode."""
    if not answer:
        return False
    if "insufficient" in answer.lower() or "could not find" in answer.lower():
        return True
    markers = {
        "highest_consumption": ("highest", "consumption"),
        "lowest_consumption": ("lowest", "consumption"),
        "total_consumption": ("total",),
        "average_consumption": ("average",),
        "trend": ("trend", "increased", "decreased", "stable"),
        "diagnostic": ("diagnostic", "hypothesis", "cause"),
        "recommendation": ("recommended", "action", "investigate"),
        "prediction": ("prediction", "baseline", "historical"),
        "transformer_status": ("loading", "%"),
    }
    required = markers.get(route["intent"])
    return required is None or any(marker in answer.lower() for marker in required)


def _question_specific_answer(question, dataframe, conversation_context=""):
    """Answer the current routed question from the supplied evidence."""
    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
        return None
    route = _question_route(question, conversation_context)
    question_text = route["question_text"]
    measure_column = next(
        (
            column for column in route["metric_terms"]
            if column in dataframe.columns
            and pd.to_numeric(dataframe[column], errors="coerce").notna().any()
        ),
        None,
    )
    if measure_column is None:
        question_words = set(re.findall(r"[a-z0-9_]+", question_text))
        numeric_columns = [
            column for column in dataframe.columns
            if pd.to_numeric(dataframe[column], errors="coerce").notna().any()
        ]
        measure_column = next(
            (
                column for column in numeric_columns
                if set(re.findall(r"[a-z0-9_]+", str(column).lower())) & question_words
            ),
            None,
        )
    if measure_column is None:
        return None
    working = _filter_question_period(dataframe, route)
    working[measure_column] = pd.to_numeric(working[measure_column], errors="coerce")
    working = working.dropna(subset=[measure_column])
    if working.empty:
        return "## Insufficient data\n\nNo rows match the requested time period or metric."

    label_column = _question_label_column(working, route["entity"])
    unit = "kWh" if measure_column in {"daily_kwh", "kwh", "energy_consumption_kwh", "generation_kwh"} else "units"
    if measure_column == "kw":
        unit = "kW"
    if measure_column == "loading_percent":
        unit = "%"
    if measure_column in {"total_m3", "air_consumption"}:
        unit = "m³"
    if measure_column in {"water_consumption_liters", "water_consumption", "water", "liters"}:
        unit = "liters"

    grouped = working.groupby(label_column)[measure_column].sum().sort_values(ascending=False) if label_column else None
    intent = route["intent"]

    # Direct lookups are answered from the matching uploaded/database row,
    # rather than asking the language model to infer a value from a preview.
    if label_column and any(term in question_text for term in ("what is", "value", "reading", "how much", "show")):
        matching_labels = [
            label for label in working[label_column].dropna().astype(str).unique()
            if label.lower() in question_text
        ]
        if matching_labels:
            selected_rows = working[working[label_column].astype(str).isin(matching_labels)]
            numeric_values = selected_rows.select_dtypes(include="number").columns
            if len(numeric_values):
                details = "; ".join(
                    f"{column.replace('_', ' ')}: {selected_rows.iloc[0][column]:,.2f}"
                    for column in numeric_values
                    if pd.notna(selected_rows.iloc[0][column])
                )
                return (
                    f"## Answer\n\n**{matching_labels[0]}**: {details}.\n\n"
                    f"### 📚 Data Evidence\n\nRecords analyzed: **{len(selected_rows)}**"
                )

    if label_column and intent in {"highest_consumption", "lowest_consumption"}:
        ordered = grouped if intent == "highest_consumption" else grouped.sort_values()
        selected = ordered.head(5)
        title = "Highest Consumption" if intent == "highest_consumption" else "Lowest Consumption"
        rows = "\n".join(f"| {name} | {value:,.2f} {unit} |" for name, value in selected.items())
        return (
            f"## Answer\n\n**{selected.index[0]}** recorded the "
            f"{'highest' if intent == 'highest_consumption' else 'lowest'} value at **{selected.iloc[0]:,.2f} {unit}**.\n\n"
            f"### 📊 {title}\n\n| {label_column.title()} | Value |\n|---|---:|\n{rows}\n\n"
            f"### 📚 Data Evidence\n\nPeriod: **{route['time'] or 'available data'}**\nRecords analyzed: **{len(working)}**\nMeasure: `{measure_column}`"
        )

    if intent == "total_consumption":
        return (
            f"## Answer\n\nTotal **{measure_column.replace('_', ' ')}**: **{working[measure_column].sum():,.2f} {unit}**.\n\n"
            f"### 📚 Data Evidence\n\nRecords analyzed: **{len(working)}**\nMeasure: `{measure_column}`"
        )

    if intent == "average_consumption":
        return (
            f"## Answer\n\nAverage **{measure_column.replace('_', ' ')}**: **{working[measure_column].mean():,.2f} {unit}**.\n\n"
            f"### 📚 Data Evidence\n\nRecords analyzed: **{len(working)}**\nMeasure: `{measure_column}`"
        )

    if intent == "trend":
        date_column = next((column for column in ("date", "datetime", "timestamp", "log_date") if column in working.columns), None)
        if date_column:
            dates = pd.to_datetime(working[date_column], errors="coerce")
            trend = working.assign(_date=dates).dropna(subset=["_date"]).groupby("_date")[measure_column].sum().sort_index()
            if len(trend) >= 2:
                change = trend.iloc[-1] - trend.iloc[0]
                direction = "increased" if change > 0 else "decreased" if change < 0 else "remained stable"
                return (
                    f"## Answer\n\nThe measured value **{direction}** over the available period.\n\n"
                    f"### 📈 Trend\n\n- First value: **{trend.iloc[0]:,.2f} {unit}**\n- Latest value: **{trend.iloc[-1]:,.2f} {unit}**\n- Change: **{change:,.2f} {unit}**\n\n"
                    f"### 📚 Data Evidence\n\nPeriod: **{trend.index.min().date()} to {trend.index.max().date()}**\nRecords analyzed: **{len(working)}**"
                )
        return "## Insufficient historical data\n\nThere is not enough dated history to calculate a reliable trend."

    if intent == "count":
        count_column = _question_label_column(working, route["entity"])
        if count_column is None:
            return "## Insufficient data\n\nNo location or asset column is available for this count."
        count = working[count_column].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
        subject = "solar locations" if "solar" in question_text else count_column.replace("_", " ")
        return f"## Answer\n\nThere are **{count} distinct {subject}** in the available data.\n\n### 📚 Data Evidence\n\nColumn: `{count_column}`\nRecords analyzed: **{len(working)}**"

    if intent == "diagnostic":
        if label_column and grouped is not None and not grouped.empty:
            subject = grouped.index[0]
            return (
                f"## Answer\n\nThe available data shows **{subject}** as the largest contributor at **{grouped.iloc[0]:,.2f} {unit}**.\n\n"
                "### 🔍 Diagnostic Analysis\n\nThis is an observed relationship, not proof of causation. The supplied snapshot does not include enough target, alert, environmental, or prior-period evidence to confirm why it occurred.\n\n"
                "### 💡 Hypothesis\n\nInvestigate operating duration, load allocation, and equipment readings for the identified asset."
            )
        return "## Insufficient diagnostic evidence\n\nThe available data has no asset or comparison signal to support a causal explanation."

    if intent == "recommendation":
        subject = grouped.index[0] if grouped is not None and not grouped.empty else "the highest measured contributor"
        return (
            f"## Answer\n\n### ⚡ Recommended Actions\n\n"
            f"1. Verify the latest meter and operating status for **{subject}**.\n"
            "2. Compare its load with the immediately preceding period and check active alerts.\n"
            "3. Investigate only after confirming the measurement and operating conditions.\n\n"
            "### 📚 Evidence\n\nRecommendations are limited to the supplied measurements; no unobserved cause is presented as fact."
        )

    if intent == "prediction":
        date_column = next((column for column in ("date", "datetime", "timestamp", "log_date") if column in working.columns), None)
        days = pd.to_datetime(working[date_column], errors="coerce").dt.normalize().nunique() if date_column else 0
        if days < 7:
            return f"## Insufficient historical data\n\nA reliable prediction needs at least 7 dated days; only {days} are available."
        daily = working.assign(_day=pd.to_datetime(working[date_column], errors="coerce").dt.date).groupby("_day")[measure_column].sum()
        return f"## Prediction\n\nThe next-day baseline is **{daily.tail(7).mean():,.2f} {unit}**, based on a seven-day moving average.\n\nHistorical basis: **{days} dated days**. This is a transparent baseline, not a certainty estimate."

    if intent == "transformer_status" and "loading_percent" in working.columns:
        loading = pd.to_numeric(working["loading_percent"], errors="coerce").dropna()
        if not loading.empty:
            index = loading.idxmax()
            label = working.loc[index, label_column] if label_column else "Transformer"
            return f"## Answer\n\n**{label}** has the highest recorded loading at **{loading.loc[index]:,.2f}%**.\n\n### 📚 Data Evidence\n\nRecords analyzed: **{len(loading)}**\nMeasure: `loading_percent`"

    return None


def _analytical_answer(question, dataframe):
    """Return evidence-based analytical lenses when the supplied data supports them."""
    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
        return None
    question_text = _clean_text(question)
    operational_terms = (
        "energy", "power", "solar", "generation", "consumption", "water", "air",
        "transformer", "utility", "environment", "temperature", "humidity", "alert",
        "anomal", "target", "trend", "predict", "forecast", "recommend", "why",
    )
    if not any(term in question_text for term in operational_terms):
        return None

    measure_column = _question_measure_column(question_text, dataframe)
    if measure_column is None:
        return "Insufficient data available to answer this reliably.\n\nData evidence\n----------------\nNo numeric measure matching the question was found in the available application data."

    working = dataframe.copy()
    working[measure_column] = pd.to_numeric(working[measure_column], errors="coerce")
    working = working.dropna(subset=[measure_column])
    if working.empty:
        return "Insufficient data available to answer this reliably.\n\nData evidence\n----------------\nThe matching measure contains no usable numeric values."

    label_column = next((column for column in ("location", "source", "utility", "transformer", "unit") if column in working.columns), None)
    date_column = next((column for column in ("date", "datetime", "timestamp", "log_date") if column in working.columns), None)
    if date_column:
        working[date_column] = pd.to_datetime(working[date_column], errors="coerce")
        valid_dates = working[date_column].dropna()
    else:
        valid_dates = pd.Series(dtype="datetime64[ns]")

    target_column = next((column for column in (f"{measure_column}_target", "target", "target_value") if column in working.columns), None)
    total = float(working[measure_column].sum())
    average = float(working[measure_column].mean())
    minimum = float(working[measure_column].min())
    maximum = float(working[measure_column].max())
    sections = ["UTILITY INTELLIGENCE ANALYSIS", "===============================", f"Measure: {measure_column}"]
    sections.extend([
        "\nDESCRIPTIVE",
        "-----------",
        f"Records analyzed: {len(working)}",
        f"Total: {total:,.2f}",
        f"Average: {average:,.2f}",
        f"Minimum: {minimum:,.2f}",
        f"Maximum: {maximum:,.2f}",
    ])
    if valid_dates.size:
        sections.append(f"Data period: {valid_dates.min().date()} to {valid_dates.max().date()}")
    if label_column:
        grouped = working.groupby(label_column)[measure_column].sum().sort_values(ascending=False)
        if not grouped.empty:
            sections.append(f"Highest location/source: {grouped.index[0]} ({grouped.iloc[0]:,.2f})")

    if target_column:
        working[target_column] = pd.to_numeric(working[target_column], errors="coerce")
        target = float(working[target_column].mean()) if working[target_column].notna().any() else None
        if target is not None and target != 0:
            deviation = average - target
            sections.extend(["\nTARGET VS ACTUAL", "----------------", f"Average target: {target:,.2f}", f"Average actual: {average:,.2f}", f"Deviation: {deviation:,.2f} ({deviation / target * 100:,.2f}%)"])

    diagnostic_requested = any(term in question_text for term in ("why", "cause", "anomal", "above target", "abnormal"))
    if diagnostic_requested:
        sections.extend(["\nDIAGNOSTIC", "----------"])
        if target_column and target is not None:
            status = "above" if average > target else "within or below"
            sections.append(f"Observed issue: average actual is {status} the available target.")
            sections.append("Evidence: target and actual values were calculated from the supplied data.")
        else:
            sections.append("Insufficient evidence for a causal diagnosis: no target column or causal signal was supplied.")
        sections.extend(["\nHYPOTHESIS", "----------", "No causal hypothesis is presented without supporting equipment, alert, environmental, or comparison evidence."])

    predictive_requested = any(term in question_text for term in ("predict", "forecast", "tomorrow", "likely"))
    if predictive_requested:
        sections.extend(["\nPREDICTIVE", "----------"])
        distinct_days = valid_dates.dt.date.nunique() if valid_dates.size else 0
        if distinct_days < 7:
            sections.append(f"Insufficient historical data for a reliable prediction. Available history: {distinct_days} day(s). Minimum required: 7 days.")
        else:
            daily = working.assign(_day=working[date_column].dt.date).groupby("_day")[measure_column].sum()
            window = daily.tail(7)
            sections.append(f"Seven-day baseline: {window.mean():,.2f}")
            sections.append("Prediction method: transparent seven-day moving average; uncertainty is not quantified.")

    prescriptive_requested = any(term in question_text for term in ("recommend", "should", "action", "do about"))
    if prescriptive_requested:
        sections.extend(["\nPRESCRIPTIVE", "------------"])
        if label_column:
            sections.append(f"Investigate the highest contributing {label_column}: {working.groupby(label_column)[measure_column].sum().idxmax()}.")
        else:
            sections.append("Review the measured values and confirm the operating target before taking action.")
        sections.append("These actions are limited to evidence present in the supplied data.")

    sections.extend(["\nDATA EVIDENCE", "------------", f"Source rows analyzed: {len(working)}", f"Columns available: {', '.join(map(str, working.columns[:20]))}"])
    return "\n".join(sections)


# =========================================================
# MAIN AI FUNCTION
# =========================================================

def ask_ai(question, data_context, dataframe=None, conversation_context=""):

    # -----------------------------------------------------
    # ADMIN AI CHECK
    # -----------------------------------------------------

    if not is_enabled(
        "ai_enabled",
        default=True
    ):

        return (
            "The AI Agent has been disabled "
            "by the administrator."
        )

    route = _question_route(question, conversation_context)
    logger.info(
        "AI pipeline question=%r intent=%s metric=%s time=%s entity=%s rows=%s",
        question,
        route["intent"],
        ",".join(route["metric_terms"]),
        route["time"],
        route["entity"],
        len(dataframe) if isinstance(dataframe, pd.DataFrame) else 0,
    )

    # -----------------------------------------------------
    # EXACT NUMERICAL QUESTIONS
    #
    # Python handles these first.
    # -----------------------------------------------------

    question_specific = _question_specific_answer(
        question, dataframe, conversation_context
    )
    if question_specific:
        if not _answer_matches_route(question_specific, route):
            logger.warning("AI pipeline rejected irrelevant routed answer intent=%s", route["intent"])
            return "## Insufficient data\n\nThe available evidence could not support the requested analysis."
        logger.info("AI pipeline answer generated intent=%s chars=%s", route["intent"], len(question_specific))
        return question_specific

    deterministic = _deterministic_answer(
        question,
        data_context,
        dataframe
    )

    if deterministic:
        return deterministic

    # -----------------------------------------------------
    # OLLAMA FOR GENERAL QUESTIONS
    # -----------------------------------------------------

    prompt = f"""
You are the Utility Intelligence AI assistant.

Answer ONLY using the utility data supplied below.

STRICT RULES:

1. Answer the exact question asked.
2. Use only the supplied utility data.
3. Never invent numbers.
4. Never invent dates.
5. Never invent locations.
6. Never assume information that is not present.
7. If calculations are required, use the supplied data.
8. If the information is not available, say:
"I could not find this information in the available data."
9. Do not answer a different question.
10. Do not use outside knowledge.

UTILITY DATA:
----------------
{data_context}
----------------

CONVERSATION CONTEXT (supporting context only):
{conversation_context}

CURRENT USER QUESTION (primary task):
{question}

Return ONLY the answer.
"""

    try:
        _check_ollama_health()

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "seed": 42,
                    "num_ctx": 2048,
                    "num_predict": 512,
                }
            },
            timeout=OLLAMA_TIMEOUT
        )

        response.raise_for_status()

        result = response.json()

        answer = result.get(
            "response",
            ""
        ).strip()

        if not answer:

            return (
                "I could not generate an answer "
                "from the available data."
            )

        if not _answer_matches_route(answer, route):
            logger.warning("AI pipeline rejected irrelevant LLM answer intent=%s", route["intent"])
            return "I could not find a reliable answer for that question in the available data."

        logger.info("AI pipeline answer generated intent=%s chars=%s", route["intent"], len(answer))
        return answer

    except requests.exceptions.ConnectionError as error:
        raise OllamaUnavailableError(OLLAMA_OFFLINE_MESSAGE) from error

    except requests.exceptions.Timeout:

        return (
            "The local AI model is taking too long to respond. "
            "Try again, or use a smaller Ollama model such as `qwen2.5:3b`."
        )

    except Exception as e:

        return f"AI error: {e}"