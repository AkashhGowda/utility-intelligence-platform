import pandas as pd
from pathlib import Path
from datetime import datetime


# =========================================================
# PROJECT PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)


# =========================================================
# LOAD CSV / EXCEL
# =========================================================

def load_file(file):

    filename = file.name.lower()

    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(file)

        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(file)

        else:
            raise ValueError(
                "Unsupported file format. Please upload CSV or Excel."
            )

        return clean_data(df)

    except Exception as e:
        raise ValueError(f"Could not read the file: {e}")


# =========================================================
# CLEAN DATA
# =========================================================

def clean_data(df):

    if df is None:
        raise ValueError("No data was provided.")

    if df.empty:
        raise ValueError("The uploaded file is empty.")

    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")

    df.columns = [
        str(column)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        for column in df.columns
    ]

    df = df.loc[:, ~df.columns.duplicated()]

    date_columns = [
        "date",
        "datetime",
        "timestamp",
        "time"
    ]

    for column in date_columns:
        if column in df.columns:
            df[column] = pd.to_datetime(
                df[column],
                errors="coerce"
            )
            break

    return df


# =========================================================
# VALIDATE DATA
# =========================================================

def validate_data(df):

    errors = []
    warnings = []

    if df is None or df.empty:
        errors.append("Dataset is empty.")
        return errors, warnings

    duplicate_count = int(df.duplicated().sum())

    if duplicate_count > 0:
        warnings.append(
            f"{duplicate_count} duplicate rows found."
        )

    missing = df.isna().sum()
    missing_columns = missing[missing > 0]

    if not missing_columns.empty:
        warnings.append(
            "Missing values found in: "
            + ", ".join(missing_columns.index.tolist())
        )

    possible_date_columns = [
        "date",
        "datetime",
        "timestamp",
        "time"
    ]

    found_date = False

    for column in possible_date_columns:
        if column in df.columns:
            found_date = True
            break

    if not found_date:
        warnings.append(
            "No standard date/time column detected."
        )

    numeric_columns = df.select_dtypes(
        include="number"
    ).columns

    if len(numeric_columns) == 0:
        warnings.append(
            "No numeric columns detected."
        )

    return errors, warnings


# =========================================================
# SAVE UPLOADED DATA
# =========================================================

def save_uploaded_data(df, filename):

    if df is None or df.empty:
        raise ValueError(
            "Cannot save an empty dataset."
        )

    safe_filename = Path(filename).name
    df = clean_data(df)

    output_path = UPLOAD_DIR / safe_filename

    if safe_filename.lower().endswith(".csv"):

        df.to_csv(
            output_path,
            index=False
        )

    elif safe_filename.lower().endswith(
        (".xlsx", ".xls")
    ):

        df.to_excel(
            output_path,
            index=False
        )

    else:

        raise ValueError(
            "Only CSV and Excel files are supported."
        )

    return output_path


# =========================================================
# LOAD SAVED DATA
# =========================================================

def load_saved_data(filename):

    safe_filename = Path(filename).name
    file_path = UPLOAD_DIR / safe_filename

    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: {filename}"
        )

    if file_path.suffix.lower() == ".csv":
        df = pd.read_csv(file_path)

    elif file_path.suffix.lower() in [".xlsx", ".xls"]:
        df = pd.read_excel(file_path)

    else:
        raise ValueError(
            "Unsupported file format."
        )

    return clean_data(df)


# =========================================================
# GET AVAILABLE FILES
# =========================================================

def get_uploaded_files():

    if not UPLOAD_DIR.exists():
        return []

    files = []

    for file in UPLOAD_DIR.iterdir():

        if file.is_file() and file.suffix.lower() in [
            ".csv",
            ".xlsx",
            ".xls"
        ]:
            files.append(file.name)

    return sorted(files)


# =========================================================
# GET FILE INFORMATION
# =========================================================

def get_file_info(filename):

    file_path = UPLOAD_DIR / Path(filename).name

    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: {filename}"
        )

    df = load_saved_data(filename)
    stat = file_path.stat()

    return {
        "filename": file_path.name,
        "rows": len(df),
        "columns": len(df.columns),
        "size_kb": round(stat.st_size / 1024, 2),
        "last_modified": datetime.fromtimestamp(
            stat.st_mtime
        ),
        "column_names": list(df.columns)
    }


