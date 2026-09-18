# DistribuSense

DistribuSense is an FMCG distribution intelligence application for a wholesale distributor. It combines sales, inventory, supplier, retailer, payment, forecasting, and operational data into one explainable dashboard and API.

The application helps an operator answer:

- What is selling, where, and at what margin?
- Which products may run out soon?
- What should be reordered, in what quantity, and why?
- Which retailers are overdue or exceeding their credit exposure?
- Which supplier balances need attention?
- What operational alerts require action today?

This is an MVP designed around transparent business rules, reproducible sample data, and service-layer calculations that can be tested independently of Streamlit and FastAPI.

## Problem Statement

FMCG distributors typically manage several connected workflows:

- Daily sales across named retailers and counter sales.
- Inventory replenishment with supplier lead times and minimum order quantities.
- Demand variability and stockout risk.
- Retailer credit sales, payment terms, partial payments, and overdue balances.
- Supplier purchases and installment payments.
- Operating expenses and business performance reporting.

When these workflows are managed in disconnected spreadsheets, it is difficult to see margin, cash exposure, stockout risk, or the actions that should be taken next. DistribuSense provides a single operational view while keeping the calculations visible and explainable.

## Solution

DistribuSense provides:

1. A Streamlit dashboard for daily commercial, inventory, finance, and alert monitoring.
2. A FastAPI service for authentication, reads, forecasting, CSV uploads, and reorder recommendation decisions.
3. A SQLAlchemy data model for operational persistence.
4. A reproducible generator for realistic FMCG sample data.
5. Independent service functions for analytics, forecasting, inventory policy, receivables, supplier balances, validation, formatting, and recommendations.
6. Automated tests covering business logic, data validation, authentication, ingestion, and API behavior.

## Implemented Features

### Dashboard workspaces

The Streamlit dashboard contains these workspaces:

- **Executive Dashboard**: revenue, orders, units sold, inventory value, gross margin, active retailers, outstanding receivables, stockout risk, and a daily revenue/units chart.
- **Sales Analytics**: category filters, revenue by category, product profitability, gross profit, gross margin, and units sold.
- **Demand Forecast**: product-level historical demand, selectable forecast horizon, selected baseline model, MAE, RMSE, forecast values, and uncertainty band.
- **Inventory Intelligence**: current stock, daily demand, reorder point, days remaining, risk, and recommended order quantity.
- **Reorder Planning**: inventory recommendations filtered to products requiring an order.
- **Retailer Analytics**: retailer revenue and order summaries plus outstanding receivables, payment totals, days overdue, credit exposure, and risk status. Receivables can be sorted by balance or risk.
- **Operating Expenses**: expense filters, date range filtering, monthly expense trend, expense category totals, and detailed expense records.
- **Supplier Analytics**: supplier product coverage and purchase/payment balances with supplier status.
- **Alert Center**: live stockout, slow-moving, retailer credit, and supplier balance alerts with severity filtering and colored status badges.

### Sales and channels

- Named-retailer sales are treated as credit sales.
- Each named-retailer sale receives a due date based on the retailer's `payment_terms_days`.
- Counter sales have no retailer, are treated as cash sales, and have no due date.
- Sales include quantity, selling price, purchase cost, product, retailer, date, and channel information in the generated data.

### Retailer accounts receivable

Retailers have:

- `credit_limit`
- `payment_terms_days`
- Credit sales with calculated due dates
- Installment and partial payments through `retailer_payments`

`retailer_outstanding_balances` calculates, as of a selected date:

- Total credit sales
- Total payments received
- Outstanding balance
- Days overdue on the oldest unpaid sale
- Credit utilization ratio
- Risk status: `Current`, `Due Soon`, `Overdue`, or `High Risk`

Payments are applied to the oldest credit sales first, which makes installment behavior and aging meaningful.

### Supplier payables

Supplier balances use purchase invoices and supplier payments to calculate:

- Total purchases
- Payments made
- Outstanding balance
- Typical monthly purchases
- Balance ratio
- Supplier status: `Green`, `Yellow`, or `Red`

### Alert Center

Alerts are assembled by the `build_alerts` service function rather than being calculated in the Streamlit page. The current alert categories are:

- **Stockout**: critical and high-risk products from the inventory position logic, including the estimated stockout date.
- **Slow-moving**: products whose last sale is older than the configured slow-moving threshold.
- **Retailer credit**: retailers with `Overdue` or `High Risk` receivables.
- **Supplier balance**: suppliers with a `Red` balance status.

Each alert contains severity, category, entity name, and a concise explanation. The dashboard supports filtering by `Critical`, `High`, and `Warning` severity.

Status values throughout Inventory Intelligence, Retailer Analytics, Supplier Analytics, and Alert Center use the same colored badge renderer:

