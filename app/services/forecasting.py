from dataclasses import dataclass
from functools import lru_cache
import logging
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from statsmodels.tsa.holtwinters import ExponentialSmoothing

logger = logging.getLogger(__name__)
_FEATURE_NAMES = ("lag_1", "lag_7", "lag_14", "mean_7", "mean_28", "std_28", "weekday")


def build_product_demand_history(sales: pd.DataFrame, product_id: str | int, as_of=None) -> pd.Series:
    data = sales.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    history = data[data.product_id.astype(str) == str(product_id)].groupby("date").quantity.sum()
    if as_of is not None and not history.empty:
        cutoff = pd.Timestamp(as_of).normalize()
        history = history[history.index <= cutoff]
    if history.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], name="date"))
    if as_of is not None:
        return history.reindex(pd.date_range(history.index.min(), cutoff, freq="D", name="date"),
                               fill_value=0).astype(float)
    return history.asfreq("D", fill_value=0).astype(float)


def latest_daily_demand(sales: pd.DataFrame, days: int = 30) -> pd.Series:
    data = sales.copy()
    data["date"] = pd.to_datetime(data["date"])
    if data.empty:
        return pd.Series(dtype=float)
    cutoff = data.date.max() - pd.Timedelta(days=days)
    return data[data.date >= cutoff].groupby("product_id").quantity.sum().div(days)


def normalize_forecast_horizon(horizon: int) -> int:
    return min(max(int(horizon), 1), 60)


def get_product_ids(products: pd.DataFrame) -> list[int]:
    return products.product_id.tolist()


def get_forecast_horizon_options() -> list[int]:
    return [7, 14, 30, 60]


@dataclass(frozen=True)
class ForecastResult:
    dates: list[pd.Timestamp]
    values: list[float]
    lower: list[float]
    upper: list[float]
    model_name: str
    mae: float | None
    rmse: float | None
    mape: float | None
    horizon: int
    aggregate_demand: float
    interval_available: bool
    uncertainty_basis: str | None


def calculate_accuracy_metrics(
    actual: list[float] | np.ndarray, predicted: list[float] | np.ndarray
) -> dict[str, float | None]:
    actual_values = np.asarray(actual, dtype=float)
    predicted_values = np.asarray(predicted, dtype=float)
    if actual_values.shape != predicted_values.shape or actual_values.size == 0:
        raise ValueError("actual and predicted must be non-empty arrays with the same shape")
    if not np.isfinite(actual_values).all() or not np.isfinite(predicted_values).all():
        raise ValueError("actual and predicted must contain only finite values")
    has_zero_actual = bool((actual_values == 0).any())
    mask = actual_values != 0
    mape = (
        float(np.mean(np.abs((actual_values[mask] - predicted_values[mask]) / actual_values[mask])) * 100)
        if mask.any() and not has_zero_actual else None
    )
    return {
        "mae": float(mean_absolute_error(actual_values, predicted_values)),
        "rmse": float(mean_squared_error(actual_values, predicted_values) ** 0.5),
        "mape": mape,
    }


def _features(history: np.ndarray, target_date: pd.Timestamp) -> list[float]:
    recent = history[-28:]
    return [
        float(history[-1]),
        float(history[-7]) if len(history) >= 7 else 0.0,
        float(history[-14]) if len(history) >= 14 else 0.0,
        float(np.mean(history[-7:])),
        float(np.mean(recent)),
        float(np.std(recent, ddof=1)) if len(recent) > 1 else 0.0,
        float(target_date.dayofweek),
    ]


