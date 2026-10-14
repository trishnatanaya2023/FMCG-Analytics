from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil
import logging
import math

import numpy as np
import pandas as pd

from app.config import Settings, get_settings
from app.services.forecasting import (
    ForecastResult,
    build_product_demand_history,
    forecast_daily,
    latest_daily_demand,
)

logger = logging.getLogger(__name__)


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
    available_stock: int
    planning_horizon_demand: float
    lead_time_demand: float
    forecast_source: str
    forecast_model: str | None


def calculate_safety_stock(daily_demand: list[float], lead_time_days: int, safety_stock_days: float = 3) -> int:
    if not daily_demand or lead_time_days < 0:
        return 0
    if len(daily_demand) < 2:
        return ceil(max(daily_demand, default=0) * safety_stock_days)
    mean = sum(daily_demand) / len(daily_demand)
    variance = sum((value - mean) ** 2 for value in daily_demand) / (len(daily_demand) - 1)
    demand_deviation = variance ** 0.5
    return max(0, ceil(demand_deviation * (max(lead_time_days, 1) ** 0.5) + mean * safety_stock_days))


def calculate_reorder_point(average_daily_demand: float, lead_time_days: int, safety_stock: int,
                            lead_time_demand: float | None = None) -> int:
    expected_demand = (
        max(0.0, lead_time_demand)
        if lead_time_demand is not None
        else max(0, average_daily_demand) * max(0, lead_time_days)
    )
    return ceil(expected_demand + max(0, safety_stock))


def calculate_inventory_position(current_stock: int, reserved_stock: int, incoming_stock: int,
                                 demand_history: list[float], forecast_demand: float,
                                 policy: InventoryPolicy, as_of: date | None = None,
                                 forecast_values: list[float] | None = None,
                                 forecast_model: str | None = None,
                                 forecast_source: str = "historical-average fallback",
                                 planning_horizon_days: int = 30) -> InventoryPosition:
    as_of = as_of or date.today()
    available = max(0, current_stock - reserved_stock)
    history_average = sum(demand_history) / len(demand_history) if demand_history else 0.0
    valid_forecast = forecast_values is not None and len(forecast_values) > 0
    if valid_forecast:
        raw_forecast = [float(value) for value in forecast_values]
        if not all(math.isfinite(value) for value in raw_forecast):
            raise ValueError("forecast values must be finite")
        cleaned_forecast = [max(0.0, value) for value in raw_forecast]
        horizon_values = cleaned_forecast[:planning_horizon_days]
        planning_demand = sum(horizon_values)
        if len(horizon_values) < planning_horizon_days:
            planning_demand += (planning_horizon_days - len(horizon_values)) * (
                sum(horizon_values) / len(horizon_values) if horizon_values else history_average
            )
        lead_values = cleaned_forecast[:policy.lead_time_days]
        lead_demand = sum(lead_values)
        if len(lead_values) < policy.lead_time_days:
            extension_rate = sum(lead_values) / len(lead_values) if lead_values else history_average
            lead_demand += (policy.lead_time_days - len(lead_values)) * extension_rate
        daily_forecast = planning_demand / max(1, planning_horizon_days)
        average = daily_forecast
        forecast_demand = planning_demand
    else:
        average = history_average
        forecast_demand = max(0.0, forecast_demand)
        daily_forecast = forecast_demand / planning_horizon_days if forecast_demand else average
        planning_demand = daily_forecast * planning_horizon_days
        lead_demand = average * max(0, policy.lead_time_days)
        forecast_model = None
        forecast_source = "historical-average fallback"
    safety = calculate_safety_stock(demand_history, policy.lead_time_days, policy.safety_stock_days)
    reorder_point = calculate_reorder_point(average, policy.lead_time_days, safety,
                                            lead_time_demand=lead_demand if valid_forecast else None)
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
    target_stock = max(reorder_point, ceil(planning_demand + safety))
    order_quantity = max(0, target_stock - available - max(0, incoming_stock))
    if order_quantity and policy.minimum_order_quantity > 1:
        order_quantity = ceil(order_quantity / policy.minimum_order_quantity) * policy.minimum_order_quantity
    if order_quantity:
        model_label = f" using {forecast_model}" if forecast_model else ""
        reason = (f"Order {order_quantity} units because the {forecast_source}{model_label} estimates "
                  f"{forecast_demand:.0f} units over {planning_horizon_days} days; available inventory is "
                  f"{available}, incoming stock is {max(0, incoming_stock)}, and the reorder point is {reorder_point}.")
    else:
        model_label = f" using {forecast_model}" if forecast_model else ""
        reason = (f"No order needed: available inventory plus incoming stock covers the "
                  f"{planning_horizon_days}-day target of {target_stock} units because the "
                  f"{forecast_source}{model_label} estimates {forecast_demand:.0f} units.")
    return InventoryPosition(current_stock, reserved_stock, incoming_stock, average, daily_forecast,
                             safety, reorder_point, days_remaining, stockout_date, risk, order_quantity, reason,
                             available, planning_demand, lead_demand, forecast_source, forecast_model)


