from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.main import app
from app.database.session import Base, get_db
from app.models.domain import Brand, Category, InventoryStock, Product, Retailer, Sale, Supplier
from app.services.auth import get_current_user


def test_recommendation_lifecycle_is_persisted():
    """Generates, queries, modifies, approves, and re-queries one recommendation."""
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
    with session_factory() as db:
        category = Category(name="Biscuits")
        brand = Brand(name="Brand")
        supplier = Supplier(supplier_code="SUP-1", name="Supplier", lead_time_days=5, minimum_order_quantity=10)
        retailer = Retailer(retailer_id="RET-1", name="Retailer", location="North")
        db.add_all([category, brand, supplier, retailer])
        db.flush()
        product = Product(product_id="SKU-1", name="Rice A", category=category, brand=brand, supplier=supplier,
                  purchase_price=10, selling_price=15)
        db.add(product)
        db.flush()
        db.add(InventoryStock(product_id=product.id, quantity=10, reserved_quantity=0))
        db.add(Sale(sale_date=date.today() - timedelta(days=10), product_id=product.id, retailer_id=retailer.id,
                    quantity=20, selling_price=15, purchase_cost=10))
        db.commit()

    client = TestClient(app)
    generated_response = client.post("/reorder-recommendations/generate")
    assert generated_response.status_code == 200
    generated = generated_response.json()["recommendations"][0]
    assert generated["status"] == "generated"
    assert generated["current_stock"] == 10
    assert generated["forecast_demand"] > 0
    assert generated["reason"]

    listed_response = client.get("/reorder-recommendations?status=generated")
    assert listed_response.status_code == 200
    assert listed_response.json()[0]["id"] == generated["id"]

    recommendation_id = generated["id"]
    modified_response = client.patch(f"/reorder-recommendations/{recommendation_id}", json={"action": "modified", "quantity": 25})
    assert modified_response.status_code == 200
    assert modified_response.json()["status"] == "modified"
    assert modified_response.json()["modified_quantity"] == 25

    approved_response = client.patch(f"/reorder-recommendations/{recommendation_id}", json={"action": "approved"})
    assert approved_response.status_code == 200
    assert approved_response.json()["status"] == "approved"
    assert approved_response.json()["modified_quantity"] == 25

    with session_factory() as db:
        from app.models.domain import ReorderRecommendation
        stored = db.get(ReorderRecommendation, recommendation_id)
        assert stored.status == "approved"
        assert stored.modified_quantity == 25
        assert stored.decided_at is not None
    app.dependency_overrides.clear()
    engine.dispose()