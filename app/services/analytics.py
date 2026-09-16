import pandas as pd

from app.config import Settings, get_settings
from app.services.inventory import inventory_overview


def build_alerts(products: pd.DataFrame, sales: pd.DataFrame, inventory: pd.DataFrame,
                 suppliers: pd.DataFrame, retailer_payments: pd.DataFrame,
                 purchases: pd.DataFrame, supplier_payments: pd.DataFrame,
                 retailers: pd.DataFrame, as_of_date=None,
                 settings: Settings | None = None) -> pd.DataFrame:
    """Build dashboard alerts from the existing inventory and balance services."""
    settings = settings or get_settings()
    cutoff = pd.Timestamp(as_of_date) if as_of_date is not None else pd.Timestamp.today().normalize()
    alerts = []

    inventory_view = inventory_overview(products, sales, inventory, suppliers, settings)
    for _, row in inventory_view[inventory_view["Risk"].isin(["Critical", "High Risk"])].iterrows():
        stockout_date = row["Estimated stockout date"]
        days = max(0, (pd.Timestamp(stockout_date) - cutoff).days) if pd.notna(stockout_date) else None
        explanation = f"Stockout expected in {days} days" if days is not None else "Stockout risk is immediate"
        alerts.append({"severity": "Critical" if row["Risk"] == "Critical" else "High",
                       "category": "Stockout", "name": row["Product"],
                       "explanation": explanation, "estimated_stockout_date": stockout_date})

    sales_dates = sales.copy()
    sales_dates["date"] = pd.to_datetime(sales_dates["date"])
    last_sales = sales_dates.groupby("product_id", as_index=False)["date"].max().rename(columns={"date": "last_sale"})
    slow = products[["product_id", "name"]].merge(last_sales, on="product_id", how="left")
    slow["days_since_last_sale"] = (cutoff - slow["last_sale"]).dt.days
    for row in slow[slow["days_since_last_sale"].ge(settings.slow_moving_days)].itertuples():
        days = int(row.days_since_last_sale)
        alerts.append({"severity": "Warning", "category": "Slow-moving", "name": row.name,
                       "explanation": f"No sale recorded for {days} days", "days_since_last_sale": days})

    retailer_view = retailer_outstanding_balances(sales, retailer_payments, retailers, cutoff,
                                                   settings.retailer_due_soon_days,
                                                   settings.retailer_high_risk_overdue_days,
                                                   settings.retailer_high_risk_credit_ratio)
    retailer_view = retailer_view.merge(retailers[["retailer_id", "name"]], on="retailer_id", how="left")
    for row in retailer_view[retailer_view["risk_status"].isin(["Overdue", "High Risk"])].itertuples():
        alerts.append({"severity": "Critical" if row.risk_status == "High Risk" else "High",
                       "category": "Retailer credit", "name": row.name,
                       "explanation": f"{row.outstanding_balance:,.0f} overdue by {int(row.days_overdue)} days",
                       "outstanding_amount": row.outstanding_balance, "days_overdue": row.days_overdue})

    from app.services.accounting import supplier_balance_overview
    supplier_view = supplier_balance_overview(purchases, supplier_payments, suppliers, settings)
    for row in supplier_view[supplier_view["status"] == "Red"].itertuples():
        alerts.append({"severity": "Critical", "category": "Supplier balance", "name": row.supplier_name,
                       "explanation": f"{row.outstanding_balance:,.0f} outstanding", "outstanding_amount": row.outstanding_balance})
    return pd.DataFrame(alerts, columns=["severity", "category", "name", "explanation",
                                         "estimated_stockout_date", "days_since_last_sale",
                                         "outstanding_amount", "days_overdue"])


