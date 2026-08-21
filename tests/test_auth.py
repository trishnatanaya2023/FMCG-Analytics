from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.main import app
from app.config import get_settings
from app.database.session import Base, get_db
from app.models.domain import User
from app.services.auth import PBKDF2_ITERATIONS, hash_password


def test_pbkdf2_iteration_policy_meets_minimum():
    """Checks that generated PBKDF2-HMAC-SHA256 hashes use at least 600,000 rounds."""
    generated_hash = hash_password("policy-check-password")
    rounds = int(generated_hash.split("$")[2])
    assert PBKDF2_ITERATIONS >= 600_000
    assert rounds >= 600_000


def test_login_flow_rejects_anonymous_and_allows_valid_token(monkeypatch):
    """Confirms anonymous rejection, JWT issuance, and authenticated API access."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-only")
    get_settings.cache_clear()
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
    with session_factory.begin() as db:
        db.add(User(username="operator", password_hash=hash_password("correct-password")))

    client = TestClient(app)
    anonymous = client.get("/products")
    assert anonymous.status_code == 401

    login = client.post("/auth/login", json={"username": "operator", "password": "correct-password"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert login.json()["token_type"] == "bearer"

    authenticated = client.get("/products", headers={"Authorization": f"Bearer {token}"})
    assert authenticated.status_code == 200
    assert authenticated.json()

    app.dependency_overrides.clear()
    engine.dispose()
    get_settings.cache_clear()