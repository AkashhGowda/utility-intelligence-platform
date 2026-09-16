import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow the nested Streamlit entry point to use the project-level services.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from ingest_solar_excel import render_excel_uploader
from services.db import get_connection


st.set_page_config(
	page_title="Utility Intelligence",
	page_icon="☀️",
	layout="wide",
	initial_sidebar_state="expanded",
)


def show_dashboard() -> None:
	"""Render the application overview."""
	st.title("Utility Intelligence")
	st.subheader("Solar monitoring workspace")
	st.write(
		"Upload operational Excel data, store it in PostgreSQL, and inspect "
		"the latest records from one workspace."
	)

	metric_columns = st.columns(3)
	metric_columns[0].metric("Data source", "PostgreSQL")
	metric_columns[1].metric("Database", "solar_monitoring")
	metric_columns[2].metric("Upload format", ".xlsx")


def show_data_explorer() -> None:
	"""Display a preview of rows stored by the Excel uploader."""
	st.title("Data Explorer")
	row_limit = st.slider("Rows to preview", min_value=5, max_value=100, value=20)

	connection = get_connection()
	try:
		dataframe = pd.read_sql_query(
			f"SELECT * FROM solar_data LIMIT {row_limit}",
			connection,
		)
	except Exception as error:
		st.info(f"No uploaded data is available yet: {error}")
	else:
		if dataframe.empty:
			st.info("The solar_data table is empty.")
		else:
			st.dataframe(dataframe, use_container_width=True, hide_index=True)
	finally:
		connection.close()


def show_database_status() -> None:
	"""Check connectivity to the configured PostgreSQL database."""
	st.title("Database Status")
	try:
		connection = get_connection()
		try:
			with connection.cursor() as cursor:
				cursor.execute("SELECT current_database(), version();")
				database_name, version = cursor.fetchone()
		finally:
			connection.close()
	except Exception as error:
		st.error(f"Database connection failed: {error}")
		return

	st.success("Connected to PostgreSQL")
	st.write(f"**Database:** {database_name}")
	st.caption(version)


def main() -> None:
	"""Run the Streamlit application."""
	with st.sidebar:
		st.title("Utility Intelligence")
		section = st.radio(
			"Navigate",
			options=[
				"Dashboard",
				"Data Upload",
				"Data Explorer",
				"Database Status",
			],
		)
		st.divider()
		st.caption("Solar monitoring and diagnostics")

	if section == "Dashboard":
		show_dashboard()
	elif section == "Data Upload":
		st.title("Data Upload")
		st.write("Upload an Excel workbook to insert its rows into PostgreSQL.")
		render_excel_uploader()
	elif section == "Data Explorer":
		show_data_explorer()
	else:
		show_database_status()


if __name__ == "__main__":
	main()
