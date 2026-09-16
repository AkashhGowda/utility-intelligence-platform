import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        database=os.getenv("DB_NAME", "solar_monitoring"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD") or "admin123",
        port=os.getenv("DB_PORT", "5432")
    )