# DistribuSense

DistribuSense is an FMCG distribution intelligence MVP. It combines sales, inventory, supplier, and retailer data to help distribution operators answer three questions:

1. What is selling, where, and at what margin?
2. Which products are likely to run out or expire soon?
3. What should be reordered, in what quantity, and why?

The project is intentionally explainable. Forecasts expose their selected baseline and error metrics, while inventory recommendations expose the demand, stock, safety stock, reorder point, and MOQ assumptions behind each decision.

## What is included

- A reproducible sample dataset with 60 staple-grocery products across 6 focused categories, 6 brands, 8 suppliers, 60 retailers, 365 days of sales, and current-stock inventory.
- Streamlit workspaces for executive metrics, sales, demand forecasting, inventory, reorder planning, retailer analytics, supplier analytics, and alerts. The Executive Dashboard presents its seven KPIs in a responsive two-column grid.
- A FastAPI service with JWT authentication, product/sales/inventory reads, demand forecasts, reorder recommendation generation, recommendation decisions, and CSV upload validation. Product and sales responses retain numeric money fields and add Indian Rupee formatted fields for display clients.
- SQLAlchemy models for users, products, suppliers, retailers, sales, current inventory stock, forecasts, reorder recommendations, and alerts.
- CSV ingestion for suppliers, products, retailers, inventory, and sales. Uploads are validated before processing and are rolled back if a row cannot be ingested.
- SQLite as the default local database and PostgreSQL support through `psycopg2`.
- A shared Indian Rupee formatter for dashboard KPIs, tables, chart labels, and API display fields.
- Pytest coverage for forecasting preparation and metrics, current-stock inventory calculations, analytics aggregations, currency formatting, validation, authentication, and ingestion behavior.

## Architecture

```text
												 +----------------------+
												 |   Streamlit dashboard |
												 | app/dashboard/       |
												 +----------+-----------+
																		|
									 data loading      | shared service functions
							data/sample/*.csv    |
																		v
												 +----------------------+
												 |    app/services/     |
												 | analytics             |
												 | forecasting          |
												 | inventory             |
												 | recommendations      |
												 | ingestion/validation |
												 | auth                  |
												 +----------+-----------+
																		^
																		| calls services and DB sessions
												 +----------+-----------+
												 |       FastAPI        |
												 |     app/api/main.py  |
												 +----------+-----------+
																		|
												 +----------v-----------+
												 | SQLAlchemy + database |
												 | app/models/domain.py  |
												 | SQLite / PostgreSQL   |
												 +----------------------+
```

### Responsibilities

| Area | Responsibility |
| --- | --- |
| `app/dashboard/` | Streamlit presentation layer. Calls data-loading, analytics, forecasting, inventory, supplier, and formatting services and renders interactive views. |
| `app/api/` | FastAPI HTTP boundary, request validation, authentication dependencies, response shaping, and CSV upload handling. |
| `app/services/` | Framework-independent business logic and data preparation. This is where analytics, currency formatting, sample-data loading, forecasting, inventory policy, recommendation generation, supplier summaries, authentication, and ingestion rules live. |
| `app/models/` | SQLAlchemy persistence models and relationships. |
| `app/database/` | Engine and session setup. Database selection comes from `DATABASE_URL`. |
| `scripts/` | Generate fixtures, create tables, and create or reset a user. |
| `alembic/` | Migration configuration. The current initialization script creates tables directly for local development. |
| `tests/` | Unit and integration tests for the service and API slices. |

### Data paths

There are two deliberately separate paths in this MVP:

- **Dashboard and read-only API data:** the dashboard and `/products`, `/sales`, and `/inventory` endpoints use CSV files from `data/sample/` through their data-loading/service boundaries. Generate these files before starting either consumer.
- **Operational database data:** authentication, CSV uploads, reorder recommendations, and recommendation decisions use SQLAlchemy and the configured database. Generating CSVs does not automatically load them into the database; use `/data/upload` or an ingestion service call for that.

