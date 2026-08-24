import pandas as pd


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
