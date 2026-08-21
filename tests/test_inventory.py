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
