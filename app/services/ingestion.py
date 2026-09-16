from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import (Brand, Category, Expense, InventoryStock, Product, Purchase, PurchaseItem,
                               Retailer, RetailerPayment, Sale, Supplier, SupplierPayment)
from app.services.validation import validate_csv


class IngestionError(ValueError):
    pass


@dataclass(frozen=True)
class IngestionResult:
    dataset_type: str
    rows_received: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int


def _date(value) -> date:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise IngestionError(f"Invalid date: {value}")
    return parsed.date()


def _number(value, field: str) -> Decimal:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        raise IngestionError(f"Invalid numeric value for {field}: {value}")
    return Decimal(str(parsed))


def _supplier(db: Session, code: str) -> Supplier:
    supplier = db.scalar(select(Supplier).where(Supplier.supplier_code == code))
    if supplier is None:
        supplier = Supplier(supplier_code=code, name=code)
        db.add(supplier)
        db.flush()
    return supplier


def _category(db: Session, name: str) -> Category:
    category = db.scalar(select(Category).where(Category.name == name))
    if category is None:
        category = Category(name=name)
        db.add(category)
        db.flush()
    return category


def _brand(db: Session, name: str) -> Brand:
    brand = db.scalar(select(Brand).where(Brand.name == name))
    if brand is None:
        brand = Brand(name=name)
        db.add(brand)
        db.flush()
    return brand


def _product(db: Session, code: str) -> Product:
    product = db.scalar(select(Product).where(Product.product_id == code))
    if product is None:
        raise IngestionError(f"Unknown product_id: {code}")
    return product


def _retailer(db: Session, code: str) -> Retailer:
    retailer = db.scalar(select(Retailer).where(Retailer.retailer_id == code))
    if retailer is None:
        raise IngestionError(f"Unknown retailer_id: {code}")
    return retailer


def _upsert_supplier(db: Session, row) -> str:
    code = str(row.supplier_id)
    supplier = db.scalar(select(Supplier).where(Supplier.supplier_code == code))
    if supplier is None:
        supplier = Supplier(supplier_code=code, name=str(row.name))
        db.add(supplier)
    else:
        supplier.name = str(row.name)
    supplier.lead_time_days = int(_number(row.lead_time, "lead_time"))
    supplier.minimum_order_quantity = int(_number(row.minimum_order_quantity, "minimum_order_quantity"))
    return "inserted" if supplier.id is None else "updated"


def _upsert_product(db: Session, row) -> str:
    product = db.scalar(select(Product).where(Product.product_id == str(row.product_id)))
    category = _category(db, str(row.category))
    brand = _brand(db, str(row.brand))
    supplier = _supplier(db, str(row.supplier_id))
    if product is None:
        product = Product(product_id=str(row.product_id), name=str(row.name), category=category,
                          brand=brand, supplier=supplier, purchase_price=_number(row.purchase_price, "purchase_price"),
                          selling_price=_number(row.selling_price, "selling_price"))
        db.add(product)
        return "inserted"
    product.name = str(row.name)
    product.category = category
    product.brand = brand
    product.supplier = supplier
    product.purchase_price = _number(row.purchase_price, "purchase_price")
    product.selling_price = _number(row.selling_price, "selling_price")
    return "updated"


def _upsert_retailer(db: Session, row) -> str:
    retailer = db.scalar(select(Retailer).where(Retailer.retailer_id == str(row.retailer_id)))
    terms = getattr(row, "payment_terms_days", getattr(row, "payment_terms", None))
    values = {"name": str(row.name), "location": str(row.location),
              "credit_limit": _number(row.credit_limit, "credit_limit"),
              "payment_terms_days": int(_number(terms, "payment_terms_days"))}
    if retailer is None:
        db.add(Retailer(retailer_id=str(row.retailer_id), **values))
        return "inserted"
    for key, value in values.items():
        setattr(retailer, key, value)
    return "updated"


def _upsert_inventory(db: Session, row) -> str:
    product = _product(db, str(row.product_id))
    stock = db.scalar(select(InventoryStock).where(InventoryStock.product_id == product.id))
    values = {"product_id": product.id, "quantity": int(_number(row.quantity, "quantity")),
              "reserved_quantity": int(_number(row.reserved_quantity, "reserved_quantity"))}
    if stock is None:
        db.add(InventoryStock(**values))
        return "inserted"
    for key, value in values.items():
        setattr(stock, key, value)
    return "updated"


