"""Create reproducible CSV fixtures for local development."""
from pathlib import Path
import numpy as np
import pandas as pd

SEED = 42
ROOT = Path(__file__).resolve().parents[1] / "data" / "sample"


def generate():
    rng = np.random.default_rng(SEED)
    ROOT.mkdir(parents=True, exist_ok=True)
    categories = ["Biscuits", "Beverages", "Snacks", "Dairy", "Staples", "Personal Care", "Home Care", "Confectionery", "Breakfast", "Baby Care"]
    brands = ["SunVale", "FreshField", "DailyDrop", "HarvestCo", "GoodBasket"]
    suppliers = pd.DataFrame({"supplier_id": [f"SUP-{i:03}" for i in range(1, 6)], "name": [f"{b} Distribution" for b in brands], "lead_time": rng.integers(3, 15, 5), "minimum_order_quantity": [12, 24, 10, 20, 6]})
    suppliers.to_csv(ROOT / "suppliers.csv", index=False)
    products = []
    for i in range(50):
        purchase = round(float(rng.uniform(12, 180)), 2)
        products.append({"product_id": f"SKU-{i+1:03}", "name": f"{brands[i % 5]} {categories[i % 10]} {i+1}", "brand": brands[i % 5], "category": categories[i % 10], "purchase_price": purchase, "selling_price": round(purchase * rng.uniform(1.18, 1.48), 2), "shelf_life": int(rng.choice([60, 90, 180, 365])), "supplier_id": suppliers.iloc[i % 5].supplier_id})
    products = pd.DataFrame(products)
    products.to_csv(ROOT / "products.csv", index=False)
    retailers = pd.DataFrame({"retailer_id": [f"RET-{i+1:03}" for i in range(100)], "name": [f"Retailer {i+1:03}" for i in range(100)], "location": rng.choice(["North", "South", "East", "West", "Central"], 100), "credit_limit": rng.integers(50000, 300000, 100), "payment_terms": rng.choice([15, 30, 45], 100)})
    retailers.to_csv(ROOT / "retailers.csv", index=False)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=365, freq="D")
    rows = []
    for product in products.itertuples():
        base = rng.uniform(5, 45)
        for day in dates:
            seasonal = 1 + 0.18 * np.sin(2 * np.pi * day.dayofyear / 365) + (0.25 if day.month in [10, 11] else 0)
            quantity = max(0, int(rng.poisson(base * seasonal * (1.1 if day.weekday() in [4, 5] else 0.9))))
            if quantity:
                retailer = retailers.iloc[int(rng.integers(0, len(retailers)))]
                rows.append({"date": day.date(), "product_id": product.product_id, "retailer_id": retailer.retailer_id, "quantity": quantity, "selling_price": product.selling_price})
    pd.DataFrame(rows).to_csv(ROOT / "sales.csv", index=False)
    today = pd.Timestamp.today().normalize()
    batches = []
    for product in products.itertuples():
        for batch_no in range(2):
            manufactured = today - pd.Timedelta(days=int(rng.integers(10, max(20, product.shelf_life - 5))))
            expiry = manufactured + pd.Timedelta(days=product.shelf_life)
            batches.append({"product_id": product.product_id, "batch_id": f"{product.product_id}-B{batch_no+1}", "quantity": int(rng.integers(30, 500)), "manufacturing_date": manufactured.date(), "expiry_date": expiry.date()})
    pd.DataFrame(batches).to_csv(ROOT / "inventory.csv", index=False)


if __name__ == "__main__":
    generate()
    print(f"Generated sample CSVs in {ROOT}")
