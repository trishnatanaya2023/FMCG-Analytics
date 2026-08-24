import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd
import plotly.express as px
import streamlit as st
from app.database.session import SessionLocal
from app.services.auth import authenticate_user, create_access_token
from app.services.analytics import (category_revenue, daily_sales_revenue, product_profitability,
                                    retailer_summary, sales_summary, get_categories)
from app.services.data_loading import load_sample_data
from app.services.forecasting import (build_product_demand_history, forecast_daily,
                                      get_product_ids, get_forecast_horizon_options, latest_daily_demand)
from app.services.inventory import (calculate_inventory_value, expiry_analysis, expiry_risk_count,
                                    inventory_overview, critical_expiry_items)
from app.services.suppliers import supplier_product_counts, supplier_product_summary

st.set_page_config(page_title="DistribuSense", page_icon="DS", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif; }
[data-testid="stMetric"] { background: #f4f7f2; border-left: 4px solid #1f7a5a; padding: 14px; border-radius: 6px; }
.alert { padding: 12px 16px; border-radius: 5px; margin: 6px 0; background: #fff4df; border-left: 4px solid #e39b21; }
</style>
""", unsafe_allow_html=True)

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

try:
    products, sales, inventory, retailers, suppliers = load_data()
except FileNotFoundError:
    st.error("Sample data is missing. Run `python scripts/generate_sample_data.py` first.")
    st.stop()

st.sidebar.title("DistribuSense")
st.sidebar.caption("Distribution intelligence")
st.sidebar.caption(f"Signed in as {st.session_state.get('username', 'user')}")
if st.sidebar.button("Log out"):
    st.session_state.clear()
    st.rerun()
page = st.sidebar.radio("Workspace", ["Executive Dashboard", "Sales Analytics", "Demand Forecast", "Inventory Intelligence", "Reorder Planning", "Expiry Management", "Retailer Analytics", "Supplier Analytics", "Alerts"])
summary = sales_summary(sales)

if page == "Executive Dashboard":
    st.title("What needs action today?")
    st.caption(f"Operating view through {sales.date.max().date()}")
    cols = st.columns(8)
    values = [("Revenue", f"₹{summary['revenue']:,.0f}"), ("Orders", f"{summary['orders']:,}"), ("Units sold", f"{summary['units']:,}"), ("Inventory value", f"₹{calculate_inventory_value(inventory, products):,.0f}"), ("Gross margin", f"{summary['margin']:.1f}%"), ("Active retailers", f"{summary['active_retailers']:,}"), ("Stockout risk", "Review"), ("Expiry risk", f"{expiry_risk_count(inventory):,}")]
    for col, (label, value) in zip(cols, values): col.metric(label, value)
    st.subheader("Sales pulse")
    daily = daily_sales_revenue(sales)
    st.plotly_chart(px.line(daily, x="date", y=["revenue", "units"], title="Daily revenue and units"), use_container_width=True)
    st.subheader("Priority alerts")
    expiry = expiry_analysis(inventory, products).query("risk == 'Critical'").sort_values("expiry_date").head(5)
    for row in expiry.itertuples(): st.markdown(f'<div class="alert">Expiry risk: <b>{row.product_id}</b> has {row.quantity:,} units expiring on {row.expiry_date.date()}. Prioritize FEFO dispatch or promotion.</div>', unsafe_allow_html=True)

elif page == "Sales Analytics":
    st.title("Sales Analytics")
    category = st.multiselect("Categories", get_categories(products), default=get_categories(products))
    filtered = sales[sales.category.isin(category)]
    revenue = category_revenue(filtered)
    st.plotly_chart(px.bar(revenue, x="category", y="revenue", title="Revenue by category"), use_container_width=True)
    profit = product_profitability(filtered, products)
    st.dataframe(profit.sort_values("gross_profit", ascending=False), use_container_width=True, hide_index=True)

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
    st.dataframe(table, use_container_width=True, hide_index=True)

elif page == "Expiry Management":
    st.title("Expiry Management | FEFO queue")
    view = expiry_analysis(inventory, products)
    st.dataframe(view.sort_values("expiry_date"), use_container_width=True, hide_index=True)

elif page == "Retailer Analytics":
    st.title("Retailer Analytics")
    view = retailer_summary(sales)
    st.dataframe(view.sort_values("revenue", ascending=False), use_container_width=True, hide_index=True)

elif page == "Supplier Analytics":
    st.title("Supplier Analytics")
    st.dataframe(supplier_product_summary(suppliers, products), use_container_width=True, hide_index=True)

else:
    st.title("Alert Center")
    st.info("Alerts are derived from the same inventory, expiry, demand, and credit calculations shown in each workspace.")
    st.dataframe(critical_expiry_items(inventory, products), use_container_width=True, hide_index=True)