def calculate_inventory_value(inventory: pd.DataFrame, products: pd.DataFrame) -> float:
    valued = inventory.merge(products[["product_id", "purchase_price"]], on="product_id")
    return float((valued["quantity"] * valued["purchase_price"]).sum())


def inventory_overview(products: pd.DataFrame, sales: pd.DataFrame, inventory: pd.DataFrame,
                       suppliers: pd.DataFrame, settings: Settings | None = None,
                       as_of: date | None = None) -> pd.DataFrame:
    settings = settings or get_settings()
    supplier_values = suppliers.set_index("supplier_id")
    latest = latest_daily_demand(sales)
    as_of = pd.to_datetime(sales["date"]).max().normalize() if not sales.empty else None
    rows = []
    for product in products.itertuples():
        stock = inventory[inventory.product_id == product.product_id]
        supplier = supplier_values.loc[product.supplier_id]
        history = build_product_demand_history(sales, product.product_id, as_of)
        result: ForecastResult | None = None
        if len(history) >= 2:
            try:
                result = forecast_daily(history, 60)
            except (ValueError, RuntimeError, ArithmeticError, np.linalg.LinAlgError) as exc:
                logger.warning("Inventory forecast failed for SKU %s; using historical average: %s",
                               product.product_id, exc)
        demand = float(latest.get(product.product_id, 0))
        fallback_demand = demand * 30
        policy = InventoryPolicy(int(supplier.lead_time), settings.safety_stock_days,
                                 int(supplier.minimum_order_quantity))
        if result is not None:
            position = calculate_inventory_position(
                int(stock.quantity.iloc[0]) if not stock.empty else 0,
                int(stock.reserved_quantity.iloc[0]) if not stock.empty else 0,
                0, history.tail(60).astype(float).tolist(), sum(result.values[:30]), policy,
                as_of=as_of,
                forecast_values=result.values, forecast_model=result.model_name,
                forecast_source="selected forecast",
            )
        else:
            position = calculate_inventory_position(
                int(stock.quantity.iloc[0]) if not stock.empty else 0,
                int(stock.reserved_quantity.iloc[0]) if not stock.empty else 0,
                0, [demand] * 30, fallback_demand, policy, as_of=as_of)
        rows.append({"Product": product.name, "SKU": product.product_id,
                     "Stock": position.current_stock,
                     "Available stock": position.available_stock,
                     "Incoming stock": position.incoming_stock,
                     "Daily demand": round(position.forecast_daily_demand, 1),
                     "Forecast demand (30d)": round(position.planning_horizon_demand, 1),
                     "Forecast model": position.forecast_model or "historical-average fallback",
                     "Forecast source": position.forecast_source,
                     "Forecast MAE": result.mae if result is not None else None,
                     "Forecast RMSE": result.rmse if result is not None else None,
                     "Forecast MAPE": result.mape if result is not None else None,
                     "Supplier lead time (days)": policy.lead_time_days,
                     "MOQ": policy.minimum_order_quantity,
                     "Safety stock": position.safety_stock,
                     "Reorder point": position.reorder_point,
                     "Days left": round(position.days_remaining, 1) if position.days_remaining is not None else None,
                     "Estimated stockout date": position.estimated_stockout_date,
                     "Risk": position.risk_level,
                     "Recommended order": position.recommended_order_quantity,
                     "Reason": position.reason})
    return pd.DataFrame(rows)


def stockout_risk_count(products: pd.DataFrame, sales: pd.DataFrame, inventory: pd.DataFrame,
                        suppliers: pd.DataFrame, settings: Settings | None = None) -> int:
    overview = inventory_overview(products, sales, inventory, suppliers, settings)
    return int(overview["Risk"].isin(["Critical", "High Risk", "Warning"]).sum())
