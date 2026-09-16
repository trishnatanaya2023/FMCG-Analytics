from pathlib import Path

import pandas as pd

from app.services.analytics import supplier_outstanding_balances
from app.config import Settings, get_settings


def load_accounting_data(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    expenses = pd.read_csv(root / "expenses.csv", parse_dates=["date"])
    supplier_payments = pd.read_csv(root / "supplier_payments.csv", parse_dates=["date"])
    purchases = pd.read_csv(root / "purchases.csv", parse_dates=["date"])
    retailer_payments = pd.read_csv(root / "retailer_payments.csv", parse_dates=["date"])
    return expenses, supplier_payments, purchases, retailer_payments


def filter_expenses(expenses: pd.DataFrame, categories: list[str] | None = None,
                    start_date=None, end_date=None) -> pd.DataFrame:
    filtered = expenses.copy()
    filtered["date"] = pd.to_datetime(filtered["date"])
    if categories:
        filtered = filtered[filtered["category"].isin(categories)]
    if start_date is not None:
        filtered = filtered[filtered["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        filtered = filtered[filtered["date"] <= pd.Timestamp(end_date)]
    return filtered.sort_values(["date", "expense_id"]).reset_index(drop=True)


def monthly_expense_summary(expenses: pd.DataFrame) -> pd.DataFrame:
    data = expenses.copy()
    data["date"] = pd.to_datetime(data["date"])
    return (data.assign(month=data["date"].dt.to_period("M").dt.to_timestamp())
            .groupby("month", as_index=False)["amount"].sum()
            .rename(columns={"amount": "total_expenses"}))


def expense_category_summary(expenses: pd.DataFrame) -> pd.DataFrame:
    return (expenses.groupby("category", as_index=False)["amount"].sum()
            .rename(columns={"amount": "total_expenses"})
            .sort_values("total_expenses", ascending=False))


def supplier_balance_overview(purchases: pd.DataFrame,
                              supplier_payments: pd.DataFrame, suppliers: pd.DataFrame,
                              settings: Settings | None = None) -> pd.DataFrame:
    settings = settings or get_settings()
    balances = supplier_outstanding_balances(purchases, supplier_payments)
    monthly = purchases.copy()
    monthly["date"] = pd.to_datetime(monthly["date"])
    typical = (monthly.assign(month=monthly["date"].dt.to_period("M"))
               .groupby(["supplier_id", "month"], as_index=False)["total_amount"].sum()
               .groupby("supplier_id", as_index=False)["total_amount"].mean()
               .rename(columns={"total_amount": "typical_monthly_purchases"}))
    view = balances.merge(suppliers[["supplier_id", "name"]], on="supplier_id", how="left")
    view = view.merge(typical, on="supplier_id", how="left")
    view["balance_ratio"] = view["outstanding_balance"] / view["typical_monthly_purchases"].replace(0, pd.NA)
    view["status"] = "Green"
    view.loc[view["outstanding_balance"] > 0, "status"] = "Yellow"
    view.loc[view["balance_ratio"] >= settings.supplier_balance_critical_ratio, "status"] = "Red"
    return view.rename(columns={"name": "supplier_name"}).sort_values(
        "outstanding_balance", ascending=False).reset_index(drop=True)