def retailer_outstanding_balances(sales: pd.DataFrame, retailer_payments: pd.DataFrame,
                                  retailers: pd.DataFrame | None = None, as_of_date=None,
                                  due_soon_days: int = 7, high_risk_overdue_days: int = 30,
                                  high_risk_credit_ratio: float = 1.0) -> pd.DataFrame:
    """Calculate retailer receivables, applying payments to the oldest sales first."""
    cutoff = pd.Timestamp(as_of_date) if as_of_date is not None else pd.Timestamp.max
    credit_sales = sales[sales["retailer_id"].notna()].copy()
    if credit_sales.empty:
        credit_sales = pd.DataFrame(columns=["retailer_id", "sale_date", "due_date", "credit_sale"])
    else:
        credit_sales["sale_date"] = pd.to_datetime(credit_sales.get("sale_date", credit_sales.get("date")))
        credit_sales["due_date"] = pd.to_datetime(credit_sales.get("due_date"), errors="coerce")
        if retailers is not None and "payment_terms_days" in retailers.columns:
            terms = retailers.set_index("retailer_id")["payment_terms_days"]
            missing_due = credit_sales["due_date"].isna()
            credit_sales.loc[missing_due, "due_date"] = (
                credit_sales.loc[missing_due, "sale_date"] +
                pd.to_timedelta(credit_sales.loc[missing_due, "retailer_id"].map(terms), unit="D")
            )
        credit_sales = credit_sales[credit_sales["sale_date"] <= cutoff]
        credit_sales["credit_sale"] = credit_sales["quantity"] * credit_sales["selling_price"]

    payment_data = retailer_payments.copy()
    if payment_data.empty:
        payment_data = pd.DataFrame(columns=["retailer_id", "date", "amount"])
    payment_data["date"] = pd.to_datetime(payment_data["date"])
    payment_data = payment_data[payment_data["date"] <= cutoff]
    payment_totals = payment_data.groupby("retailer_id", as_index=False)["amount"].sum()

    retailer_ids = set(credit_sales["retailer_id"]) | set(payment_totals["retailer_id"])
    if retailers is not None and "retailer_id" in retailers.columns:
        retailer_ids |= set(retailers["retailer_id"])
    rows = []
    for retailer_id in sorted(retailer_ids):
        invoices = credit_sales[credit_sales["retailer_id"] == retailer_id].sort_values(["due_date", "sale_date"])
        credit_total = float(invoices["credit_sale"].sum())
        payments_total = float(payment_totals.loc[payment_totals["retailer_id"] == retailer_id, "amount"].sum())
        remaining_payment = payments_total
        oldest_unpaid_due = None
        for invoice in invoices.itertuples():
            unpaid = max(0.0, float(invoice.credit_sale) - remaining_payment)
            remaining_payment = max(0.0, remaining_payment - float(invoice.credit_sale))
            if unpaid > 0:
                oldest_unpaid_due = invoice.due_date
                break
        outstanding = max(0.0, credit_total - payments_total)
        days_overdue = max(0, (cutoff.normalize() - oldest_unpaid_due.normalize()).days) if oldest_unpaid_due is not None and oldest_unpaid_due <= cutoff else 0
        credit_limit = 0.0
        if retailers is not None and "credit_limit" in retailers.columns:
            matched = retailers.loc[retailers["retailer_id"] == retailer_id, "credit_limit"]
            credit_limit = float(matched.iloc[0]) if not matched.empty else 0.0
        ratio = outstanding / credit_limit if credit_limit > 0 else 0.0
        if outstanding <= 0:
            risk = "Current"
        elif ratio >= high_risk_credit_ratio or days_overdue >= high_risk_overdue_days:
            risk = "High Risk"
        elif days_overdue > 0:
            risk = "Overdue"
        elif oldest_unpaid_due is not None and (oldest_unpaid_due - cutoff).days <= due_soon_days:
            risk = "Due Soon"
        else:
            risk = "Current"
        rows.append({"retailer_id": retailer_id, "credit_sales": credit_total, "payments": payments_total,
                     "outstanding_balance": outstanding, "days_overdue": days_overdue,
                     "credit_limit": credit_limit, "credit_ratio": ratio, "risk_status": risk})
    return pd.DataFrame(rows).sort_values("outstanding_balance", ascending=False).reset_index(drop=True)