- Green: `Healthy`, `Current`, `Green`
- Yellow: `Warning`, `Due Soon`
- Orange: `High`, `Overdue`, `High Risk`, `Yellow`
- Red: `Critical`, `Red`

## Forecasting and Replenishment

### Demand forecasting

`forecast_daily` prepares a daily demand series and fills missing dates with zero demand. It evaluates chronological 80/20 holdout performance for:

- Naive last-value forecast
- Seven-day moving average
- Additive damped-trend exponential smoothing

The model with the lowest holdout MAE is selected. Forecast results expose the model name, MAE, RMSE, forecast values, and uncertainty bounds.

### Inventory policy

For each active product, the inventory service:

1. Builds recent daily demand history.
2. Calculates available stock as current stock minus reserved stock.
3. Calculates safety stock from demand variability, lead time, and configured safety-stock days.
4. Calculates the reorder point as lead-time demand plus safety stock.
5. Targets the larger of the reorder point and a 30-day demand target plus safety stock.
6. Subtracts available and incoming stock.
7. Rounds a positive order up to the supplier minimum order quantity.

The resulting inventory position includes risk level, days remaining, estimated stockout date, recommended order quantity, and an explanation.

## Technology Stack

- **Python 3.12**: application language and runtime.
- **Streamlit**: interactive dashboard.
- **FastAPI**: authenticated REST API.
- **SQLAlchemy 2**: ORM and database access.
- **SQLite**: default local database.
- **PostgreSQL 16**: Docker Compose database option.
- **Pandas**: CSV loading, aggregation, and analytical data preparation.
- **NumPy**: reproducible sample-data generation and numerical calculations.
- **Statsmodels**: exponential smoothing forecasting.
- **Scikit-learn**: forecasting metrics and supporting analytical utilities.
- **Plotly**: interactive dashboard charts.
- **Pydantic Settings**: environment-based configuration.
- **python-jose**: JWT access tokens.
- **Passlib**: PBKDF2-SHA256 password hashing.
- **Pytest**: automated tests.
- **Alembic**: migration configuration; local initialization currently uses `create_all`.
- **Docker Compose**: PostgreSQL, API, and dashboard orchestration.

All direct dependencies are listed in `requirements.txt`.

## Architecture

```text
                         +----------------------+
                         | Streamlit dashboard  |
                         | app/dashboard/       |
                         +----------+-----------+
                                    |
                         service functions and CSV reads
                                    v
                         +----------------------+
                         | app/services/        |
                         | analytics            |
                         | accounting           |
                         | forecasting          |
                         | inventory            |
                         | recommendations     |
                         | suppliers            |
                         | ingestion/validation |
                         | auth/formatting      |
                         +----------+-----------+
                                    ^
                                    | service calls and DB sessions
                         +----------+-----------+
                         | FastAPI API          |
                         | app/api/main.py      |
                         +----------+-----------+
                                    |
                         +----------v-----------+
                         | SQLAlchemy models    |
                         | SQLite/PostgreSQL    |
                         +----------------------+
```

### Layer responsibilities

| Layer | Responsibility |
| --- | --- |
| `app/dashboard/` | Streamlit authentication flow, page layout, filters, tables, charts, and status presentation. |
| `app/api/` | FastAPI routes, request validation, JWT dependencies, response shaping, and CSV upload boundary. |
| `app/services/` | Framework-independent business logic and data preparation. |
| `app/models/` | SQLAlchemy entities for users, catalog, sales, inventory, purchases, payments, recommendations, and alerts. |
| `app/database/` | Engine, declarative base, and session dependency. |
| `scripts/` | Sample-data generation, database initialization, and user creation. |
| `data/sample/` | Reproducible CSV fixtures consumed by the dashboard and read-only API. |
| `tests/` | Unit, service, ingestion, authentication, and API integration tests. |

## Data Model

The main persisted entities are:

- `User`: username, password hash, active flag.
- `Supplier`: supplier code, name, lead time, minimum order quantity, contact email.
- `Product`: SKU, name, category, brand, supplier, purchase price, selling price, active flag.
- `Purchase`: supplier invoice and total amount.
- `PurchaseItem`: product-level purchase quantity, unit cost, and amount.
- `Retailer`: retailer code, name, location, credit limit, payment terms.
- `Sale`: date, due date, product, optional retailer, quantity, selling price, and purchase cost.
- `InventoryStock`: quantity and reserved quantity by product.
- `Expense`: dated operating expense and payment method.
- `SupplierPayment`: supplier payment date, amount, and method.
- `RetailerPayment`: retailer payment date, amount, and method.
- `Forecast`: persisted forecast values and model metadata.
- `ReorderRecommendation`: inventory recommendation, quantity, reason, status, and decision metadata.
- `Alert`: alert severity, category, title, explanation, entity, and creation timestamp.

## Sample Data