def _insert_sale(db: Session, row) -> str:
    product = _product(db, str(row.product_id))
    retailer_id = None
    retailer = None
    raw_retailer_id = getattr(row, "retailer_id", None)
    if raw_retailer_id is not None and not pd.isna(raw_retailer_id):
        retailer_id = str(raw_retailer_id).strip()
        retailer = _retailer(db, retailer_id)
    sale_date = _date(row.date)
    quantity = int(_number(row.quantity, "quantity"))
    selling_price = _number(row.selling_price, "selling_price")
    duplicate_filter = [
        Sale.sale_date == sale_date,
        Sale.product_id == product.id,
        Sale.quantity == quantity,
        Sale.selling_price == selling_price,
    ]
    if retailer is not None:
        duplicate_filter.append(Sale.retailer_id == retailer.id)
    else:
        duplicate_filter.append(Sale.retailer_id.is_(None))
    duplicate = db.scalar(select(Sale).where(*duplicate_filter))
    if duplicate is not None:
        return "skipped"
    due_date = sale_date + pd.Timedelta(days=retailer.payment_terms_days) if retailer is not None else None
    db.add(Sale(sale_date=sale_date, due_date=due_date, product_id=product.id, retailer_id=retailer.id if retailer is not None else None,
                quantity=quantity, selling_price=selling_price, purchase_cost=product.purchase_price))
    return "inserted"


def _insert_expense(db: Session, row) -> str:
    expense_id = str(row.expense_id)
    if db.scalar(select(Expense).where(Expense.expense_id == expense_id)) is not None:
        return "skipped"
    db.add(Expense(expense_id=expense_id, date=_date(row.date), category=str(row.category),
                   description=str(row.description), amount=_number(row.amount, "amount"),
                   payment_method=str(row.payment_method)))
    return "inserted"


def _insert_supplier_payment(db: Session, row) -> str:
    payment_id = str(row.payment_id)
    if db.scalar(select(SupplierPayment).where(SupplierPayment.payment_id == payment_id)) is not None:
        return "skipped"
    supplier = _supplier(db, str(row.supplier_id))
    db.add(SupplierPayment(payment_id=payment_id, date=_date(row.date), supplier_id=supplier.id,
                           amount=_number(row.amount, "amount"), payment_method=str(row.payment_method)))
    return "inserted"


def _insert_retailer_payment(db: Session, row) -> str:
    payment_id = str(row.payment_id)
    if db.scalar(select(RetailerPayment).where(RetailerPayment.payment_id == payment_id)) is not None:
        return "skipped"
    retailer = _retailer(db, str(row.retailer_id))
    db.add(RetailerPayment(payment_id=payment_id, date=_date(row.date), retailer_id=retailer.id,
                           amount=_number(row.amount, "amount"), payment_method=str(row.payment_method)))
    return "inserted"


def _insert_purchase(db: Session, row) -> str:
    purchase_id = str(row.purchase_id)
    if db.scalar(select(Purchase).where(Purchase.purchase_id == purchase_id)) is not None:
        return "skipped"
    supplier = _supplier(db, str(row.supplier_id))
    db.add(Purchase(purchase_id=purchase_id, date=_date(row.date), supplier=supplier,
                    invoice_reference=str(row.invoice_reference),
                    total_amount=_number(row.total_amount, "total_amount")))
    return "inserted"


def _insert_purchase_item(db: Session, row) -> str:
    purchase_item_id = str(row.purchase_item_id)
    if db.scalar(select(PurchaseItem).where(PurchaseItem.purchase_item_id == purchase_item_id)) is not None:
        return "skipped"
    purchase = db.scalar(select(Purchase).where(Purchase.purchase_id == str(row.purchase_id)))
    if purchase is None:
        raise IngestionError(f"Unknown purchase_id: {row.purchase_id}")
    product = _product(db, str(row.product_id))
    db.add(PurchaseItem(purchase_item_id=purchase_item_id, purchase=purchase, product=product,
                        quantity=int(_number(row.quantity, "quantity")),
                        unit_cost=_number(row.unit_cost, "unit_cost"),
                        amount=_number(row.amount, "amount")))
    return "inserted"


def ingest_dataframe(db: Session, frame: pd.DataFrame, dataset_type: str) -> IngestionResult:
    validation = validate_csv(frame, dataset_type)
    if not validation.valid:
        raise IngestionError("; ".join(validation.errors))
    rows = frame.drop_duplicates().to_dict(orient="records")
    received = len(frame)
    inserted = updated = skipped = 0
    handlers = {"suppliers": _upsert_supplier, "products": _upsert_product,
                "retailers": _upsert_retailer, "inventory": _upsert_inventory, "sales": _insert_sale,
                "expenses": _insert_expense, "supplier_payments": _insert_supplier_payment,
                "retailer_payments": _insert_retailer_payment,
                "purchases": _insert_purchase, "purchase_items": _insert_purchase_item}
    handler = handlers[dataset_type]
    try:
        with db.begin():
            for record in rows:
                result = handler(db, type("CsvRow", (), record)())
                if result == "inserted":
                    inserted += 1
                elif result == "updated":
                    updated += 1
                else:
                    skipped += 1
    except Exception as exc:
        db.rollback()
        if isinstance(exc, IngestionError):
            raise
        raise IngestionError(f"Upload rolled back: {exc}") from exc
    skipped += received - len(rows)
    return IngestionResult(dataset_type, received, inserted, updated, skipped)