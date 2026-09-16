"""Create reproducible CSV fixtures for a realistic FMCG wholesale distributor."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

SEED = 42
ROOT = Path(__file__).resolve().parents[1] / "data" / "sample"
FY_START = pd.Timestamp("2024-04-01").normalize()
FY_END = pd.Timestamp("2025-03-31").normalize()
COUNTER_SALES_SHARE = 0.25
MONTHLY_SEASONALITY = {
    4: 0.92,
    5: 1.04,
    6: 0.96,
    7: 0.9,
    8: 1.02,
    9: 1.18,
    10: 1.34,
    11: 1.7,
    12: 1.95,
    1: 1.52,
    2: 1.28,
    3: 1.66,
}

FICTIONAL_SUPPLIER_NAMES = [
    "Madhab Behera Agro Foods",
    "Pranati Mohanty Trading Co.",
    "Subhranshu Sahoo Enterprises",
    "Suchitra Pradhan Food Products",
    "Debasish Rout Distributors",
    "Manaswini Jena Wholesale",
    "Chandan Nayak Agro Mart",
    "Rasmita Das Supply House",
]
FICTIONAL_BRANDS = [
    "Dhauli Basket", "Mahanadi Pantry", "Kalinga Harvest", "Konark Choice", "Utkal Daily", "Bhuban Fresh",
]
RETAILER_PERSONAL_NAMES = [
    "Sanjay Behera", "Mamata Sahoo", "Bikash Mohanty", "Lipsa Pradhan", "Rakesh Jena", "Prativa Rout",
    "Soumya Das", "Tapan Nayak", "Niharika Swain", "Manoj Barik", "Sasmita Behera", "Ranjan Sahoo",
    "Jyoti Mohanty", "Akash Pradhan", "Madhuri Jena", "Debendra Rout", "Kavita Nayak", "Prakash Das",
    "Sushant Swain", "Anita Barik", "Biswa Behera", "Gitanjali Sahoo", "Kunal Mohanty", "Mitali Pradhan",
]
RETAILER_LOCALITIES = [
    "Saheed Nagar", "Unit 4", "Mancheswar", "Kharavel Nagar", "Patia", "Rasulgarh", "Jharapada",
    "Old Town", "Baramunda", "Nayapalli", "Chandrasekharpur", "Bapuji Nagar",
]


def _pack_templates():
    return [
        {"category": "Atta & Flour", "item": "Wheat Atta", "variant": "5kg x 6pc", "pack_size": "PKT", "units_per_pack": 6, "base_price": 400},
        {"category": "Atta & Flour", "item": "Wheat Atta", "variant": "10kg x 2pc", "pack_size": "PKT", "units_per_pack": 2, "base_price": 760},
        {"category": "Atta & Flour", "item": "Maida", "variant": "50kg", "pack_size": "KG", "units_per_pack": 50, "base_price": 2250},
        {"category": "Atta & Flour", "item": "Suji Rava", "variant": "25kg", "pack_size": "KG", "units_per_pack": 25, "base_price": 1350},
        {"category": "Rice & Grains", "item": "Sona Masuri Rice", "variant": "25kg", "pack_size": "KG", "units_per_pack": 25, "base_price": 1450},
        {"category": "Rice & Grains", "item": "Swarnamasuri Rice", "variant": "30kg", "pack_size": "KG", "units_per_pack": 30, "base_price": 1600},
        {"category": "Rice & Grains", "item": "Basmati Rice", "variant": "25kg", "pack_size": "KG", "units_per_pack": 25, "base_price": 2350},
        {"category": "Rice & Grains", "item": "Poha Chuda", "variant": "25kg", "pack_size": "KG", "units_per_pack": 25, "base_price": 1250},
        {"category": "Pulses & Dal", "item": "Toor Dal", "variant": "30kg", "pack_size": "KG", "units_per_pack": 30, "base_price": 2850},
        {"category": "Pulses & Dal", "item": "Moong Dal", "variant": "30kg", "pack_size": "KG", "units_per_pack": 30, "base_price": 2700},
        {"category": "Pulses & Dal", "item": "Chana Dal", "variant": "30kg", "pack_size": "KG", "units_per_pack": 30, "base_price": 2050},
        {"category": "Pulses & Dal", "item": "Besan", "variant": "25kg", "pack_size": "KG", "units_per_pack": 25, "base_price": 1850},
        {"category": "Cooking Oil", "item": "Sunflower Oil", "variant": "1ltr x 16", "pack_size": "TIN", "units_per_pack": 16, "base_price": 2150},
        {"category": "Cooking Oil", "item": "Mustard Oil", "variant": "1ltr x 16", "pack_size": "TIN", "units_per_pack": 16, "base_price": 2350},
        {"category": "Cooking Oil", "item": "Groundnut Oil", "variant": "1ltr x 12", "pack_size": "TIN", "units_per_pack": 12, "base_price": 2050},
        {"category": "Sugar & Sweeteners", "item": "Refined Sugar", "variant": "50kg", "pack_size": "KG", "units_per_pack": 50, "base_price": 2050},
        {"category": "Sugar & Sweeteners", "item": "Jaggery Gur", "variant": "30kg", "pack_size": "KG", "units_per_pack": 30, "base_price": 1750},
        {"category": "Salt & Seasoning", "item": "Iodised Salt", "variant": "1kg x 25pc", "pack_size": "PKT", "units_per_pack": 25, "base_price": 300},
        {"category": "Salt & Seasoning", "item": "Turmeric Powder", "variant": "1kg x 10pc", "pack_size": "PKT", "units_per_pack": 10, "base_price": 950},
        {"category": "Salt & Seasoning", "item": "Cumin Whole", "variant": "5kg", "pack_size": "KG", "units_per_pack": 5, "base_price": 1900},
    ]


def generate():
    rng = np.random.default_rng(SEED)
    ROOT.mkdir(parents=True, exist_ok=True)

    suppliers = pd.DataFrame({
        "supplier_id": [f"SUP-{i:03}" for i in range(1, 9)],
        "name": FICTIONAL_SUPPLIER_NAMES,
        "lead_time": rng.integers(3, 16, 8),
        "minimum_order_quantity": [12, 18, 10, 24, 15, 20, 9, 14],
    })
    suppliers.to_csv(ROOT / "suppliers.csv", index=False)

    products = []
    templates = _pack_templates()
    for idx, profile in enumerate(templates):
        for variant_no in range(1, 4):
            product_id = f"SKU-{idx * 3 + variant_no:03}"
            purchase_price = round(float(profile["base_price"] * rng.uniform(0.72, 0.96)), 2)
            selling_price = round(float(purchase_price * rng.uniform(1.18, 1.46)), 2)
            products.append({
                "product_id": product_id,
                "name": f"{profile['item']} {profile['variant']}",
                "brand": FICTIONAL_BRANDS[idx % len(FICTIONAL_BRANDS)],
                "category": profile["category"],
                "pack_size": profile["pack_size"],
                "units_per_pack": profile["units_per_pack"],
                "purchase_price": purchase_price,
                "selling_price": selling_price,
                "supplier_id": suppliers.iloc[(idx + variant_no) % len(suppliers)].supplier_id,
            })
    products = pd.DataFrame(products)
    products.to_csv(ROOT / "products.csv", index=False)

    personal_retailers = [f"{name} {suffix}" for name, suffix in zip(
        RETAILER_PERSONAL_NAMES,
        ["Store", "Grocery", "Store", "Grocery"] * 6,
    )]
    locality_retailers = [
        f"{locality} {suffix}"
        for locality in RETAILER_LOCALITIES
        for suffix in ["VT Store", "Grocery", "Daily Needs"]
    ]
    retailer_names = personal_retailers + locality_retailers
    retailers = pd.DataFrame({
        "retailer_id": [f"RET-{i:03}" for i in range(1, 61)],
        "name": retailer_names,
        "location": rng.choice(RETAILER_LOCALITIES, 60),
        "credit_limit": rng.integers(50000, 350000, 60),
        "payment_terms_days": rng.choice([15, 30, 45, 60], 60),
    })
    retailers.loc[retailers["retailer_id"].map(lambda value: int(value[-3:]) % 11 == 0), "payment_terms_days"] = 30
    retailers.loc[retailers["retailer_id"].map(lambda value: int(value[-3:]) % 13 == 0), "payment_terms_days"] = 60
    retailers.to_csv(ROOT / "retailers.csv", index=False)

    sales_rows = []
    dates = pd.date_range(start=FY_START, end=FY_END, freq="D")
    for product in products.itertuples():
        base_daily_packs = rng.uniform(2.7, 12.2)
        category_factor = {"Atta & Flour": 1.2, "Rice & Grains": 1.15, "Pulses & Dal": 1.05,
                   "Cooking Oil": 0.95, "Sugar & Sweeteners": 1.0, "Salt & Seasoning": 0.8}.get(product.category, 1.0)
        for day in dates:
            month_factor = MONTHLY_SEASONALITY[day.month]
            weekend_factor = 1.35 if day.weekday() >= 5 else 1.0
            promo_factor = 1.12 if day.month in [11, 12, 1, 3] and day.day in [5, 10, 15, 20, 25] else 1.0
            mean_packs = max(0.4, base_daily_packs * month_factor * weekend_factor * category_factor * promo_factor)
            quantity = int(rng.poisson(mean_packs))
            if quantity <= 0:
                continue

            is_counter = rng.random() < COUNTER_SALES_SHARE
            if is_counter:
                retailer_id = np.nan
                sale_channel = "Counter"
                quantity = max(1, int(quantity * rng.uniform(0.25, 0.65)))
                selling_price = round(float(product.selling_price * rng.uniform(0.82, 0.96)), 2)
                quantity = max(1, int(np.ceil(500 / selling_price)))
                quantity = min(quantity, max(1, int(15000 / selling_price)))
            else:
                retailer_id = retailers.iloc[int(rng.integers(0, len(retailers)))].retailer_id
                sale_channel = "Retailer"
                selling_price = round(float(product.selling_price * rng.uniform(0.96, 1.08)), 2)

            sales_rows.append({
                "date": day.date(),
                "due_date": (day + pd.Timedelta(days=int(retailers.loc[retailers["retailer_id"] == retailer_id, "payment_terms_days"].iloc[0]))).date() if not is_counter else pd.NaT,
                "product_id": product.product_id,
                "retailer_id": retailer_id,
                "sale_channel": sale_channel,
                "quantity": quantity,
                "selling_price": selling_price,
            })

    sales = pd.DataFrame(sales_rows)
    sales.to_csv(ROOT / "sales.csv", index=False)

    retailer_revenue = (sales[sales["retailer_id"].notna()]
                         .assign(revenue=lambda frame: frame["quantity"] * frame["selling_price"])
                         .groupby("retailer_id")["revenue"].sum())
    retailers["credit_limit"] = retailers["credit_limit"].astype(float)
    for index, retailer in retailers.iterrows():
        behavior = int(retailer.retailer_id[-3:])
        limit_ratio = 0.15 if behavior % 17 == 0 else 0.42 if behavior % 9 == 0 else 3.0
        retailers.loc[index, "credit_limit"] = round(float(retailer_revenue.get(retailer.retailer_id, 0)) * limit_ratio, 2)
    retailers.to_csv(ROOT / "retailers.csv", index=False)

    purchase_source = sales.merge(products[["product_id", "purchase_price", "supplier_id"]], on="product_id")
    purchase_source["date"] = pd.to_datetime(purchase_source["date"])
    purchase_source["purchase_window"] = ((purchase_source["date"] - FY_START).dt.days // 7)
    purchase_source["purchase_date"] = FY_START + pd.to_timedelta(purchase_source["purchase_window"] * 7, unit="D")
    purchase_source["quantity"] = np.ceil(purchase_source["quantity"] * 1.08).astype(int)
    purchase_items = (purchase_source.groupby(["supplier_id", "purchase_date", "product_id", "purchase_price"], as_index=False)
                      .agg(quantity=("quantity", "sum")))
    purchase_items["quantity"] = purchase_items["quantity"].clip(lower=5, upper=100)
    purchase_items["unit_cost"] = (purchase_items["purchase_price"] * rng.uniform(0.98, 1.03, len(purchase_items))).round(2)
    purchase_items["amount"] = (purchase_items["quantity"] * purchase_items["unit_cost"]).round(2)
    purchase_items["purchase_id"] = [f"PUR-{date.strftime('%Y%m%d')}-{supplier}" for date, supplier in
                                      zip(purchase_items.purchase_date, purchase_items.supplier_id)]
    purchase_items["purchase_item_id"] = [f"{purchase_id}-I-{index:03}" for index, purchase_id in
                                           enumerate(purchase_items.purchase_id, 1)]
    purchases = (purchase_items.groupby(["purchase_id", "supplier_id", "purchase_date"], as_index=False)
                 .agg(total_amount=("amount", "sum")))
    purchases["date"] = purchases["purchase_date"].dt.date
    purchases["invoice_reference"] = purchases.purchase_id.map(lambda value: f"INV-{value[4:]}")
    purchases[["purchase_id", "date", "supplier_id", "invoice_reference", "total_amount"]].to_csv(
        ROOT / "purchases.csv", index=False)
    purchase_items[
        ["purchase_item_id", "purchase_id", "product_id", "quantity", "unit_cost", "amount"]
    ].to_csv(ROOT / "purchase_items.csv", index=False)

    expense_categories = [
        ("Rent", "Monthly warehousing and office occupancy", 115000, "Bank Transfer"),
        ("Vehicle Maintenance", "Fleet servicing and tyre replacement", 22000, "Bank Transfer"),
        ("Labour", "Wages and dispatch helper support", 80000, "Bank Transfer"),
        ("Fuel", "Delivery and field movement expense", 18000, "Cash"),
        ("Utilities", "Power, water, and telecom", 15000, "UPI"),
        ("Freight", "Third-party transport and handling", 26000, "Bank Transfer"),
    ]
    expenses = []
    month_timestamps = pd.date_range(start=FY_START, end=FY_END, freq="MS")
    for month_start in month_timestamps:
        month_index = int(month_start.strftime("%m"))
        month_year = int(month_start.strftime("%Y"))
        for idx, (category, description, baseline_amount, payment_method) in enumerate(expense_categories):
            month_end = month_start + pd.offsets.MonthEnd(0)
            if category == "Rent":
                amount = baseline_amount
                if month_start == FY_START:
                    event_date = FY_START
                elif month_start == FY_END:
                    event_date = FY_END
                else:
                    event_date = month_end
            elif category == "Labour":
                amount = baseline_amount + rng.integers(-7000, 9000)
                event_date = month_end - pd.Timedelta(days=2)
            elif category == "Utilities":
                amount = baseline_amount + rng.integers(-3000, 5000)
                event_date = month_end - pd.Timedelta(days=1)
            elif category == "Fuel":
                amount = int(baseline_amount * rng.uniform(0.78, 1.36))
                event_date = month_start + pd.Timedelta(days=rng.integers(0, 15))
            elif category == "Vehicle Maintenance":
                amount = int(baseline_amount * rng.uniform(0.7, 1.9)) if rng.random() < 0.8 else 0
                if amount == 0:
                    continue
                event_date = month_start + pd.Timedelta(days=rng.integers(0, 20))
            else:  # Freight
                amount = int(baseline_amount * rng.uniform(0.6, 1.75))
                event_date = month_start + pd.Timedelta(days=rng.integers(0, 18))
            expenses.append({
                "expense_id": f"EXP-{month_year}-{month_index:02}-{idx + 1:02}",
                "date": event_date.date(),
                "category": category,
                "description": description,
                "amount": round(float(amount), 2),
                "payment_method": payment_method,
            })
    expenses = pd.DataFrame(expenses)
    expenses.to_csv(ROOT / "expenses.csv", index=False)

    purchases["month"] = purchases["date"].pipe(pd.to_datetime).dt.to_period("M")
    monthly_purchases = purchases.groupby(["supplier_id", "month"], as_index=False)["total_amount"].sum()
    settling_supplier = suppliers.iloc[0].supplier_id
    payment_rows = []
    payment_counter = 1
    for supplier_id in suppliers["supplier_id"]:
        running_balance = 0.0
        for month_start in month_timestamps:
            month = month_start.to_period("M")
            purchase_total = monthly_purchases.loc[
                (monthly_purchases["supplier_id"] == supplier_id) & (monthly_purchases["month"] == month),
                "total_amount",
            ].sum()
            running_balance += float(purchase_total)
            if running_balance <= 0:
                continue
            if supplier_id == settling_supplier and month == FY_END.to_period("M"):
                amount = running_balance
            elif purchase_total > 0:
                amount = min(running_balance, float(purchase_total) * float(rng.uniform(0.68, 0.9)))
            else:
                continue
            payment_rows.append({
                "payment_id": f"PAY-{payment_counter:04}",
                "date": (month_start + pd.offsets.MonthEnd(0)).date(),
                "supplier_id": supplier_id,
                "amount": round(amount, 2),
                "payment_method": rng.choice(["Bank Transfer", "NEFT", "RTGS"]),
            })
            running_balance -= amount
            payment_counter += 1
    pd.DataFrame(payment_rows).to_csv(ROOT / "supplier_payments.csv", index=False)

    retailer_profiles = retailers.set_index("retailer_id")
    retailer_sales = sales[sales["retailer_id"].notna()].copy()
    retailer_sales["revenue"] = retailer_sales["quantity"] * retailer_sales["selling_price"]
    retailer_sales["date"] = pd.to_datetime(retailer_sales["date"])
    retailer_sales["due_date"] = pd.to_datetime(retailer_sales["due_date"])
    retailer_payment_rows = []
    payment_counter = 1
    for retailer_id, invoices in retailer_sales.groupby("retailer_id"):
        behavior = int(retailer_id[-3:])
        if behavior % 13 == 0:
            payment_rate, delay_days = 1.0, 2
        elif behavior % 11 == 0:
            payment_rate, delay_days = 1.0, 0
        elif behavior % 17 == 0:
            payment_rate, delay_days = 0.55, 75
        elif behavior % 9 == 0:
            payment_rate, delay_days = 0.82, 18
        else:
            payment_rate, delay_days = 1.0, 2
        for _, monthly in invoices.groupby(invoices["date"].dt.to_period("M")):
            if behavior % 11 == 0 and monthly["date"].max().to_period("M") == FY_END.to_period("M"):
                continue
            amount = float(monthly["revenue"].sum()) * payment_rate
            payment_date = monthly["due_date"].max() + pd.Timedelta(days=delay_days)
            if behavior % 13 == 0:
                payment_date = min(payment_date, FY_END)
            if payment_date > FY_END:
                continue
            retailer_payment_rows.append({"payment_id": f"RPAY-{payment_counter:04}", "date": payment_date.date(),
                                          "retailer_id": retailer_id, "amount": round(amount, 2),
                                          "payment_method": rng.choice(["Bank Transfer", "UPI", "NEFT"])})
            payment_counter += 1
    pd.DataFrame(retailer_payment_rows).to_csv(ROOT / "retailer_payments.csv", index=False)

    stock_rows = []
    sales_by_product = sales.groupby("product_id")["quantity"].sum()
    for product in products.itertuples():
        sold = int(sales_by_product.get(product.product_id, 0))
        stock_rows.append({"product_id": product.product_id,
                           "quantity": max(40, int(sold * rng.uniform(0.08, 0.24))),
                           "reserved_quantity": int(rng.integers(0, 20))})
    pd.DataFrame(stock_rows).to_csv(ROOT / "inventory.csv", index=False)

    monthly_revenue = (
        sales.assign(revenue=sales["quantity"] * sales["selling_price"])
        .assign(month=pd.to_datetime(sales["date"]).dt.to_period("M").astype(str))
        .groupby("month", as_index=False)["revenue"].sum()
        .sort_values("month")
    )
    summary = {
        "sales_rows": len(sales),
        "products_rows": len(products),
        "retailer_rows": len(retailers),
        "supplier_rows": len(suppliers),
        "supplier_payment_rows": len(payment_rows),
        "retailer_payment_rows": len(retailer_payment_rows),
        "inventory_rows": len(stock_rows),
        "date_min": sales["date"].min(),
        "date_max": sales["date"].max(),
        "monthly_revenue": monthly_revenue,
    }
    return summary


if __name__ == "__main__":
    summary = generate()
    print(f"Products: {summary['products_rows']}")
    print(f"Retailers: {summary['retailer_rows']}")
    print(f"Suppliers: {summary['supplier_rows']}")
    print(f"Sales rows: {summary['sales_rows']}")
    print(f"Inventory products: {summary['inventory_rows']}")
    print(f"Date range: {summary['date_min']} to {summary['date_max']}")
    print("\nMonthly revenue:")
    print(summary["monthly_revenue"].to_string(index=False))
    print(f"\nGenerated sample CSVs in {ROOT}")
