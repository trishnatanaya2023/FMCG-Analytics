from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from app.database.session import SessionLocal
from app.services.auth import authenticate_user, create_access_token
from app.services.analytics import product_profitability, sales_summary
from app.services.forecasting import forecast_daily
from app.services.inventory import InventoryPolicy, calculate_inventory_position

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
    products = pd.read_csv(ROOT / "products.csv")
    sales = pd.read_csv(ROOT / "sales.csv", parse_dates=["date"])
    inventory = pd.read_csv(ROOT / "inventory.csv", parse_dates=["manufacturing_date", "expiry_date"])
    retailers = pd.read_csv(ROOT / "retailers.csv")
    suppliers = pd.read_csv(ROOT / "suppliers.csv")
    sales = sales.merge(products[["product_id", "purchase_price", "name", "category", "brand", "supplier_id"]], on="product_id")
    sales["purchase_cost"] = sales["purchase_price"]
    return products, sales, inventory, retailers, suppliers

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
    values = [("Revenue", f"₹{summary['revenue']:,.0f}"), ("Orders", f"{summary['orders']:,}"), ("Units sold", f"{summary['units']:,}"), ("Inventory value", f"₹{(inventory.merge(products[['product_id','purchase_price']], on='product_id').eval('quantity * purchase_price').sum()):,.0f}"), ("Gross margin", f"{summary['margin']:.1f}%"), ("Active retailers", f"{sales.retailer_id.nunique():,}"), ("Stockout risk", "Review"), ("Expiry risk", f"{(inventory.expiry_date <= pd.Timestamp.today() + pd.Timedelta(days=30)).sum():,}")]
    for col, (label, value) in zip(cols, values): col.metric(label, value)
    st.subheader("Sales pulse")
    daily = sales.groupby("date", as_index=False).agg(revenue=("selling_price", lambda x: 0), units=("quantity", "sum"))
    daily["revenue"] = sales.assign(revenue=sales.quantity * sales.selling_price).groupby("date").revenue.sum().values
    st.plotly_chart(px.line(daily, x="date", y=["revenue", "units"], title="Daily revenue and units"), use_container_width=True)
    st.subheader("Priority alerts")
    expiry = inventory[inventory.expiry_date <= pd.Timestamp.today() + pd.Timedelta(days=30)].sort_values("expiry_date").head(5)
    for row in expiry.itertuples(): st.markdown(f'<div class="alert">Expiry risk: <b>{row.product_id}</b> has {row.quantity:,} units expiring on {row.expiry_date.date()}. Prioritize FEFO dispatch or promotion.</div>', unsafe_allow_html=True)

elif page == "Sales Analytics":
    st.title("Sales Analytics")
    category = st.multiselect("Categories", sorted(products.category.unique()), default=sorted(products.category.unique()))
    filtered = sales[sales.category.isin(category)]
    category_revenue = (filtered.assign(revenue=filtered.quantity * filtered.selling_price)
                        .groupby("category", as_index=False)["revenue"].sum())
    st.plotly_chart(px.bar(category_revenue, x="category", y="revenue", title="Revenue by category"), use_container_width=True)
    profit = product_profitability(filtered, products)
    st.dataframe(profit.sort_values("gross_profit", ascending=False), use_container_width=True, hide_index=True)

elif page == "Demand Forecast":
    st.title("Demand Forecast")
    selected = st.selectbox("Product", products.product_id.tolist())
    horizon = st.select_slider("Forecast horizon", options=[7, 14, 30, 60], value=30)
    history = sales[sales.product_id == selected].groupby("date").quantity.sum().asfreq("D", fill_value=0)
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
    latest = sales[sales.date >= sales.date.max() - pd.Timedelta(days=30)].groupby("product_id").quantity.sum().div(30)
    rows = []
    for product in products.itertuples():
        batches = inventory[inventory.product_id == product.product_id]
        demand = float(latest.get(product.product_id, 0))
        position = calculate_inventory_position(int(batches.quantity.sum()), 0, 0, [demand] * 30, demand * 30, InventoryPolicy(int(suppliers.loc[suppliers.supplier_id == product.supplier_id, "lead_time"].iloc[0]), 3, int(suppliers.loc[suppliers.supplier_id == product.supplier_id, "minimum_order_quantity"].iloc[0])))
        rows.append({"Product": product.name, "SKU": product.product_id, "Stock": position.current_stock, "Daily demand": round(position.forecast_daily_demand, 1), "Reorder point": position.reorder_point, "Days left": round(position.days_remaining, 1) if position.days_remaining is not None else None, "Risk": position.risk_level, "Recommended order": position.recommended_order_quantity, "Reason": position.reason})
    table = pd.DataFrame(rows)
    if page == "Reorder Planning": table = table[table["Recommended order"] > 0]
    st.dataframe(table, use_container_width=True, hide_index=True)

elif page == "Expiry Management":
    st.title("Expiry Management | FEFO queue")
    view = inventory.merge(products[["product_id", "name", "purchase_price"]], on="product_id")
    view["days_until_expiry"] = (view.expiry_date - pd.Timestamp.today().normalize()).dt.days
    view["risk"] = pd.cut(view.days_until_expiry, [-10**6, 30, 60, 90, 10**6], labels=["Critical", "Warning", "Monitor", "Healthy"])
    view["value_at_risk"] = view.quantity * view.purchase_price
    st.dataframe(view.sort_values("expiry_date"), use_container_width=True, hide_index=True)

elif page == "Retailer Analytics":
    st.title("Retailer Analytics")
    view = sales.assign(revenue=sales.quantity * sales.selling_price).groupby("retailer_id", as_index=False).agg(revenue=("revenue", "sum"), units=("quantity", "sum"), orders=("date", "nunique"), last_purchase=("date", "max"))
    view["average_order_value"] = view.revenue / view.orders.replace(0, 1)
    st.dataframe(view.sort_values("revenue", ascending=False), use_container_width=True, hide_index=True)

elif page == "Supplier Analytics":
    st.title("Supplier Analytics")
    st.dataframe(suppliers.merge(products.groupby("supplier_id").size().rename("products_supplied"), on="supplier_id"), use_container_width=True, hide_index=True)

else:
    st.title("Alert Center")
    st.info("Alerts are derived from the same inventory, expiry, demand, and credit calculations shown in each workspace.")
    st.dataframe(inventory.assign(days_until_expiry=(inventory.expiry_date - pd.Timestamp.today().normalize()).dt.days).query("days_until_expiry <= 30"), use_container_width=True, hide_index=True)