`python scripts/generate_sample_data.py` creates deterministic fixtures using seed `42` for the fiscal year April 1, 2024 through March 31, 2025. The generated dataset contains:

- 60 products
- 6 product categories
- 6 fictional brands
- 8 suppliers
- 60 retailers
- 365 days of sales activity
- Named-retailer credit sales and counter/cash sales
- Retailer credit limits and payment terms
- Retailer installment payments with normal, late, and chronically overdue behavior
- Supplier purchases and payments
- Inventory snapshots
- Monthly operating expenses

The generated files are:

```text
data/sample/
  products.csv
  sales.csv
  inventory.csv
  retailers.csv
  suppliers.csv
  purchases.csv
  purchase_items.csv
  supplier_payments.csv
  retailer_payments.csv
  expenses.csv
```

Sample CSVs are fixtures, not a replacement for production ingestion or a production data warehouse.

## Project Layout

```text
app/
  api/main.py                 FastAPI routes
  config.py                   Environment-backed settings
  dashboard/streamlit_app.py Streamlit application
  database/session.py         SQLAlchemy engine and sessions
  models/domain.py            SQLAlchemy entities
  services/
    accounting.py             Expenses and supplier balance views
    analytics.py              Sales, receivables, supplier balances, alerts
    auth.py                   Password hashing and JWT authentication
    data_loading.py           Sample CSV loading
    forecasting.py            Demand history, models, and forecast metrics
    formatting.py             Indian Rupee formatting
    ingestion.py              Transactional CSV ingestion
    inventory.py              Stock, reorder point, and stockout logic
    recommendations.py        Reorder recommendation lifecycle
    suppliers.py              Supplier summaries
    validation.py             CSV contracts and validation
data/sample/                  Generated CSV fixtures
scripts/
  create_user.py              Create or reset a dashboard/API user
  generate_sample_data.py     Generate reproducible data
  init_db.py                  Create database tables
tests/                        Automated test suite
alembic/                      Migration configuration
Dockerfile                    Python application image
docker-compose.yml            PostgreSQL, API, and dashboard stack
run.py                        Local Streamlit shortcut
requirements.txt              Python dependencies
```

## Requirements

- Python 3.12 or newer recommended.
- Docker Desktop is optional and required only for the Compose/PostgreSQL workflow.
- PowerShell examples below assume Windows.

## Local Setup

From the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/generate_sample_data.py
python scripts/init_db.py
```

Set a JWT secret and create a user:

```powershell
$env:JWT_SECRET = "replace-with-a-long-local-secret"
python scripts/create_user.py operator
```

Start the dashboard:

```powershell
python -m streamlit run app/dashboard/streamlit_app.py
```

Open `http://localhost:8501` and sign in with the user created above. `python run.py` is an equivalent local shortcut.

Start the API in another terminal:

```powershell
python -m uvicorn app.api.main:app --reload
```

The API is available at `http://localhost:8000`. OpenAPI documentation is available at `http://localhost:8000/docs`, and the health endpoint is `http://localhost:8000/health`.

## Docker Compose

Create a root `.env` file:

```dotenv
POSTGRES_PASSWORD=change-this-local-password
DATABASE_URL=postgresql+psycopg2://distribusense:change-this-local-password@postgres:5432/distribusense
JWT_SECRET=change-this-to-a-long-random-secret
```

Start the stack:

```powershell
docker compose up --build
```

Host ports:

| Service | URL or port |
| --- | --- |
| PostgreSQL | `localhost:5433` |
| FastAPI | `http://localhost:8001` |
| Streamlit | `http://localhost:8502` |

The API listens on container port 8000 and Streamlit listens on container port 8501. Initialize tables with `python scripts/init_db.py` in an environment using the same `DATABASE_URL`, or run the equivalent command inside the API container.

## Configuration