# =========================================================
# DATA SUMMARY
# =========================================================

def get_data_summary(df):

    if df is None or df.empty:

        return {
            "rows": 0,
            "columns": 0,
            "column_names": [],
            "missing_values": 0,
            "duplicate_rows": 0
        }

    return {
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
        "missing_values": int(
            df.isna().sum().sum()
        ),
        "duplicate_rows": int(
            df.duplicated().sum()
        )
    }


# =========================================================
# FIND DATE COLUMN
# =========================================================

def find_date_column(df):

    if df is None or df.empty:
        return None

    possible_columns = [
        "date",
        "datetime",
        "timestamp",
        "time"
    ]

    for column in possible_columns:

        if column in df.columns:
            return column

    return None


# =========================================================
# GET DATE RANGE
# =========================================================

def get_date_range(df):

    date_column = find_date_column(df)

    if date_column is None:
        return None, None

    dates = pd.to_datetime(
        df[date_column],
        errors="coerce"
    ).dropna()

    if dates.empty:
        return None, None

    return dates.min(), dates.max()


# =========================================================
# FILTER BY DATE
# =========================================================

def filter_by_date(
    df,
    start_date=None,
    end_date=None
):

    if df is None or df.empty:
        return df

    date_column = find_date_column(df)

    if date_column is None:
        return df

    result = df.copy()

    result[date_column] = pd.to_datetime(
        result[date_column],
        errors="coerce"
    )

    if start_date is not None:

        start_date = pd.to_datetime(start_date)

        result = result[
            result[date_column] >= start_date
        ]

    if end_date is not None:

        end_date = pd.to_datetime(end_date)

        end_date = end_date + pd.Timedelta(days=1)

        result = result[
            result[date_column] < end_date
        ]

    return result


# =========================================================
# DELETE UPLOADED FILE
# =========================================================

def delete_uploaded_file(filename):

    file_path = UPLOAD_DIR / Path(filename).name

    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: {filename}"
        )

    file_path.unlink()

    return True

# =========================================================
# PREPARE DATA FOR AI AGENT
# =========================================================

def dataframe_to_ai_context(df, max_rows=200):
    """
    Convert a DataFrame into a safe text representation
    that can be provided to the AI Agent.
    """

    if df is None or df.empty:
        return "No utility data is currently available."

    # Work on a copy so the original DataFrame is not changed.
    context_df = df.copy()

    # Limit the amount of data sent to the local AI model.
    context_df = context_df.head(max_rows)

    # Convert datetime values into readable strings.
    for column in context_df.columns:

        if pd.api.types.is_datetime64_any_dtype(
            context_df[column]
        ):
            context_df[column] = context_df[column].astype(str)

    # Replace missing values.
    context_df = context_df.fillna("N/A")

    # Convert the DataFrame to text.
    context = context_df.to_string(
        index=False
    )

    return context
# =========================================================
# LOAD ALL EXCEL SHEETS
# =========================================================

def load_excel_sheets(file):
    """
    Load every worksheet from an Excel workbook.

    Returns:
        dict[str, DataFrame]
    """

    if file is None:
        raise ValueError("No Excel file was provided.")

    filename = str(file.name).lower()

    if not filename.endswith((".xlsx", ".xls")):
        raise ValueError(
            "This function supports Excel files only."
        )

    try:

        file.seek(0)

        sheets = pd.read_excel(
            file,
            sheet_name=None
            
        )

        cleaned_sheets = {}

        for sheet_name, dataframe in sheets.items():

            if dataframe is None:
                continue

            if dataframe.empty:
                continue

            cleaned_sheets[sheet_name] = clean_data(
                dataframe
            )

        if not cleaned_sheets:
            raise ValueError(
                "No usable worksheets were found."
            )

        return cleaned_sheets

    except Exception as e:

        raise ValueError(
            f"Could not read Excel workbook: {e}"
        )


