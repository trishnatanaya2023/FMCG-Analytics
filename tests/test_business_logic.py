from datetime import date
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.generate_sample_data as generator
from app.services.analytics import (category_revenue, daily_sales_revenue, product_profitability,
                                    retailer_summary, supplier_outstanding_balances)
from app.services.data_loading import load_sample_data
from app.services.suppliers import supplier_product_counts
from app.services.forecasting import (build_product_demand_history, calculate_accuracy_metrics,
                                      latest_daily_demand, normalize_forecast_horizon)
from app.services.inventory import (
    InventoryPolicy,
    calculate_inventory_value,
    calculate_inventory_position,
    calculate_reorder_point,
    calculate_safety_stock,
)
from app.services.validation import validate_csv
from app.services.formatting import format_currency


def test_reorder_point_normal_case():
    """Checks demand multiplied by lead time plus safety stock in the standard case."""
    assert calculate_reorder_point(20, 5, 80) == 180


def test_reorder_point_zero_lead_time():
    """Checks that immediate replenishment depends only on safety stock."""
    assert calculate_reorder_point(20, 0, 80) == 80


def test_reorder_point_zero_demand():
    """Checks that no demand does not create a demand-driven reorder quantity."""
    assert calculate_reorder_point(0, 10, 0) == 0


def test_safety_stock_constant_demand():
    """Checks that stable demand uses the configured safety-stock day buffer."""
    assert calculate_safety_stock([10, 10, 10], lead_time_days=5, safety_stock_days=3) == 30


def test_safety_stock_variable_demand():
    """Checks that demand variability increases safety stock beyond the mean buffer."""
    assert calculate_safety_stock([0, 10], lead_time_days=5, safety_stock_days=3) == 31


def test_stockout_with_zero_current_stock():
    """Checks that zero available inventory is critical and predicts stockout immediately."""
    position = calculate_inventory_position(0, 0, 0, [10, 10], 300, InventoryPolicy(5), date(2026, 1, 1))
    assert position.days_remaining == 0
    assert position.estimated_stockout_date == date(2026, 1, 1)
    assert position.risk_level == "Critical"


def test_stockout_with_zero_average_demand():
    """Checks that zero demand returns no finite stockout date instead of dividing by zero."""
    position = calculate_inventory_position(100, 0, 0, [0, 0], 0, InventoryPolicy(5), date(2026, 1, 1))
    assert position.days_remaining is None
    assert position.estimated_stockout_date is None
    assert position.risk_level == "Healthy"


def test_forecast_accuracy_metrics_known_values():
    """Checks hand-verifiable MAE, RMSE, and MAPE values on fixed predictions."""
    metrics = calculate_accuracy_metrics([100, 200, 300], [90, 220, 330])
    assert metrics["mae"] == 20
    assert math.isclose(metrics["rmse"], math.sqrt(1400 / 3), rel_tol=1e-9)
    assert math.isclose(metrics["mape"], 10, rel_tol=1e-9)


def test_format_currency_uses_indian_grouping():
    assert format_currency(60987) == "₹60,987"
    assert format_currency(123456) == "₹1,23,456"
    assert format_currency(10000000) == "₹1,00,00,000"
    assert format_currency(2390.5, 2) == "₹2,390.50"


def test_forecasting_preparation_fills_dates_and_normalizes_horizon():
    sales = pd.DataFrame([
        {"date": "2026-01-01", "product_id": "A", "quantity": 2},
        {"date": "2026-01-03", "product_id": "A", "quantity": 4},
        {"date": "2026-01-03", "product_id": "B", "quantity": 8},
    ])
    history = build_product_demand_history(sales, "A")
    assert history.tolist() == [2, 0, 4]
    assert latest_daily_demand(sales, days=2).loc["A"] == 3
    assert normalize_forecast_horizon(-2) == 1
    assert normalize_forecast_horizon(100) == 60


def test_product_profitability_includes_zero_sales_product():
    """Checks revenue, cost, profit, margin, and retention of an unsold catalog product."""
    products = pd.DataFrame([
        {"product_id": "A", "name": "A", "brand": "Brand", "category": "Biscuits"},
        {"product_id": "B", "name": "B", "brand": "Brand", "category": "Biscuits"},
    ])
    sales = pd.DataFrame([
        {"product_id": "A", "quantity": 10, "selling_price": 15, "purchase_cost": 9},
    ])
    result = product_profitability(sales, products).set_index("product_id")
    assert result.loc["A", "revenue"] == 150
    assert result.loc["A", "purchase_cost"] == 90
    assert result.loc["A", "gross_profit"] == 60
    assert result.loc["A", "gross_margin_pct"] == 40
    assert result.loc["B", "revenue"] == 0
    assert result.loc["B", "gross_margin_pct"] == 0


def test_inventory_value_uses_current_stock():
    inventory = pd.DataFrame([{"product_id": "A", "quantity": 10, "reserved_quantity": 0}])
    products = pd.DataFrame([{"product_id": "A", "name": "A", "purchase_price": 4}])
    assert calculate_inventory_value(inventory, products) == 40


