from datetime import date
import math
import pandas as pd

from app.services.analytics import product_profitability
from app.services.forecasting import calculate_accuracy_metrics
from app.services.inventory import (
    InventoryPolicy,
    calculate_inventory_position,
    calculate_reorder_point,
    calculate_safety_stock,
)
from app.services.validation import validate_csv


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