def supplier_outstanding_balances(purchases: pd.DataFrame, supplier_payments: pd.DataFrame,
                                  as_of_date=None) -> pd.DataFrame:
    """Return supplier balances using purchase invoices and payments."""
    cutoff = pd.Timestamp(as_of_date) if as_of_date is not None else pd.Timestamp.max
    purchase_data = purchases.copy()
    purchase_data["date"] = pd.to_datetime(purchase_data["date"])
    purchase_data = purchase_data[purchase_data["date"] <= cutoff]
    purchase_data["purchase_total"] = purchase_data["total_amount"]
    purchases = purchase_data.groupby("supplier_id", as_index=False)["purchase_total"].sum()

    def reductions(frame: pd.DataFrame, value_column: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=["supplier_id", value_column])
        filtered = frame.copy()
        filtered["date"] = pd.to_datetime(filtered["date"])
        filtered = filtered[filtered["date"] <= cutoff]
        return filtered.groupby("supplier_id", as_index=False)["amount"].sum().rename(columns={"amount": value_column})

    payment_totals = reductions(supplier_payments, "payments")
    result = purchases.rename(columns={"purchase_total": "purchases"})
    result = result.merge(payment_totals, on="supplier_id", how="outer")
    for column in ["purchases", "payments"]:
        result[column] = result[column].fillna(0.0)
    result["outstanding_balance"] = result["purchases"] - result["payments"]
    return result.sort_values("supplier_id").reset_index(drop=True)


def sales_summary(sales: pd.DataFrame) -> dict:
    if sales.empty:
        return {"revenue": 0, "orders": 0, "units": 0, "gross_profit": 0, "margin": 0, "active_retailers": 0}
    revenue = (sales["quantity"] * sales["selling_price"]).sum()
    cost = (sales["quantity"] * sales["purchase_cost"]).sum()
    profit = revenue - cost
    return {"revenue": float(revenue), "orders": int(len(sales)), "units": int(sales["quantity"].sum()),
            "gross_profit": float(profit), "margin": float(profit / revenue * 100) if revenue else 0,
            "active_retailers": int(sales.retailer_id.nunique())}


def product_profitability(sales: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    catalog = products[["product_id", "name", "brand", "category"]].copy()
    if sales.empty:
        result = catalog.assign(revenue=0.0, purchase_cost=0.0, units=0)
    else:
        data = sales.assign(revenue=sales.quantity * sales.selling_price,
                            purchase_cost_total=sales.quantity * sales.purchase_cost)
        totals = data.groupby("product_id", as_index=False).agg(revenue=("revenue", "sum"),
            purchase_cost=("purchase_cost_total", "sum"), units=("quantity", "sum"))
        result = catalog.merge(totals, on="product_id", how="left")
        result[["revenue", "purchase_cost", "units"]] = result[["revenue", "purchase_cost", "units"]].fillna(0)
    result["gross_profit"] = result.revenue - result.purchase_cost
    result["gross_margin_pct"] = (result.gross_profit / result.revenue.replace(0, pd.NA) * 100).fillna(0)
    return result


def daily_sales_revenue(sales: pd.DataFrame) -> pd.DataFrame:
    return (sales.assign(revenue=sales.quantity * sales.selling_price)
            .groupby("date", as_index=False)
            .agg(revenue=("revenue", "sum"), units=("quantity", "sum")))


def category_revenue(sales: pd.DataFrame) -> pd.DataFrame:
    return (sales.assign(revenue=sales.quantity * sales.selling_price)
            .groupby("category", as_index=False)["revenue"].sum())


def retailer_summary(sales: pd.DataFrame) -> pd.DataFrame:
    view = (sales.assign(revenue=sales.quantity * sales.selling_price)
            .groupby("retailer_id", as_index=False)
            .agg(revenue=("revenue", "sum"), units=("quantity", "sum"),
                 orders=("date", "nunique"), last_purchase=("date", "max")))
    view["average_order_value"] = view.revenue / view.orders.replace(0, 1)
    return view


def detect_anomalies(daily_sales: pd.DataFrame, threshold: float = 2.0) -> pd.DataFrame:
    if daily_sales.empty:
        return pd.DataFrame()
    grouped = daily_sales.groupby(["product_id", "date"], as_index=False)["quantity"].sum()
    stats = grouped.groupby("product_id")["quantity"].agg(["mean", "std"]).reset_index()
    result = grouped.merge(stats, on="product_id")
    result["z_score"] = (result.quantity - result["mean"]) / result["std"].replace(0, pd.NA)
    return result[result.z_score.abs().fillna(0) >= threshold].sort_values("z_score", key=lambda s: s.abs(), ascending=False)


def get_categories(products: pd.DataFrame) -> list[str]:
    return sorted(products.category.unique())
