import numpy as np
import pandas as pd
import pytest

from scripts import evaluate_forecast


def test_evaluation_selects_on_validation_and_tests_on_separate_later_window(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=120)
    products = pd.DataFrame({"product_id": ["SKU-1"]})
    sales = pd.DataFrame({
        "product_id": ["SKU-1"] * len(dates),
        "date": dates,
        "quantity": [10.0] * 105 + [50.0] * 15,
    })
    observed_origins: list[tuple[str, pd.Timestamp, int]] = []

    def fake_candidate(name: str, history: pd.Series, horizon: int) -> np.ndarray:
        observed_origins.append((name, history.index[-1], len(history)))
        # Demand during the validation period is 10, so validation selects naive.
        # The final test period is 50, proving selection doesn't inspect test labels.
        prediction = {"naive baseline": 10.0, "damped-trend exponential smoothing": 20.0,
                      "Random Forest": 30.0}[name]
        return np.repeat(prediction, horizon)

    monkeypatch.setattr(evaluate_forecast, "_candidate_forecast", fake_candidate)
    result = evaluate_forecast.run_benchmark(
        products, sales, test_days=15, validation_days=20, min_train_days=39
    )

    row = result["sku_rows"][0]
    assert row["selected_model"] == "naive baseline"
    assert row["naive_baseline_mae"] == 40
    assert row["relative_wape_reduction_pct"] == 0
    assert all(origin < pd.Timestamp("2026-04-16") for _, origin, _ in observed_origins)
    assert result["metadata"]["sku_day_predictions"] == 15


def test_benchmark_uses_common_sku_days_and_counts_exclusions(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=100)
    products = pd.DataFrame({"product_id": ["eligible", "short"]})
    rows = [
        {"product_id": "eligible", "date": day, "quantity": 2}
        for day in dates
    ]
    rows.append({"product_id": "short", "date": dates[-2], "quantity": 1})

    result = evaluate_forecast.run_benchmark(
        products,
        pd.DataFrame(rows),
        test_days=10,
        validation_days=20,
        min_train_days=39,
    )

    assert result["metadata"]["eligible_skus"] == 1
    assert result["metadata"]["excluded_skus"] == 1
    assert result["metadata"]["sku_day_predictions"] == 10
    assert result["sku_rows"][1]["status"] == "excluded"


def test_aggregate_metrics_and_relative_reduction_handle_zero_actuals():
    metrics = evaluate_forecast._metrics(np.array([0.0, 0.0]), np.array([1.0, 1.0]))

    assert metrics["wape_pct"] is None
    assert metrics["mae"] == 1
    assert evaluate_forecast.relative_wape_reduction(0.0, 0.0) is None
    assert evaluate_forecast.relative_wape_reduction(50.0, 40.0) == 20


def test_benchmark_outputs_include_summary_and_per_sku_csv(tmp_path):
    dates = pd.date_range("2026-01-01", periods=100)
    products = pd.DataFrame({"product_id": ["SKU-1"]})
    sales = pd.DataFrame({
        "product_id": ["SKU-1"] * len(dates),
        "date": dates,
        "quantity": [4] * len(dates),
    })
    result = evaluate_forecast.run_benchmark(
        products, sales, test_days=10, validation_days=20, min_train_days=39
    )

    report_path, sku_path, summary_path = evaluate_forecast.write_outputs(
        result, tmp_path, tmp_path / "reports"
    )

    assert report_path.exists()
    assert "Untouched test results" in report_path.read_text(encoding="utf-8")
    assert pd.read_csv(sku_path).loc[0, "status"] == "evaluated"
    summary = pd.read_csv(summary_path)
    assert {"candidate_model", "selected_strategy", "selected_vs_naive"} <= set(summary.record_type)