## Forecasting and replenishment logic

### Demand forecasting

`forecast_daily` prepares a daily series, filling missing dates with zero demand. It evaluates these baselines on an 80/20 chronological holdout:

- naive last-value forecast
- seven-day moving average
- additive damped-trend exponential smoothing

The model with the lowest holdout MAE is selected. The API and dashboard expose the selected model, MAE, RMSE, forecast values, and an uncertainty band. The implementation is a practical MVP baseline, not a production-trained model registry.

### Inventory recommendations

For each active product, the recommendation service:

1. Builds the recent daily demand history from persisted sales.
2. Calculates available stock as current stock minus reserved stock.
3. Calculates safety stock from demand variability, lead time, and configured safety-stock days.
4. Calculates the reorder point as lead-time demand plus safety stock.
5. Targets the larger of the reorder point and a 30-day demand target plus safety stock.
6. Subtracts available and incoming stock, then rounds a positive order up to the supplier MOQ.

The result includes a risk level, estimated stockout date, recommended quantity, and a human-readable reason. Recommendations can be approved, modified, or rejected through the API.

### Currency display

All user-facing currency is displayed as Indian Rupees using lakh/crore grouping through `app/services/formatting.py`. Examples include `₹1,23,456` and `₹1,00,00,000`. The formatter is used by dashboard KPI cards, revenue charts, profitability/retailer tables, and formatted API fields. Raw numeric API money fields remain available for calculations and backward compatibility.

## Project layout

```text
app/
	api/main.py                 FastAPI routes
	config.py                   Environment-backed settings
	dashboard/streamlit_app.py Streamlit application
	database/session.py         SQLAlchemy engine and sessions
	models/domain.py            Database entities
	services/                   Business logic
	services/data_loading.py    Sample CSV loading and preparation
	services/formatting.py      Shared Indian Rupee formatting
	services/suppliers.py       Supplier summaries
data/sample/                  Generated CSV fixtures
scripts/                      Local setup and data utilities
tests/                        Automated tests
alembic/                      Migration configuration
```

## Requirements

- Python 3.12 or newer is recommended. The Docker image uses Python 3.12.
- Docker Desktop is needed only for the containerized/PostgreSQL workflow.
- Python dependencies are listed in `requirements.txt`.

## Quick start: local SQLite

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/generate_sample_data.py
python scripts/init_db.py
```

Set a JWT secret before using the login-protected API or dashboard:

```powershell
$env:JWT_SECRET = "replace-with-a-long-local-secret"
python scripts/create_user.py operator
```

Start the dashboard:

```powershell
python -m streamlit run app/dashboard/streamlit_app.py
```

Open `http://localhost:8501`, then sign in with the user created above.

Start the API in a second terminal:

```powershell
python -m uvicorn app.api.main:app --reload
```

The API is available at `http://localhost:8000`. Interactive OpenAPI documentation is at `http://localhost:8000/docs` and the health check is `http://localhost:8000/health`.

`run.py` is a shortcut for starting the Streamlit dashboard with the active Python interpreter:

```powershell
python run.py
```

## Docker Compose: PostgreSQL, API, and dashboard

Docker Compose expects a root `.env` file because the API and Streamlit services use `env_file: .env`, and PostgreSQL requires `POSTGRES_PASSWORD`.

Create one locally:

```dotenv
POSTGRES_PASSWORD=change-this-local-password
DATABASE_URL=postgresql+psycopg2://distribusense:change-this-local-password@postgres:5432/distribusense
JWT_SECRET=change-this-to-a-long-random-secret
```

Start the stack:

```powershell
docker compose up --build
```

The host ports are:

| Service | URL |
| --- | --- |
| PostgreSQL | `localhost:5433` |
| FastAPI | `http://localhost:8001` |
| Streamlit | `http://localhost:8502` |

The Compose services share the image built by `Dockerfile`. The API listens on container port 8000 and the dashboard on container port 8501; Compose maps them to the host ports above. Database tables still need to be initialized with `python scripts/init_db.py` in an environment that has the same `DATABASE_URL`, or with an equivalent migration/init command inside the API container.

