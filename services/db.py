import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


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
        database=_setting("DB_NAME", "solar_monitoring"),
        user=_setting("DB_USER", "postgres"),
        password=_setting("DB_PASSWORD", ""),
        port=_setting("DB_PORT", "5432")
    )