# DistribuSense

DistribuSense is an FMCG distribution intelligence MVP that turns sales, inventory, supplier, and retailer data into explainable operational decisions.

## MVP capabilities

- Reproducible synthetic dataset: 50 products, 10 categories, 5 brands, 5 suppliers, 100 retailers, 12 months of daily sales, and batch inventory.
- Sales trends, category performance, profitability, and retailer rollups.
- Time-series-aware demand forecasting with naive, moving-average, and exponential-smoothing baselines selected by holdout MAE.
- Safety stock, reorder point, days of inventory, estimated stockout date, risk levels, and MOQ-rounded reorder recommendations.
- FEFO expiry queue with value-at-risk.
- FastAPI read endpoints and CSV upload validation.
- PostgreSQL-ready SQLAlchemy schema with SQLite local fallback.

## Architecture

`app/services` contains business logic, `app/ml` is reserved for model adapters, `app/models` owns persistence, `app/api` exposes replaceable backend endpoints, and `app/dashboard` is the Streamlit presentation layer. The dashboard loads the same pure services used by API consumers.

## Run locally

```powershell
C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe -m pip install -r requirements.txt
C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe scripts/generate_sample_data.py
C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe scripts/init_db.py
C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe -m streamlit run app/dashboard/streamlit_app.py
```

API: `C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe -m uvicorn app.api.main:app --reload`

For PostgreSQL, copy `.env.example` to `.env` and set `DATABASE_URL=postgresql+psycopg2://...`. Run `docker compose up -d postgres` for the local database service.

## Configuration and security

Business thresholds are environment-configurable in `.env`: safety-stock days, stockout warning days, slow-moving days, and expiry thresholds. Secrets are never committed. Authentication, full persistence-backed ingestion, purchase-order approval workflow, payments, delivery tracking, and role enforcement are planned follow-up slices; they are not represented as completed functionality in this MVP.

## Tests

Run `python -m pytest -q` after installing the requirements. Current tests cover the reorder-point business example and stockout calculation. Add database/API integration tests as persistence-backed ingestion is expanded.
