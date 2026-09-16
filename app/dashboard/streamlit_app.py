import sys
from html import escape
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.formatting import format_currency, format_currency_columns
from app.database.session import SessionLocal
from app.services.auth import authenticate_user, create_access_token
from app.services.analytics import (build_alerts, category_revenue, daily_sales_revenue, product_profitability,
                                    retailer_outstanding_balances, retailer_summary, sales_summary, get_categories)
from app.services.accounting import (expense_category_summary, filter_expenses, load_accounting_data,
                                     monthly_expense_summary, supplier_balance_overview)
from app.services.data_loading import load_sample_data
from app.services.forecasting import (build_product_demand_history, forecast_daily,
                                      get_product_ids, get_forecast_horizon_options, latest_daily_demand)
from app.services.inventory import (calculate_inventory_value, inventory_overview, stockout_risk_count)
from app.services.suppliers import supplier_product_counts, supplier_product_summary

st.set_page_config(page_title="DistribuSense", page_icon="DS", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif; }
[data-testid="stMetric"] { background: #f4f7f2; border-left: 4px solid #1f7a5a; padding: 12px; border-radius: 6px; min-width: 0; }
[data-testid="stMetricLabel"], [data-testid="stMetricValue"] { min-width: 0; overflow: visible; white-space: normal; overflow-wrap: anywhere; }
[data-testid="stMetricValue"] { font-size: 1.15rem !important; line-height: 1.15; }
.alert { padding: 12px 16px; border-radius: 5px; margin: 6px 0; background: #fff4df; border-left: 4px solid #e39b21; }
.status-badge { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 0.78rem; font-weight: 700; white-space: nowrap; }
.status-healthy, .status-current { color: #166534; background: #dcfce7; }
.status-warning, .status-due-soon { color: #854d0e; background: #fef3c7; }
.status-high, .status-overdue { color: #9a3412; background: #ffedd5; }
.status-critical, .status-red { color: #991b1b; background: #fee2e2; }
.alert-table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
.alert-table th, .alert-table td { padding: 0.65rem 0.75rem; border-bottom: 1px solid #e5e7eb; text-align: left; }
.alert-table th { color: #4b5563; font-size: 0.78rem; text-transform: uppercase; }
</style>
""", unsafe_allow_html=True)

def status_badge(value: str) -> str:
    slug = value.lower().replace(" ", "-")
    return f'<span class="status-badge status-{escape(slug)}">{escape(value)}</span>'


def render_status_table(frame: pd.DataFrame, status_column: str) -> None:
    headers = "".join(f"<th>{escape(str(column))}</th>" for column in frame.columns)
    body = []
    for _, row in frame.iterrows():
        cells = []
        for column in frame.columns:
            value = row[column]
            rendered = status_badge(str(value)) if column == status_column else escape(str(value))
            cells.append(f"<td>{rendered}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    st.markdown(f'<table class="alert-table"><thead><tr>{headers}</tr></thead><tbody>{"".join(body)}</tbody></table>', unsafe_allow_html=True)

if "access_token" not in st.session_state:
    st.title("DistribuSense")
    st.subheader("Sign in to continue")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Sign in", type="primary"):
        with SessionLocal() as db:
            user = authenticate_user(db, username, password)
        if user is None:
            st.error("Invalid username or password")
        else:
            try:
                st.session_state["access_token"] = create_access_token(user.username)
                st.session_state["username"] = user.username
                st.rerun()
            except RuntimeError as exc:
                st.error(str(exc))
    st.stop()

ROOT = Path(__file__).resolve().parents[2] / "data" / "sample"

@st.cache_data
def load_data():
    return load_sample_data(ROOT)


@st.cache_data
def load_financial_data():
    return load_accounting_data(ROOT)

try:
    products, sales, inventory, retailers, suppliers = load_data()
    expenses, supplier_payments, purchases, retailer_payments = load_financial_data()
except FileNotFoundError:
    st.error("Sample data is missing. Run `python scripts/generate_sample_data.py` first.")
    st.stop()

st.sidebar.title("DistribuSense")
st.sidebar.caption("Distribution intelligence")
st.sidebar.caption(f"Signed in as {st.session_state.get('username', 'user')}")
if st.sidebar.button("Log out"):
    st.session_state.clear()
    st.rerun()
page = st.sidebar.radio("Workspace", ["Executive Dashboard", "Sales Analytics", "Demand Forecast", "Inventory Intelligence", "Reorder Planning", "Retailer Analytics", "Operating Expenses", "Supplier Analytics", "Alerts"])
summary = sales_summary(sales)
receivables = retailer_outstanding_balances(sales, retailer_payments, retailers, sales.date.max())

if page == "Executive Dashboard":
    st.title("What needs action today?")
    st.caption(f"Operating view through {sales.date.max().date()}")
    values = [("Revenue", format_currency(summary["revenue"])), ("Orders", f"{summary['orders']:,}"), ("Units sold", f"{summary['units']:,}"), ("Inventory value", format_currency(calculate_inventory_value(inventory, products))), ("Gross margin", f"{summary['margin']:.1f}%"), ("Active retailers", f"{summary['active_retailers']:,}"), ("Outstanding receivables", format_currency(receivables["outstanding_balance"].sum())), ("Stockout risk", f"{stockout_risk_count(products, sales, inventory, suppliers):,}")]
    for row_start in range(0, len(values), 2):
        cols = st.columns(2)
        for col, (label, value) in zip(cols, values[row_start:row_start + 2]):
            col.metric(label, value)
    st.subheader("Sales pulse")
    daily = daily_sales_revenue(sales)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily.date, y=daily.revenue, name="Revenue",
                             hovertemplate="%{x|%d %b %Y}<br>Revenue: %{customdata}<extra></extra>",
                             customdata=[format_currency(value) for value in daily.revenue]))
    fig.add_trace(go.Scatter(x=daily.date, y=daily.units, name="Units", yaxis="y2",
                             hovertemplate="%{x|%d %b %Y}<br>Units: %{y:,.0f}<extra></extra>"))
    revenue_ticks = daily.revenue.quantile([index / 5 for index in range(6)]).drop_duplicates().tolist()
    fig.update_layout(title="Daily revenue and units", yaxis=dict(title="Revenue (₹)",
                      tickmode="array", tickvals=revenue_ticks,
                      ticktext=[format_currency(value) for value in revenue_ticks], nticks=6),
                      yaxis2=dict(title="Units", overlaying="y", side="right"),
                      margin=dict(l=110, r=90))
    st.plotly_chart(fig, use_container_width=True)

elif page == "Sales Analytics":
    st.title("Sales Analytics")
    category = st.multiselect("Categories", get_categories(products), default=get_categories(products))
    filtered = sales[sales.category.isin(category)]
    revenue = category_revenue(filtered)
    fig = px.bar(revenue, x="category", y="revenue", title="Revenue by category",
                 custom_data=[revenue.revenue.map(format_currency)])
    category_ticks = revenue.revenue.quantile([index / 5 for index in range(6)]).drop_duplicates().tolist()
    fig.update_traces(hovertemplate="%{x}<br>Revenue: %{customdata[0]}<extra></extra>")
    fig.update_yaxes(title="Revenue (₹)", tickmode="array", tickvals=category_ticks,
                     ticktext=[format_currency(value) for value in category_ticks], nticks=6,
                     automargin=True)
    fig.update_layout(margin=dict(l=110, r=40))
    st.plotly_chart(fig, use_container_width=True)
    profit = product_profitability(filtered, products)
    st.dataframe(format_currency_columns(profit.sort_values("gross_profit", ascending=False),
                                         ["revenue", "purchase_cost", "gross_profit"]), use_container_width=True, hide_index=True)

elif page == "Demand Forecast":
    st.title("Demand Forecast")
    selected = st.selectbox("Product", get_product_ids(products))
    horizon = st.select_slider("Forecast horizon", options=get_forecast_horizon_options(), value=30)
    history = build_product_demand_history(sales, selected)
    result = forecast_daily(history, horizon)
    actual = history.tail(90).rename("units").reset_index()
    future = pd.DataFrame({"date": result.dates, "units": result.values, "lower": result.lower, "upper": result.upper})
    st.caption(f"Selected model: {result.model_name} | MAE: {result.mae if result.mae is not None else 'n/a'} | RMSE: {result.rmse if result.rmse is not None else 'n/a'}")
    fig = px.line(actual, x="date", y="units", title=f"{selected} demand")
    fig.add_scatter(x=future.date, y=future.units, mode="lines", name="Forecast")
    fig.add_scatter(x=future.date, y=future.upper, mode="lines", line=dict(width=0), showlegend=False)
    fig.add_scatter(x=future.date, y=future.lower, mode="lines", fill="tonexty", line=dict(width=0), name="Confidence band")
    st.plotly_chart(fig, use_container_width=True)

elif page in ["Inventory Intelligence", "Reorder Planning"]:
    st.title(page)
    table = inventory_overview(products, sales, inventory, suppliers)
    if page == "Reorder Planning": table = table[table["Recommended order"] > 0]
    status_table = table[["Product", "Days left", "Risk", "Recommended order"]].copy()
    status_table["Days left"] = status_table["Days left"].fillna("n/a")
    render_status_table(status_table, "Risk")

elif page == "Retailer Analytics":
    st.title("Retailer Analytics")
    view = retailer_summary(sales)
    st.dataframe(format_currency_columns(view.sort_values("revenue", ascending=False),
                                         ["revenue", "average_order_value"]), use_container_width=True, hide_index=True)
    st.subheader("Outstanding receivables")
    sort_by = st.selectbox("Sort receivables by", ["Outstanding balance", "Risk status"], key="receivables_sort")
    receivable_view = receivables.merge(retailers[["retailer_id", "name"]], on="retailer_id", how="left")
    receivable_view = receivable_view.rename(columns={"name": "retailer", "outstanding_balance": "outstanding balance",
                                                       "days_overdue": "days overdue", "risk_status": "risk status"})
    if sort_by == "Risk status":
        risk_order = {"High Risk": 0, "Overdue": 1, "Due Soon": 2, "Current": 3}
        receivable_view["_risk_order"] = receivable_view["risk status"].map(risk_order).fillna(4)
        receivable_view = receivable_view.sort_values(["_risk_order", "outstanding balance"], ascending=[True, False]).drop(columns="_risk_order")
    else:
        receivable_view = receivable_view.sort_values("outstanding balance", ascending=False)
    retailer_status_view = receivable_view[["retailer", "outstanding balance", "days overdue", "risk status"]].copy()
    for column in ["outstanding balance"]:
        retailer_status_view[column] = retailer_status_view[column].map(lambda value: format_currency(value, 2))
    render_status_table(retailer_status_view.rename(columns={"risk status": "Risk status"}), "Risk status")

elif page == "Operating Expenses":
    st.title("Operating Expenses")
    expense_start = expenses.date.min().date()
    expense_end = expenses.date.max().date()
    selected_categories = st.multiselect("Expense categories", sorted(expenses.category.unique()),
                                         default=sorted(expenses.category.unique()))
    selected_dates = st.date_input("Expense date range", value=(expense_start, expense_end),
                                   min_value=expense_start, max_value=expense_end)
    start_date, end_date = selected_dates if isinstance(selected_dates, tuple) else (selected_dates, selected_dates)
    filtered_expenses = filter_expenses(expenses, selected_categories, start_date, end_date)
    total_expenses = filtered_expenses.amount.sum()
    monthly = monthly_expense_summary(filtered_expenses)
    average_monthly = total_expenses / len(monthly) if len(monthly) else 0
    kpi_cols = st.columns(2)
    kpi_cols[0].metric("Total expenses", format_currency(total_expenses))
    kpi_cols[1].metric("Average monthly expense", format_currency(average_monthly))
    chart_cols = st.columns(2)
    with chart_cols[0]:
        st.plotly_chart(px.bar(monthly, x="month", y="total_expenses", title="Monthly expense trend",
                               labels={"total_expenses": "Expenses (₹)", "month": "Month"}),
                        use_container_width=True)
    with chart_cols[1]:
        category_totals = expense_category_summary(filtered_expenses)
        st.plotly_chart(px.bar(category_totals, x="category", y="total_expenses", title="Expenses by category",
                               labels={"total_expenses": "Expenses (₹)", "category": "Category"}),
                        use_container_width=True)
    st.dataframe(format_currency_columns(filtered_expenses,
                                         ["amount"], decimals=2), use_container_width=True, hide_index=True)

elif page == "Supplier Analytics":
    st.title("Supplier Analytics")
    st.dataframe(supplier_product_summary(suppliers, products), use_container_width=True, hide_index=True)
    st.subheader("Supplier balances")
    balances = supplier_balance_overview(purchases, supplier_payments, suppliers)
    balance_view = balances[["supplier_name", "purchases", "payments", "outstanding_balance", "status"]].rename(
        columns={"supplier_name": "supplier", "outstanding_balance": "outstanding balance"})
    supplier_status_view = balance_view[["supplier", "outstanding balance", "status"]].copy()
    supplier_status_view["outstanding balance"] = supplier_status_view["outstanding balance"].map(lambda value: format_currency(value, 2))
    render_status_table(supplier_status_view.rename(columns={"status": "Status"}), "Status")

else:
    st.title("Alert Center")
    alerts = build_alerts(products, sales, inventory, suppliers, retailer_payments,
                          purchases, supplier_payments, retailers, settings=None)
    st.metric("Total alerts", len(alerts))
    selected_severities = st.multiselect("Severity", ["Critical", "High", "Warning"],
                                         default=["Critical", "High", "Warning"])
    filtered_alerts = alerts[alerts["severity"].isin(selected_severities)]
    alert_view = filtered_alerts[["severity", "category", "name", "explanation"]].rename(
        columns={"severity": "Severity", "category": "Category", "name": "Name", "explanation": "Explanation"})
    render_status_table(alert_view, "Severity")
