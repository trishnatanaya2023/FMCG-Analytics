from pathlib import Path

import pandas as pd


def load_sample_data(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    products = pd.read_csv(root / "products.csv")
    sales = pd.read_csv(root / "sales.csv", parse_dates=["date"])
    inventory = pd.read_csv(root / "inventory.csv", parse_dates=["manufacturing_date", "expiry_date"])
    retailers = pd.read_csv(root / "retailers.csv")
    suppliers = pd.read_csv(root / "suppliers.csv")
    sales = sales.merge(products[["product_id", "purchase_price", "name", "category", "brand", "supplier_id"]],
                        on="product_id")
    sales["purchase_cost"] = sales["purchase_price"]
    return products, sales, inventory, retailers, suppliers