def _random_forest_training_data(history: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    values = history.to_numpy(dtype=float)
    features = [
        _features(values[:target_index], history.index[target_index])
        for target_index in range(14, len(values))
    ]
    targets = values[14:]
    if not features:
        return np.empty((0, len(_FEATURE_NAMES))), np.empty(0)
    return np.asarray(features, dtype=float), targets


def _random_forest_forecast(history: pd.Series, horizon: int) -> np.ndarray:
    features, targets = _random_forest_training_data(history)
    if len(targets) < 5:
        raise ValueError("insufficient feature history to train Random Forest")
    model = RandomForestRegressor(
        n_estimators=200,
        min_samples_leaf=2,
        max_features=0.8,
        random_state=42,
        n_jobs=1,
    )
    model.fit(features, targets)
    observed = history.to_numpy(dtype=float).tolist()
    predictions: list[float] = []
    next_date = history.index[-1] + pd.Timedelta(days=1)
    for offset in range(horizon):
        target_date = next_date + pd.Timedelta(days=offset)
        row = np.asarray(_features(np.asarray(observed, dtype=float), target_date), dtype=float).reshape(1, -1)
        prediction = float(model.predict(row)[0])
        if not math.isfinite(prediction):
            raise ValueError("Random Forest generated a non-finite prediction")
        prediction = max(0.0, prediction)
        predictions.append(prediction)
        observed.append(prediction)
    return np.asarray(predictions, dtype=float)


def _exponential_smoothing_forecast(history: pd.Series, horizon: int) -> np.ndarray:
    if len(history) < 3:
        raise ValueError("insufficient history for trend exponential smoothing")
    fitted = ExponentialSmoothing(
        history,
        trend="add",
        damped_trend=True,
        initialization_method="estimated",
    ).fit(optimized=True)
    predictions = np.asarray(fitted.forecast(horizon), dtype=float)
    if not np.isfinite(predictions).all():
        raise ValueError("exponential smoothing generated non-finite predictions")
    return np.maximum(0.0, predictions)


def _prepare_history(history: pd.Series) -> pd.Series:
    values = pd.Series(history, dtype=float).copy()
    if values.empty:
        return values
    values.index = pd.to_datetime(values.index).normalize()
    values = values.groupby(level=0).sum().sort_index()
    values = values.asfreq("D", fill_value=0).fillna(0).clip(lower=0)
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("demand history must contain only finite values")
    return values


def _forecast_daily_uncached(history_values: tuple[tuple[str, float], ...], horizon: int) -> ForecastResult:
    values = pd.Series(
        [value for _, value in history_values],
        index=pd.to_datetime([day for day, _ in history_values]),
        dtype=float,
    )
    if values.empty:
        predictions = np.zeros(horizon, dtype=float)
        model_name = "zero-demand fallback"
        mae = rmse = mape = None
        interval_available = False
        uncertainty_basis = None
    else:
        split = max(1, int(len(values) * 0.8))
        train, test = values.iloc[:split], values.iloc[split:]
        candidates: list[tuple[str, np.ndarray]] = [
            ("naive baseline", np.repeat(float(train.iloc[-1]), len(test)))
        ]
        if len(test):
            try:
                candidates.append(("damped-trend exponential smoothing",
                                   _exponential_smoothing_forecast(train, len(test))))
            except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
                logger.info("Exponential smoothing unavailable for holdout: %s", exc)
            try:
                candidates.append(("Random Forest", _random_forest_forecast(train, len(test))))
            except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
                logger.info("Random Forest unavailable for holdout: %s", exc)

        actual = test.to_numpy(dtype=float)
        if len(test):
            scored: list[tuple[float, str, np.ndarray]] = []
            for name, predicted in candidates:
                predicted = np.asarray(predicted, dtype=float)
                if predicted.shape != actual.shape or not np.isfinite(predicted).all():
                    logger.warning("Ignoring invalid %s holdout predictions", name)
                    continue
                predicted = np.maximum(0.0, predicted)
                scored.append((float(mean_absolute_error(actual, predicted)), name, predicted))
            if not scored:
                raise RuntimeError("No forecasting model produced valid holdout predictions")
            scored.sort(key=lambda item: item[0])
            holdout_by_name = {name: predicted for _, name, predicted in scored}
        else:
            model_name = "naive baseline"
            mae = rmse = mape = None
            holdout_by_name = {}
            interval_available = False
            uncertainty_basis = None

        predictors = {
            "naive baseline": lambda series, steps: np.repeat(float(series.iloc[-1]), steps),
            "damped-trend exponential smoothing": _exponential_smoothing_forecast,
            "Random Forest": _random_forest_forecast,
        }
        predictions = None
        refit_order = [name for _, name, _ in scored] if len(test) else ["naive baseline"]
        for candidate_name in refit_order:
            try:
                candidate_predictions = np.asarray(predictors[candidate_name](values, horizon), dtype=float)
            except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
                logger.info("Selected %s could not refit on full history: %s", candidate_name, exc)
                continue
            if candidate_predictions.shape == (horizon,) and np.isfinite(candidate_predictions).all():
                model_name = candidate_name
                predictions = np.maximum(0.0, candidate_predictions)
                break
        if predictions is None:
            predictions = np.repeat(float(values.iloc[-1]), horizon)
            model_name = "naive baseline"
        if len(test):
            metrics = calculate_accuracy_metrics(actual, holdout_by_name[model_name])
            mae, rmse, mape = metrics["mae"], metrics["rmse"], metrics["mape"]
            residual_quantile = float(np.quantile(np.abs(actual - holdout_by_name[model_name]), 0.95))
            interval_available = True
            uncertainty_basis = "95th-percentile absolute chronological holdout error; indicative, not calibrated"

    last_date = values.index[-1] if not values.empty else pd.Timestamp.today().normalize()
    dates = list(pd.date_range(last_date + pd.Timedelta(days=1), periods=horizon, freq="D"))
    if interval_available:
        lower = np.maximum(0.0, predictions - residual_quantile)
        upper = predictions + residual_quantile
    else:
        lower = predictions.copy()
        upper = predictions.copy()
    return ForecastResult(
        dates=dates,
        values=predictions.tolist(),
        lower=lower.tolist(),
        upper=upper.tolist(),
        model_name=model_name,
        mae=mae,
        rmse=rmse,
        mape=mape,
        horizon=horizon,
        aggregate_demand=float(predictions.sum()),
        interval_available=interval_available,
        uncertainty_basis=uncertainty_basis,
    )


@lru_cache(maxsize=512)
def _cached_forecast(history_values: tuple[tuple[str, float], ...], horizon: int) -> ForecastResult:
    return _forecast_daily_uncached(history_values, horizon)


def forecast_daily(history: pd.Series, horizon: int = 30) -> ForecastResult:
    horizon = int(horizon)
    if horizon < 1:
        raise ValueError("horizon must be at least one day")
    values = _prepare_history(history)
    cache_key = tuple((day.isoformat(), float(value)) for day, value in values.items())
    result = _cached_forecast(cache_key, horizon)
    return ForecastResult(
        dates=list(result.dates),
        values=list(result.values),
        lower=list(result.lower),
        upper=list(result.upper),
        model_name=result.model_name,
        mae=result.mae,
        rmse=result.rmse,
        mape=result.mape,
        horizon=result.horizon,
        aggregate_demand=result.aggregate_demand,
        interval_available=result.interval_available,
        uncertainty_basis=result.uncertainty_basis,
    )


def forecast_product_from_csv(root, product_id: str, horizon: int = 30) -> ForecastResult:
    sales = pd.read_csv(root / "sales.csv")
    as_of = pd.to_datetime(sales["date"]).max().normalize() if not sales.empty else None
    history = build_product_demand_history(sales, product_id, as_of)
    if history.empty:
        raise ValueError("Product not found or has no sales")
    return forecast_daily(history, normalize_forecast_horizon(horizon))
