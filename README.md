# Solar Utility Intelligence Platform

Streamlit dashboard for plant performance, telemetry, generation trends, utility assets, and power anomalies.

## Run locally

1. Create a PostgreSQL database and apply `common_database.sql`.
2. Set database configuration in `.env` or the deployment provider's secrets.
3. Start the app:

```bash
streamlit run app.py
```

The application reads operational dashboard data from PostgreSQL. Excel and CSV files are ingestion inputs only; they are not used as a dashboard fallback.

## Deployment configuration

Use either a single PostgreSQL connection string:

```text
DATABASE_URL=postgresql://user:password@host:5432/database
```

or configure all of these variables:

```text
DB_HOST=...
DB_PORT=5432
DB_NAME=solar_monitoring
DB_USER=...
DB_PASSWORD=...
```

For Streamlit Community Cloud, add the variables under **Settings > Secrets**. The app entrypoint is `app.py`, and dependencies are listed in `requirements.txt`.

Important: a deployed app cannot connect to PostgreSQL or Ollama running on your laptop. Use hosted services and paste their connection values into Streamlit Secrets. The default `127.0.0.1` and `localhost:11434` endpoints are intended only for local development.

## Data flow

`Data Upload` parses an Excel or CSV report and persists it to PostgreSQL. The Command Center, Energy, Solar, Transformer, Utilities, Environment, Electrical Quality, Alerts, Reports, and AI views read the persisted database-backed data.
