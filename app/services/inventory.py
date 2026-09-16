from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

import pandas as pd

from app.config import Settings, get_settings
from app.services.forecasting import latest_daily_demand


@dataclass(frozen=True)
class InventoryPolicy:
    lead_time_days: int
    safety_stock_days: float = 3
    minimum_order_quantity: int = 1


@dataclass(frozen=True)
class InventoryPosition:
    current_stock: int
    reserved_stock: int
    incoming_stock: int
    average_daily_demand: float
    forecast_daily_demand: float
    safety_stock: int
    reorder_point: int
    days_remaining: float | None
    estimated_stockout_date: date | None
    risk_level: str
    recommended_order_quantity: int
    reason: str


def calculate_safety_stock(daily_demand: list[float], lead_time_days: int, safety_stock_days: float = 3) -> int:
    if not daily_demand or lead_time_days < 0:
        return 0
    if len(daily_demand) < 2:
        return ceil(max(daily_demand, default=0) * safety_stock_days)
    mean = sum(daily_demand) / len(daily_demand)
    variance = sum((value - mean) ** 2 for value in daily_demand) / (len(daily_demand) - 1)
    demand_deviation = variance ** 0.5
    return max(0, ceil(demand_deviation * (max(lead_time_days, 1) ** 0.5) + mean * safety_stock_days))


def calculate_reorder_point(average_daily_demand: float, lead_time_days: int, safety_stock: int) -> int:
    return ceil(max(0, average_daily_demand) * max(0, lead_time_days) + max(0, safety_stock))


def calculate_inventory_position(current_stock: int, reserved_stock: int, incoming_stock: int,
                                 demand_history: list[float], forecast_demand: float,
                                 policy: InventoryPolicy, as_of: date | None = None) -> InventoryPosition:
    as_of = as_of or date.today()
    available = max(0, current_stock - reserved_stock)
    average = sum(demand_history) / len(demand_history) if demand_history else 0.0
    daily_forecast = max(0.0, forecast_demand / 30) if forecast_demand else average
    safety = calculate_safety_stock(demand_history, policy.lead_time_days, policy.safety_stock_days)
    reorder_point = calculate_reorder_point(average, policy.lead_time_days, safety)
    days_remaining = available / daily_forecast if daily_forecast > 0 else None
    stockout_date = as_of + timedelta(days=ceil(days_remaining)) if days_remaining is not None else None
    if available <= 0:
        risk = "Critical"
    elif days_remaining is not None and days_remaining <= 3:
        risk = "Critical"
    elif days_remaining is not None and days_remaining <= policy.lead_time_days:
        risk = "High Risk"
    elif days_remaining is not None and days_remaining <= 14:
        risk = "Warning"
    else:
        risk = "Healthy"
    target_stock = max(reorder_point, ceil(daily_forecast * 30 + safety))
    order_quantity = max(0, target_stock - available - max(0, incoming_stock))
    if order_quantity and policy.minimum_order_quantity > 1:
        order_quantity = ceil(order_quantity / policy.minimum_order_quantity) * policy.minimum_order_quantity
    if order_quantity:
        reason = (f"Order {order_quantity} units because forecast demand for the next 30 days is "
                  f"{forecast_demand:.0f}, available inventory is {available}, and the reorder point is {reorder_point}.")
    else:
        reason = f"No order needed: available inventory plus incoming stock covers the 30-day target of {target_stock} units."
    return InventoryPosition(current_stock, reserved_stock, incoming_stock, average, daily_forecast,
                             safety, reorder_point, days_remaining, stockout_date, risk, order_quantity, reason)


def calculate_inventory_value(inventory: pd.DataFrame, products: pd.DataFrame) -> float:
    valued = inventory.merge(products[["product_id", "purchase_price"]], on="product_id")
    return float((valued["quantity"] * valued["purchase_price"]).sum())


def inventory_overview(products: pd.DataFrame, sales: pd.DataFrame, inventory: pd.DataFrame,
                       suppliers: pd.DataFrame, settings: Settings | None = None) -> pd.DataFrame:
    settings = settings or get_settings()
    latest = latest_daily_demand(sales)
    supplier_values = suppliers.set_index("supplier_id")
    rows = []
    for product in products.itertuples():
        stock = inventory[inventory.product_id == product.product_id]
        supplier = supplier_values.loc[product.supplier_id]
        demand = float(latest.get(product.product_id, 0))
        policy = InventoryPolicy(int(supplier.lead_time), settings.safety_stock_days,
                                 int(supplier.minimum_order_quantity))
        position = calculate_inventory_position(
            int(stock.quantity.iloc[0]) if not stock.empty else 0,
            int(stock.reserved_quantity.iloc[0]) if not stock.empty else 0,
            0, [demand] * 30, demand * 30, policy)
        rows.append({"Product": product.name, "SKU": product.product_id,
                     "Stock": position.current_stock,
                     "Daily demand": round(position.forecast_daily_demand, 1),
                     "Reorder point": position.reorder_point,
                     "Days left": round(position.days_remaining, 1) if position.days_remaining is not None else None,
                     "Risk": position.risk_level,
                     "Recommended order": position.recommended_order_quantity,
                     "Reason": position.reason})
    return pd.DataFrame(rows)


def stockout_risk_count(products: pd.DataFrame, sales: pd.DataFrame, inventory: pd.DataFrame,
                        suppliers: pd.DataFrame, settings: Settings | None = None) -> int:
    overview = inventory_overview(products, sales, inventory, suppliers, settings)
    return int(overview["Risk"].isin(["Critical", "High Risk", "Warning"]).sum())


