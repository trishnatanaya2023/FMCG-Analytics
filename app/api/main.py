from pathlib import Path
import pandas as pd
from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.models.domain import ReorderRecommendation
from app.services.auth import authenticate_user, create_access_token, get_current_user
from app.services.forecasting import forecast_product_from_csv, normalize_forecast_horizon
from app.services.formatting import format_currency
from app.services.ingestion import IngestionError, ingest_dataframe
from app.services.recommendations import generate_recommendations, list_recommendations, update_recommendation
from app.services.validation import validate_csv

app = FastAPI(title="DistribuSense API", version="0.1.0")
ROOT = Path(__file__).resolve().parents[2] / "data" / "sample"


class RecommendationAction(BaseModel):
    action: str = Field(pattern="^(approved|modified|rejected)$")
    quantity: int | None = Field(default=None, ge=0)


class LoginRequest(BaseModel):
    username: str
    password: str


def _recommendation_payload(recommendation: ReorderRecommendation) -> dict:
    return {
        "id": recommendation.id,
        "product_id": recommendation.product_id,
        "supplier_id": recommendation.supplier_id,
        "forecast_demand": recommendation.forecast_demand,
        "current_stock": recommendation.current_stock,
        "incoming_stock": recommendation.incoming_stock,
        "safety_stock": recommendation.safety_stock,
        "reorder_point": recommendation.reorder_point,
        "estimated_stockout_date": recommendation.estimated_stockout_date,
        "recommended_quantity": recommendation.recommended_quantity,
        "modified_quantity": recommendation.modified_quantity,
        "status": recommendation.status,
        "reason": recommendation.reason,
        "created_at": recommendation.created_at,
        "decided_at": recommendation.decided_at,
    }


def read_csv(name: str) -> pd.DataFrame:
    path = ROOT / name
    if not path.exists():
        raise HTTPException(503, "Sample data has not been generated")
    return pd.read_csv(path)


@app.get("/health")
def health():
    return {"status": "ok", "service": "distribusense"}


@app.post("/auth/login")
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, credentials.username, credentials.password)
    if user is None:
        raise HTTPException(401, "Invalid username or password", headers={"WWW-Authenticate": "Bearer"})
    try:
        token = create_access_token(user.username)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"access_token": token, "token_type": "bearer", "username": user.username}


@app.get("/products")
def products(_: object = Depends(get_current_user)):
    records = read_csv("products.csv").to_dict(orient="records")
    for record in records:
        record["purchase_price_formatted"] = format_currency(record["purchase_price"], 2)
        record["selling_price_formatted"] = format_currency(record["selling_price"], 2)
    return records


@app.get("/sales")
def sales(product_id: str | None = None, _: object = Depends(get_current_user)):
    data = read_csv("sales.csv")
    if product_id:
        data = data[data.product_id == product_id]
    records = data.to_dict(orient="records")
    for record in records:
        record["selling_price_formatted"] = format_currency(record["selling_price"], 2)
    return records


@app.get("/inventory")
def inventory(_: object = Depends(get_current_user)):
    return read_csv("inventory.csv").to_dict(orient="records")


@app.post("/reorder-recommendations/generate")
def generate_reorder_recommendations(db: Session = Depends(get_db), _: object = Depends(get_current_user)):
    recommendations = generate_recommendations(db)
    return {"count": len(recommendations), "recommendations": [_recommendation_payload(item) for item in recommendations]}


@app.get("/reorder-recommendations")
def list_reorder_recommendations(status: str | None = None, db: Session = Depends(get_db), _: object = Depends(get_current_user)):
    return [_recommendation_payload(item) for item in list_recommendations(db, status)]


@app.patch("/reorder-recommendations/{recommendation_id}")
def act_on_recommendation(recommendation_id: int, action: RecommendationAction, db: Session = Depends(get_db), _: object = Depends(get_current_user)):
    try:
        recommendation = update_recommendation(db, recommendation_id, action.action, action.quantity)
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 400, str(exc)) from exc
    return _recommendation_payload(recommendation)


@app.get("/forecast/{product_id}")
def forecast(product_id: str, horizon: int = 30, _: object = Depends(get_current_user)):
    clamped_horizon = normalize_forecast_horizon(horizon)
    try:
        result = forecast_product_from_csv(ROOT, product_id, clamped_horizon)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"product_id": product_id, "model": result.model_name, "mae": result.mae, "rmse": result.rmse, "forecast": [{"date": str(day.date()), "units": units, "lower": lower, "upper": upper} for day, units, lower, upper in zip(result.dates, result.values, result.lower, result.upper)]}


@app.post("/data/upload")
async def upload_data(file: UploadFile = File(...), dataset_type: str = Form("sales"), db: Session = Depends(get_db), _: object = Depends(get_current_user)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files are accepted")
    contents = await file.read()
    try:
        frame = pd.read_csv(pd.io.common.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(400, f"Invalid CSV: {exc}") from exc
    validation = validate_csv(frame, dataset_type)
    if not validation.valid:
        raise HTTPException(400, detail={"message": "CSV validation failed", "errors": validation.errors})
    try:
        result = ingest_dataframe(db, frame, dataset_type)
    except IngestionError as exc:
        raise HTTPException(400, detail={"message": "CSV ingestion failed; no rows were committed", "errors": [str(exc)]}) from exc
    return {"filename": file.filename, "columns": list(frame.columns), **result.__dict__}