def validate_workbook_sheets(workbook_sheets):
    """Summarize every normalized sheet before it is persisted."""
    if not isinstance(workbook_sheets, dict) or not workbook_sheets:
        raise ValueError("No usable workbook sheets were supplied.")

    summaries = []
    for sheet_name, dataframe in workbook_sheets.items():
        errors = []
        warnings = []
        if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
            errors.append("Sheet is empty.")
            row_count = 0
            column_count = 0
            columns = []
        else:
            row_count = len(dataframe)
            column_count = len(dataframe.columns)
            columns = [str(column) for column in dataframe.columns]
            if dataframe.duplicated().any():
                warnings.append(f"{int(dataframe.duplicated().sum())} duplicate rows detected.")
            if dataframe.isna().any().any():
                warnings.append(f"{int(dataframe.isna().sum().sum())} blank values detected.")
            normalized_columns = {str(column).strip().lower() for column in dataframe.columns}
            date_like = any(
                column in normalized_columns
                for column in ("date", "datetime", "timestamp", "time", "log_date")
            )
            if not date_like and not any("/" in column for column in normalized_columns):
                warnings.append("No standard date or timestamp column was detected.")
            numeric_count = len(dataframe.select_dtypes(include="number").columns)
            if numeric_count == 0:
                warnings.append("No numeric columns were detected.")

        status = "ERROR" if errors else "WARNING" if warnings else "VALID"
        summaries.append({
            "Sheet": str(sheet_name),
            "Rows": row_count,
            "Columns": column_count,
            "Detected Columns": ", ".join(columns[:12]),
            "Status": status,
            "Validation": "; ".join(errors + warnings) or "Ready for import",
        })
    return pd.DataFrame(summaries)
    # =========================================================
# SAVE COMPLETE EXCEL WORKBOOK
# =========================================================

def save_uploaded_workbook(workbook_sheets, filename):

    if not isinstance(workbook_sheets, dict):
        raise ValueError(
            "Expected an Excel workbook with multiple sheets."
        )

    if not workbook_sheets:
        raise ValueError(
            "The workbook contains no sheets."
        )

    safe_filename = Path(filename).name

    if not safe_filename.lower().endswith(
        (".xlsx", ".xls")
    ):
        raise ValueError(
            "Only Excel workbooks are supported."
        )

    # Always save as .xlsx so the complete workbook
    # can be stored reliably.
    safe_filename = Path(safe_filename).with_suffix(
        ".xlsx"
    ).name

    output_path = UPLOAD_DIR / safe_filename

    with pd.ExcelWriter(
        output_path,
        engine="openpyxl"
    ) as writer:

        for sheet_name, dataframe in workbook_sheets.items():

            if dataframe is None:
                continue

            if not isinstance(
                dataframe,
                pd.DataFrame
            ):
                continue

            df = dataframe.copy()

            # Remove Excel-generated empty columns.
            df = df.loc[
                :,
                ~df.columns.astype(str)
                .str.lower()
                .str.startswith("unnamed")
            ]

            # Excel sheet names cannot exceed 31 characters.
            clean_sheet_name = str(sheet_name)[:31]

            df.to_excel(
                writer,
                sheet_name=clean_sheet_name,
                index=False
            )

    return output_path

# =========================================================
# LOAD COMPLETE EXCEL WORKBOOK
# =========================================================

def load_saved_workbook(filename):

    safe_filename = Path(filename).name
    file_path = UPLOAD_DIR / safe_filename

    if not file_path.exists():
        raise FileNotFoundError(
            f"File not found: {filename}"
        )

    if file_path.suffix.lower() not in [
        ".xlsx",
        ".xls"
    ]:
        raise ValueError(
            "Only Excel workbooks are supported."
        )

    workbook = pd.read_excel(
        file_path,
        sheet_name=None
    )

    cleaned_workbook = {}

    for sheet_name, dataframe in workbook.items():

        if dataframe is None:
            continue

        if dataframe.empty:
            continue

        dataframe = dataframe.copy()

        # Remove Excel-generated unnamed columns
        dataframe = dataframe.loc[
            :,
            ~dataframe.columns.astype(str)
            .str.lower()
            .str.startswith("unnamed")
        ]

        # Convert mixed object columns to strings where needed
        for column in dataframe.columns:

            if dataframe[column].dtype == "object":

                dataframe[column] = dataframe[column].map(
                    lambda value:
                    str(value).strip()
                    if pd.notna(value)
                    else None
                )

        cleaned_workbook[sheet_name] = clean_data(
            dataframe
        )

    return cleaned_workbook