Settings are loaded case-insensitively from environment variables and an optional `.env` file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `DistribuSense` | Application name. |
| `ENVIRONMENT` | `development` | Environment label. |
| `DATABASE_URL` | `sqlite:///./distribusense.db` | SQLAlchemy connection URL. |
| `JWT_SECRET` | empty | Required for login and protected routes. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_MINUTES` | `480` | Token lifetime. |
| `SAFETY_STOCK_DAYS` | `3` | Safety-stock demand buffer. |
| `STOCKOUT_WARNING_DAYS` | `14` | Stockout warning threshold. |
| `SLOW_MOVING_DAYS` | `30` | Last-sale age threshold for slow-moving alerts. |
| `SUPPLIER_BALANCE_CRITICAL_RATIO` | `2.0` | Supplier balance ratio at which status becomes Red. |
| `RETAILER_DUE_SOON_DAYS` | `7` | Days before due date for Due Soon classification. |
| `RETAILER_HIGH_RISK_OVERDUE_DAYS` | `30` | Overdue age threshold for High Risk. |
| `RETAILER_HIGH_RISK_CREDIT_RATIO` | `1.0` | Outstanding-to-credit-limit ratio for High Risk. |

Keep `.env`, database files, and secrets out of source control. Passwords are stored as PBKDF2-SHA256 hashes; plaintext passwords are not persisted.

## API Overview

Protected routes require `Authorization: Bearer <token>` after login.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health check. |
| `POST` | `/auth/login` | Exchange username and password for a JWT. |
| `GET` | `/products` | Read product sample data and formatted prices. |
| `GET` | `/sales?product_id=SKU-001` | Read sales, optionally filtered by product. |
| `GET` | `/inventory` | Read inventory sample data. |
| `GET` | `/forecast/{product_id}?horizon=30` | Forecast between 1 and 60 days of demand. |
| `POST` | `/data/upload` | Validate and ingest a supported CSV dataset. |
| `POST` | `/reorder-recommendations/generate` | Generate or refresh active-product recommendations. |
| `GET` | `/reorder-recommendations?status=generated` | List recommendations, optionally filtered by status. |
| `PATCH` | `/reorder-recommendations/{id}` | Approve, modify, or reject a recommendation. |

Example authenticated request:

```powershell
$login = Invoke-RestMethod http://localhost:8000/auth/login -Method Post -ContentType 'application/json' -Body '{"username":"operator","password":"your-password"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod http://localhost:8000/products -Headers $headers
```

Use `/docs` for complete request and response schemas.

## CSV Ingestion Contracts

Uploads are validated before processing. Upserts use business identifiers, duplicate sales are skipped, and a failed row rolls back the complete upload.

| Dataset type | Required columns |
| --- | --- |
| `sales` | `date`, `product_id`, `retailer_id`, `quantity`, `selling_price` |
| `products` | `product_id`, `name`, `brand`, `category`, `purchase_price`, `selling_price`, `supplier_id` |
| `inventory` | `product_id`, `quantity`, `reserved_quantity` |
| `retailers` | `retailer_id`, `name`, `location`, `credit_limit`, `payment_terms` or `payment_terms_days` |
| `suppliers` | `supplier_id`, `name`, `lead_time`, `minimum_order_quantity` |
| `expenses` | `expense_id`, `date`, `category`, `description`, `amount`, `payment_method` |
| `supplier_payments` | `payment_id`, `date`, `supplier_id`, `amount`, `payment_method` |
| `retailer_payments` | `payment_id`, `date`, `retailer_id`, `amount`, `payment_method` |
| `purchases` | `purchase_id`, `date`, `supplier_id`, `invoice_reference`, `total_amount` |
| `purchase_items` | `purchase_item_id`, `purchase_id`, `product_id`, `quantity`, `unit_cost`, `amount` |

Products, suppliers, and retailers must exist before dependent sales, inventory, payment, or purchase-item rows are ingested. Named retailer sales resolve the retailer's payment terms and calculate a due date. Counter sales leave the retailer and due date empty.

## Currency and Presentation

User-facing currency uses Indian Rupee formatting with lakh/crore grouping through `app/services/formatting.py`, for example `₹1,23,456` and `₹1,00,00,000`. Numeric money values remain available for calculations and API compatibility. Dashboard status values use shared colored HTML badges rather than emoji-only indicators.

## Testing

Run the full suite from the project root:

```powershell
python -m pytest -q
```

The tests cover:

- Forecast history preparation, model selection, metrics, and horizons.
- Current-stock inventory formulas and stockout risk behavior.
- Reorder-point, safety-stock, MOQ, and recommendation logic.
- Sales, profitability, retailer, supplier, and receivables aggregations.
- Retailer credit due dates, installment payments, and risk classification.
- Sample-data generation and payment behavior.
- Indian Rupee formatting.
- CSV contracts, numeric/date validation, duplicate handling, and transaction rollback.
- Password hashing, JWT authentication, protected API routes, and recommendation lifecycle behavior.

## Data Path Boundaries

The application intentionally has two data paths:

- **Dashboard and read-only API path**: reads generated CSVs from `data/sample/` through the data-loading services.
- **Operational database path**: authentication, uploads, reorder recommendations, and recommendation decisions use SQLAlchemy with the configured database.

Generating sample CSVs does not automatically load every CSV into the database. Use the upload endpoint or call the ingestion service when database persistence is required.

## Current MVP Boundaries

The project does not yet implement purchase-order creation or approval beyond recommendation status, payment processing against a live payment gateway, delivery tracking, role-based permissions, a production model registry, background scheduling, or a full migration startup flow. Alembic is configured, but local table initialization currently uses `scripts/init_db.py` and `Base.metadata.create_all`.

## License and Ownership

This repository is an internal/prototype application. Add the appropriate organizational license and deployment security policy before distributing it outside its intended environment.
