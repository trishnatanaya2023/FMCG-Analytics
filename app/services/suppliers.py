import pandas as pd


def supplier_product_counts(products: pd.DataFrame) -> pd.DataFrame:
    return products.groupby("supplier_id").size().rename("products_supplied").reset_index()


def supplier_product_summary(products: pd.DataFrame, suppliers: pd.DataFrame) -> pd.DataFrame:
    counts = supplier_product_counts(products)
    return suppliers.merge(counts, on="supplier_id", how="left").fillna(0)