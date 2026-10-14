import numpy as np
import pandas as pd
import pytest

from app.services import forecasting
from app.services.forecasting import (
    _exponential_smoothing_forecast,
    _features,
    _random_forest_forecast,
    _random_forest_training_data,
    calculate_accuracy_metrics,
    forecast_daily,
)


def test_naive_baseline_handles_single_observation():
    history = pd.Series([4.0], index=pd.date_range("2026-01-01", periods=1))
    result = forecast_daily(history, 3)

    assert result.model_name == "naive baseline"
    assert result.values == [4.0, 4.0, 4.0]
    assert result.aggregate_demand == 12.0
    assert result.mae is None


def test_exponential_smoothing_produces_finite_non_negative_predictions():
    history = pd.Series(np.linspace(2, 20, 40), index=pd.date_range("2026-01-01", periods=40))

    predictions = _exponential_smoothing_forecast(history, 5)

    assert predictions.shape == (5,)
    assert np.isfinite(predictions).all()
    assert (predictions >= 0).all()


def test_random_forest_trains_and_recursively_forecasts():
    history = pd.Series(
        [5 + day % 7 + day // 10 for day in range(70)],
        index=pd.date_range("2026-01-01", periods=70),
    )

    first = _random_forest_forecast(history, 7)
    second = _random_forest_forecast(history, 7)

    assert first.shape == (7,)
    assert np.isfinite(first).all()
    assert (first >= 0).all()
    assert np.array_equal(first, second)


def test_random_forest_rejects_insufficient_supervised_training_rows():
    history = pd.Series(np.arange(18, dtype=float), index=pd.date_range("2026-01-01", periods=18))

    with pytest.raises(ValueError, match="insufficient"):
        _random_forest_forecast(history, 3)


def test_random_forest_features_use_only_prior_demand():
    history = pd.Series(np.arange(40, dtype=float), index=pd.date_range("2026-01-01", periods=40))
    features, targets = _random_forest_training_data(history)

    # The first target (day 14) uses demand only through day 13.
    assert targets[0] == 14
    assert features[0, 0] == 13
    assert features[0, 1] == 7
    assert features[0, 2] == 0
    assert features[0, 3] == 10
    assert features[0, 4] == np.mean(np.arange(14))
    assert features[0, 6] == history.index[14].dayofweek
    assert _features(np.arange(14, dtype=float), history.index[14])[0] == 13


def test_holdout_forecasting_uses_training_period_only(monkeypatch):
    history = pd.Series(np.arange(50, dtype=float), index=pd.date_range("2026-01-01", periods=50))
    seen: list[tuple[pd.Timestamp, int]] = []

    def fake_forest(train: pd.Series, horizon: int) -> np.ndarray:
        seen.append((train.index[-1], len(train)))
        return np.repeat(float(train.iloc[-1]), horizon)

    monkeypatch.setattr(forecasting, "_random_forest_forecast", fake_forest)
    forecast_daily(history, 4)

    assert seen[0] == (history.index[39], 40)


def test_lowest_holdout_mae_selects_baseline_for_constant_series():
    history = pd.Series([8.0] * 50, index=pd.date_range("2026-01-01", periods=50))

    result = forecast_daily(history, 7)

    assert result.model_name == "naive baseline"
    assert result.mae == 0
    assert result.rmse == 0
    assert result.mape == 0
    assert result.interval_available


def test_mape_is_not_reported_for_holdout_with_zero_actuals():
    metrics = calculate_accuracy_metrics([0, 10], [1, 9])

    assert metrics["mae"] == 1
    assert metrics["mape"] is None


def test_empty_history_has_finite_zero_fallback():
    result = forecast_daily(pd.Series(dtype=float), 7)

    assert result.model_name == "zero-demand fallback"
    assert result.values == [0.0] * 7
    assert result.aggregate_demand == 0
    assert not result.interval_available


def test_forecast_normalizes_negative_and_missing_demand():
    history = pd.Series(
        [3.0, np.nan, -2.0],
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
    )

    result = forecast_daily(history, 2)

    assert np.isfinite(result.values).all()
    assert all(value >= 0 for value in result.values)


def test_as_of_history_fills_unobserved_days_through_forecast_origin():
    sales = pd.DataFrame({
        "date": ["2026-01-01"],
        "product_id": ["SKU-1"],
        "quantity": [5],
    })

    history = forecasting.build_product_demand_history(sales, "SKU-1", "2026-01-04")

    assert history.tolist() == [5.0, 0.0, 0.0, 0.0]
    assert history.index[-1] == pd.Timestamp("2026-01-04")


def test_sku_history_extends_to_shared_dataset_date_when_sku_had_no_sale():
    sales = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-05"],
        "product_id": ["SKU-1", "SKU-2"],
        "quantity": [5, 3],
    })

    history = forecasting.build_product_demand_history(sales, "SKU-1", sales.date.max())

    assert history.tolist() == [5.0, 0.0, 0.0, 0.0, 0.0]


def test_forecast_api_adds_metrics_and_horizon_without_changing_daily_shape(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import main as api_main
    from app.services.auth import get_current_user

    pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=50).strftime("%Y-%m-%d"),
        "product_id": ["SKU-1"] * 50,
        "quantity": [5] * 50,
    }).to_csv(tmp_path / "sales.csv", index=False)
    monkeypatch.setattr(api_main, "ROOT", tmp_path)
    api_main.app.dependency_overrides[get_current_user] = lambda: None
    try:
        response = TestClient(api_main.app).get("/forecast/SKU-1?horizon=7")
    finally:
        api_main.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "SKU-1"
    assert payload["horizon"] == 7
    assert payload["aggregate_demand"] == sum(row["units"] for row in payload["forecast"])
    assert {"model", "mae", "rmse", "mape", "forecast"} <= payload.keys()
    assert len(payload["forecast"]) == 7
    assert {"date", "units", "lower", "upper"} <= payload["forecast"][0].keys()
