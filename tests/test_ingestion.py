from io import BytesIO
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.main import app
from app.database.session import Base, get_db
from app.services.auth import get_current_user
from app.models.domain import Brand, Category, InventoryStock, Product, Supplier


def test_product_csv_upload_persists_rows_and_skips_duplicates():
    """Uploads product CSV rows, queries SQLite, and verifies upsert plus duplicate handling."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: None
    client = TestClient(app)
    csv = "product_id,name,brand,category,purchase_price,selling_price,supplier_id\nSKU-TEST,Test Rice,Test Brand,Rice & Grains,10,15,SUP-TEST\nSKU-TEST,Test Rice,Test Brand,Rice & Grains,10,15,SUP-TEST\n"
    response = client.post("/data/upload", data={"dataset_type": "products"}, files={"file": ("products.csv", BytesIO(csv.encode()), "text/csv")})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["rows_received"] == 2
    assert response.json()["rows_inserted"] == 1
    assert response.json()["rows_skipped"] == 1
    with session_factory() as db:
        product = db.scalar(select(Product).where(Product.product_id == "SKU-TEST"))
        assert product is not None
        assert product.name == "Test Rice"
        assert product.selling_price == 15
        assert db.scalar(select(Supplier).where(Supplier.supplier_code == "SUP-TEST")) is not None
        assert db.scalar(select(Category).where(Category.name == "Rice & Grains")) is not None
    engine.dispose()


def test_invalid_row_rolls_back_entire_upload():
    """Confirms a row-level foreign-key failure leaves earlier rows uncommitted."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    from app.services.ingestion import IngestionError, ingest_dataframe
    app.dependency_overrides[get_current_user] = lambda: None

    with session_factory() as db:
        category = Category(name="Pulses & Dal")
        brand = Brand(name="Brand")
        supplier = Supplier(supplier_code="SUP-1", name="Supplier")
        db.add_all([category, brand, supplier])
        db.flush()
        db.add(Product(product_id="SKU-1", name="One", category=category, brand=brand, supplier=supplier,
                       purchase_price=5, selling_price=8))
        db.commit()
        frame = pd.DataFrame([
            {"product_id": "SKU-1", "quantity": 10, "reserved_quantity": 0},
            {"product_id": "UNKNOWN", "quantity": 10, "reserved_quantity": 0},
        ])
        try:
            ingest_dataframe(db, frame, "inventory")
        except IngestionError:
            pass
        else:
            raise AssertionError("Expected ingestion to fail")
        assert db.scalar(select(InventoryStock).where(InventoryStock.product_id == 1)) is None
    app.dependency_overrides.clear()
    engine.dispose()