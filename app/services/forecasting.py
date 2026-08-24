from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from statsmodels.tsa.holtwinters import ExponentialSmoothing


def build_product_demand_history(sales: pd.DataFrame, product_id: str, as_of=None) -> pd.Series:
    data = sales.copy()
    data["date"] = pd.to_datetime(data["date"])
    history = data[data.product_id == product_id].groupby("date").quantity.sum()
    if as_of is not None and not history.empty:
        history = history[history.index <= pd.Timestamp(as_of)]
    if history.empty:
        return pd.Series(dtype=float)
    return history.asfreq("D", fill_value=0)


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


def calculate_accuracy_metrics(actual: list[float] | np.ndarray, predicted: list[float] | np.ndarray) -> dict[str, float]:
    actual_values = np.asarray(actual, dtype=float)
    predicted_values = np.asarray(predicted, dtype=float)
    if actual_values.shape != predicted_values.shape or actual_values.size == 0:
        raise ValueError("actual and predicted must be non-empty arrays with the same shape")
    mask = actual_values != 0
    mape = float(np.mean(np.abs((actual_values[mask] - predicted_values[mask]) / actual_values[mask])) * 100) if mask.any() else 0.0
    return {
        "mae": float(mean_absolute_error(actual_values, predicted_values)),
        "rmse": float(mean_squared_error(actual_values, predicted_values) ** 0.5),
        "mape": mape,
    }


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    mask = actual != 0
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100) if mask.any() else 0.0


def forecast_daily(history: pd.Series, horizon: int = 30) -> ForecastResult:
    values = pd.Series(history, dtype=float).fillna(0).clip(lower=0)
    values.index = pd.to_datetime(values.index)
    if values.empty:
        future = np.zeros(horizon)
        model_name = "zero-demand fallback"
        mae = rmse = mape = None
    else:
        split = max(1, int(len(values) * 0.8))
        train, test = values.iloc[:split], values.iloc[split:]
        candidates: list[tuple[str, np.ndarray, np.ndarray]] = []
        naive = np.repeat(train.iloc[-1], len(test))
        candidates.append(("naive", naive, np.repeat(values.iloc[-1], horizon)))
        window = min(7, len(train))
        moving = np.repeat(train.iloc[-window:].mean(), len(test))
        candidates.append(("7-day moving average", moving, np.repeat(train.iloc[-window:].mean(), horizon)))
        try:
            fitted = ExponentialSmoothing(train, trend="add", damped_trend=True,
                                           initialization_method="estimated").fit(optimized=True)
            candidates.append(("exponential smoothing", fitted.forecast(len(test)).to_numpy(),
                               fitted.forecast(horizon).to_numpy()))
        except (ValueError, np.linalg.LinAlgError):
            pass
        actual = test.to_numpy()
        scored = [(mean_absolute_error(actual, pred), name, pred, future) for name, pred, future in candidates]
        score, model_name, _, future = min(scored, key=lambda item: item[0]) if len(test) else (0, candidates[-1][0], [], candidates[-1][2])
        if len(test):
            selected = next(item for item in candidates if item[0] == model_name)
            metrics = calculate_accuracy_metrics(actual, selected[1])
            mae, rmse, mape = metrics["mae"], metrics["rmse"], metrics["mape"]
        else:
            mae = rmse = mape = None
        future = np.maximum(0, np.asarray(future, dtype=float))
    last_date = values.index[-1] if not values.empty else pd.Timestamp.today().normalize()
    dates = list(pd.date_range(last_date + pd.Timedelta(days=1), periods=horizon, freq="D"))
    spread = max(1.0, float(np.std(values.to_numpy())) if len(values) > 1 else float(future.mean() * 0.2))
    return ForecastResult(dates, future.tolist(), np.maximum(0, future - 1.96 * spread).tolist(),
                          (future + 1.96 * spread).tolist(), model_name, mae, rmse, mape)


def forecast_product_from_csv(root, product_id: str, horizon: int = 30) -> "ForecastResult":
    sales = pd.read_csv(root / "sales.csv")
    history = build_product_demand_history(sales, product_id)
    if history.empty:
        raise ValueError("Product not found or has no sales")
    return forecast_daily(history, normalize_forecast_horizon(horizon))