def test_analytics_aggregations():
    sales = pd.DataFrame([
        {"date": "2026-01-01", "category": "Biscuits", "retailer_id": "R1", "product_id": "A", "quantity": 2, "selling_price": 10},
        {"date": "2026-01-01", "category": "Pulses & Dal", "retailer_id": "R1", "product_id": "B", "quantity": 3, "selling_price": 5},
        {"date": "2026-01-02", "category": "Biscuits", "retailer_id": "R2", "product_id": "A", "quantity": 1, "selling_price": 10},
    ])
    assert daily_sales_revenue(sales).to_dict("records") == [
        {"date": "2026-01-01", "revenue": 35, "units": 5},
        {"date": "2026-01-02", "revenue": 10, "units": 1},
    ]
    assert category_revenue(sales).set_index("category").loc["Biscuits", "revenue"] == 30
    retailer = retailer_summary(sales).set_index("retailer_id")
    assert retailer.loc["R1", "units"] == 5
    assert retailer.loc["R1", "average_order_value"] == 35
    assert supplier_product_counts(pd.DataFrame({"supplier_id": ["S1", "S1", "S2"]})).to_dict("records") == [
        {"supplier_id": "S1", "products_supplied": 2},
        {"supplier_id": "S2", "products_supplied": 1},
    ]


def test_load_sample_data_joins_purchase_cost(tmp_path):
    pd.DataFrame([{"product_id": "P1", "purchase_price": 7, "name": "Product", "category": "C", "brand": "B", "supplier_id": "S1"}]).to_csv(tmp_path / "products.csv", index=False)
    pd.DataFrame([{"date": "2026-01-01", "product_id": "P1", "retailer_id": "R1", "quantity": 2, "selling_price": 10}]).to_csv(tmp_path / "sales.csv", index=False)
    pd.DataFrame([{"product_id": "P1", "quantity": 4, "reserved_quantity": 0}]).to_csv(tmp_path / "inventory.csv", index=False)
    pd.DataFrame([{"retailer_id": "R1"}]).to_csv(tmp_path / "retailers.csv", index=False)
    pd.DataFrame([{"supplier_id": "S1"}]).to_csv(tmp_path / "suppliers.csv", index=False)
    _, sales, _, _, _ = load_sample_data(tmp_path)
    assert sales.loc[0, "purchase_cost"] == 7


def test_supplier_outstanding_balance_uses_dated_purchase_reductions():
    purchases = pd.DataFrame([
        {"date": "2024-04-10", "supplier_id": "S1", "total_amount": 70},
        {"date": "2024-05-10", "supplier_id": "S1", "total_amount": 35},
    ])
    payments = pd.DataFrame([
        {"date": "2024-04-30", "supplier_id": "S1", "amount": 20},
        {"date": "2024-06-01", "supplier_id": "S1", "amount": 10},
    ])

    result = supplier_outstanding_balances(purchases, payments, "2024-05-31").iloc[0]

    assert result["purchases"] == 105
    assert result["payments"] == 20
    assert result["outstanding_balance"] == 85


def test_sample_generator_uses_fy_2024_2025_and_counter_sales(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    generator.generate()

    products = pd.read_csv(tmp_path / "products.csv")
    sales = pd.read_csv(tmp_path / "sales.csv")

    assert {"pack_size", "units_per_pack"}.issubset(products.columns)
    assert sales["date"].min() == "2024-04-01"
    assert sales["date"].max() == "2025-03-31"
    assert set(sales["sale_channel"].dropna().unique()) <= {"Retailer", "Counter"}
    assert (sales["retailer_id"].isna() | sales["retailer_id"].astype(str).str.strip().eq("")).sum() > 0


def test_sample_generator_creates_expense_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    generator.generate()

    expenses = pd.read_csv(tmp_path / "expenses.csv")

    assert {"expense_id", "date", "category", "description", "amount", "payment_method"}.issubset(expenses.columns)
    assert expenses["date"].min() == "2024-04-01"
    assert expenses["date"].max() == "2025-03-31"
    assert (expenses["category"] == "Rent").sum() >= 12
    assert expenses["amount"].gt(0).all()
    assert expenses["payment_method"].notna().all()


def test_sample_generator_creates_supplier_payments(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    generator.generate()

    payments = pd.read_csv(tmp_path / "supplier_payments.csv")

    assert {"payment_id", "date", "supplier_id", "amount", "payment_method"}.issubset(payments.columns)
    assert payments["date"].min() >= "2024-04-01"
    assert payments["date"].max() <= "2025-03-31"
    assert payments["amount"].gt(0).all()
    assert payments["supplier_id"].nunique() >= 6


def valid_sales_frame():
    return pd.DataFrame({
        "date": ["2026-01-01"], "product_id": ["SKU-001"], "retailer_id": ["RET-001"],
        "quantity": [10], "selling_price": [25.0],
    })


def test_csv_validation_accepts_valid_file():
    """Checks that a correctly shaped sales CSV is accepted for ingestion."""
    result = validate_csv(valid_sales_frame(), "sales")
    assert result.valid is True
    assert result.errors == []


def test_csv_validation_rejects_missing_required_column():
    """Checks that missing business keys are reported before ingestion."""
    frame = valid_sales_frame().drop(columns="retailer_id")
    result = validate_csv(frame, "sales")
    assert result.valid is False
    assert "retailer_id" in result.errors[0]


def test_csv_validation_rejects_wrong_data_type():
    """Checks that non-numeric quantities cannot enter inventory calculations."""
    frame = valid_sales_frame().assign(quantity=["ten"])
    result = validate_csv(frame, "sales")
    assert result.valid is False
    assert "quantity" in " ".join(result.errors)


def test_csv_validation_rejects_negative_quantity():
    """Checks that negative sales are rejected as invalid operational data."""
    frame = valid_sales_frame().assign(quantity=[-1])
    result = validate_csv(frame, "sales")
    assert result.valid is False
    assert "negative" in " ".join(result.errors)


def test_csv_validation_rejects_empty_file():
    """Checks that an empty upload produces a useful validation error."""
    result = validate_csv(pd.DataFrame(), "sales")
    assert result.valid is False
    assert result.errors == ["CSV file is empty"]