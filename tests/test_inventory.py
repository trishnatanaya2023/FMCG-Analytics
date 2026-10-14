from datetime import date
from app.services.inventory import InventoryPolicy, calculate_inventory_position, calculate_reorder_point


def test_reorder_point_business_example():
    assert calculate_reorder_point(20, 5, 80) == 180


def test_stockout_and_reorder_quantity():
    position = calculate_inventory_position(180, 0, 200, [20] * 30, 650, InventoryPolicy(5, 0, 1), date(2026, 1, 1))
    assert position.reorder_point == 100
    assert round(position.days_remaining, 2) == 8.31
    assert position.estimated_stockout_date == date(2026, 1, 10)
    assert position.recommended_order_quantity > 0


def test_forecast_drives_lead_time_and_planning_demand_with_inventory_constraints():
    forecast = [2.0] * 60
    position = calculate_inventory_position(
        current_stock=20,
        reserved_stock=5,
        incoming_stock=3,
        demand_history=[10.0] * 30,
        forecast_demand=sum(forecast[:30]),
        policy=InventoryPolicy(lead_time_days=5, safety_stock_days=0, minimum_order_quantity=10),
        as_of=date(2026, 1, 1),
        forecast_values=forecast,
        forecast_model="Random Forest",
        forecast_source="selected forecast",
    )

    assert position.available_stock == 15
    assert position.lead_time_demand == 10
    assert position.reorder_point == 10
    assert position.planning_horizon_demand == 60
    assert position.recommended_order_quantity == 50
    assert position.forecast_source == "selected forecast"
    assert position.forecast_model == "Random Forest"
    assert "Random Forest" in position.reason


def test_inventory_fallback_keeps_historical_average_calculation():
    position = calculate_inventory_position(
        10, 0, 0, [4.0] * 30, 120, InventoryPolicy(5, 0, 1),
        date(2026, 1, 1),
    )

    assert position.forecast_source == "historical-average fallback"
    assert position.forecast_daily_demand == 4
    assert position.planning_horizon_demand == 120