## Configuration

Settings are loaded by `pydantic-settings` from environment variables and an optional `.env` file. Names are case-insensitive.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `DistribuSense` | Application name. |
| `ENVIRONMENT` | `development` | Environment label. |
| `DATABASE_URL` | `sqlite:///./distribusense.db` | SQLAlchemy connection URL. |
| `JWT_SECRET` | empty | Required for login and protected API routes. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_MINUTES` | `480` | Token lifetime. |
| `SAFETY_STOCK_DAYS` | `3` | Safety-stock demand buffer. |
| `STOCKOUT_WARNING_DAYS` | `14` | Stockout warning threshold. |
| `SLOW_MOVING_DAYS` | `30` | Slow-moving inventory threshold. |

Keep `.env`, database files, and secrets out of source control. Passwords are stored as PBKDF2-SHA256 hashes; plaintext passwords are not persisted.

## API overview

Protected routes require `Authorization: Bearer <token>` after logging in.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health check. |
| `POST` | `/auth/login` | Exchange username and password for a JWT. |
| `GET` | `/products` | Read sample product data. |
| `GET` | `/sales?product_id=SKU-001` | Read sales, optionally filtered by product. |
| `GET` | `/inventory` | Read sample inventory data. |
| `GET` | `/forecast/{product_id}?horizon=30` | Forecast 1 to 60 days of demand. |
| `POST` | `/data/upload` | Validate and ingest a CSV dataset. Use `dataset_type` of `sales`, `products`, `inventory`, `retailers`, or `suppliers`. |
| `POST` | `/reorder-recommendations/generate` | Generate or refresh active-product recommendations. |
| `GET` | `/reorder-recommendations?status=generated` | List recommendations, optionally by status. |
| `PATCH` | `/reorder-recommendations/{id}` | Approve, modify, or reject a recommendation. |

Money-bearing `/products` and `/sales` records retain numeric fields such as `purchase_price` and `selling_price`, and include formatted display fields such as `purchase_price_formatted` and `selling_price_formatted` using Indian Rupee grouping.

Example login and authenticated request:

```powershell
$login = Invoke-RestMethod http://localhost:8000/auth/login -Method Post -ContentType 'application/json' -Body '{"username":"operator","password":"your-password"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod http://localhost:8000/products -Headers $headers
```

For the complete request and response schemas, use `/docs`.

## CSV upload contracts

CSV headers are validated before ingestion. Required columns are:

| Dataset | Required columns |
| --- | --- |
| `sales` | `date`, `product_id`, `retailer_id`, `quantity`, `selling_price` |
| `products` | `product_id`, `name`, `brand`, `category`, `purchase_price`, `selling_price`, `supplier_id` |
| `inventory` | `product_id`, `quantity`, `reserved_quantity` |
| `retailers` | `retailer_id`, `name`, `location`, `credit_limit`, `payment_terms` |
| `suppliers` | `supplier_id`, `name`, `lead_time`, `minimum_order_quantity` |

Products, suppliers, and retailers are upserted by their business identifiers. Duplicate sales are skipped. Inventory rows require an existing product, and sales require existing products and retailers. A failed row rolls back the complete upload.

The generated examples in `data/sample/` are the easiest way to see valid column names and data types.

## Testing

Install the requirements, then run:

```powershell
python -m pytest -q
```

The suite covers current-stock inventory formulas and stockout behavior, forecast preparation and metrics, profitability and analytics aggregations, Indian currency formatting, CSV validation, transactional ingestion, JWT login, authenticated API access, and recommendation lifecycle behavior.

## Current MVP boundaries

This repository does not yet implement purchase-order creation or approval beyond recommendation status, payment processing, delivery tracking, role-based permissions, a production model registry, or a background job scheduler. Alembic is configured, but local initialization currently uses `scripts/init_db.py` and migrations are not yet part of the normal startup flow.
