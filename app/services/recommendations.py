from datetime import date, datetime, timezone
from decimal import Decimal
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import InventoryStock, Product, ReorderRecommendation, Sale
from app.services.inventory import InventoryPolicy, calculate_inventory_position


def _forecast_demand(db: Session, product_id: int, as_of: date) -> tuple[list[float], float]:
    rows = db.scalars(select(Sale).where(Sale.product_id == product_id, Sale.sale_date <= as_of)).all()
    if not rows:
        return [], 0.0
    sales = pd.DataFrame({"date": [row.sale_date for row in rows], "quantity": [row.quantity for row in rows]})
    daily = sales.groupby("date")["quantity"].sum()
    history = daily.reindex(pd.date_range(daily.index.min(), as_of, freq="D"), fill_value=0)
    average = float(history.tail(30).mean()) if len(history) else 0.0
    return history.tail(30).astype(float).tolist(), max(0.0, average * 30)


def generate_recommendations(db: Session, as_of: date | None = None) -> list[ReorderRecommendation]:
    as_of = as_of or date.today()
    generated: list[ReorderRecommendation] = []
    with db.begin():
        products = db.scalars(select(Product).where(Product.active.is_(True))).all()
        for product in products:
            demand_history, forecast_demand = _forecast_demand(db, product.id, as_of)
            stock = db.scalar(select(InventoryStock).where(InventoryStock.product_id == product.id))
            current_stock = stock.quantity if stock else 0
            reserved_stock = stock.reserved_quantity if stock else 0
            policy = InventoryPolicy(product.supplier.lead_time_days, 3, product.supplier.minimum_order_quantity)
            position = calculate_inventory_position(current_stock, reserved_stock, 0, demand_history,
                                                    forecast_demand, policy, as_of)
            latest = db.scalar(select(ReorderRecommendation).where(
                ReorderRecommendation.product_id == product.id,
                ReorderRecommendation.status == "generated").order_by(ReorderRecommendation.created_at.desc()))
            values = {"supplier_id": product.supplier_id, "forecast_demand": Decimal(str(forecast_demand)),
                      "current_stock": current_stock, "incoming_stock": 0, "safety_stock": position.safety_stock,
                      "reorder_point": position.reorder_point, "estimated_stockout_date": position.estimated_stockout_date,
                      "recommended_quantity": position.recommended_order_quantity, "reason": position.reason}
            if latest is None:
                latest = ReorderRecommendation(product_id=product.id, status="generated", **values)
                db.add(latest)
            else:
                for key, value in values.items():
                    setattr(latest, key, value)
            generated.append(latest)
        db.flush()
    return generated


def list_recommendations(db: Session, status: str | None = None) -> list[ReorderRecommendation]:
    query = select(ReorderRecommendation).order_by(ReorderRecommendation.created_at.desc())
    if status:
        query = query.where(ReorderRecommendation.status == status)
    return list(db.scalars(query).all())


def update_recommendation(db: Session, recommendation_id: int, action: str, quantity: int | None = None) -> ReorderRecommendation:
    with db.begin():
        recommendation = db.get(ReorderRecommendation, recommendation_id)
        if recommendation is None:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        if action not in {"approved", "modified", "rejected"}:
            raise ValueError("Action must be approved, modified, or rejected")
        if action == "modified":
            if quantity is None or quantity < 0:
                raise ValueError("A non-negative quantity is required when modifying a recommendation")
            recommendation.modified_quantity = quantity
        elif action == "approved":
            if quantity is not None:
                if quantity < 0:
                    raise ValueError("Approval quantity cannot be negative")
                recommendation.modified_quantity = quantity
            elif recommendation.modified_quantity is None:
                recommendation.modified_quantity = recommendation.recommended_quantity
        recommendation.status = action
        recommendation.decided_at = datetime.now(timezone.utc)
        db.flush()
    return recommendation