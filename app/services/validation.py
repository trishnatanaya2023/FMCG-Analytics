from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str]


REQUIRED_COLUMNS = {
    "sales": {"date", "product_id", "retailer_id", "quantity", "selling_price"},
    "products": {"product_id", "name", "brand", "category", "purchase_price", "selling_price", "shelf_life", "supplier_id"},
    "inventory": {"product_id", "batch_id", "quantity", "manufacturing_date", "expiry_date"},
    "retailers": {"retailer_id", "name", "location", "credit_limit", "payment_terms"},
    "suppliers": {"supplier_id", "name", "lead_time", "minimum_order_quantity"},
}


def validate_csv(frame: pd.DataFrame, dataset_type: str = "sales") -> ValidationResult:
    errors: list[str] = []
    if dataset_type not in REQUIRED_COLUMNS:
        return ValidationResult(False, [f"Unsupported dataset type: {dataset_type}"])
    if frame.empty:
        return ValidationResult(False, ["CSV file is empty"])
    missing = sorted(REQUIRED_COLUMNS[dataset_type] - set(frame.columns))
    if missing:
        errors.append(f"Missing required columns: {', '.join(missing)}")
    for column in ["quantity", "selling_price", "purchase_price", "credit_limit", "lead_time", "minimum_order_quantity", "payment_terms", "shelf_life"]:
        if column in frame.columns and pd.to_numeric(frame[column], errors="coerce").isna().any():
            errors.append(f"Column '{column}' must contain numeric values")
    if "date" in frame.columns and pd.to_datetime(frame["date"], errors="coerce").isna().any():
        errors.append("Column 'date' must contain valid dates")
    for column in ["manufacturing_date", "expiry_date"]:
        if column in frame.columns and pd.to_datetime(frame[column], errors="coerce").isna().any():
            errors.append(f"Column '{column}' must contain valid dates")
    if "quantity" in frame.columns:
        quantity = pd.to_numeric(frame["quantity"], errors="coerce")
        if quantity.notna().any() and (quantity.dropna() < 0).any():
            errors.append("Column 'quantity' cannot contain negative values")
    return ValidationResult(not errors, errors)