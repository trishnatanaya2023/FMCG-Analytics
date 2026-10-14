"""Backtest the forecast model selection against a naive baseline on a held-out window.

The final TEST_DAYS of sales are held out. For each SKU, forecast_daily() selects a model
using only data before that window, then forecasts it. Errors are pooled across all SKUs.

Usage: python -m scripts.evaluate_forecast
"""
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.data_loading import load_sample_data
from app.services.forecasting import build_product_demand_history, forecast_daily, get_product_ids

ROOT = Path(__file__).resolve().parents[1] / "data"
TEST_DAYS = 30
# forecast_daily selects its model on the last 20% of history, so 30 days leaves a 6-day selection window.
MIN_TRAIN_DAYS = 30


def naive_forecast(history: pd.Series, horizon: int) -> np.ndarray:
    # Mirrors the "naive" candidate in forecast_daily: repeat the last observed value.
    values = pd.Series(history, dtype=float).fillna(0).clip(lower=0)
    return np.repeat(values.iloc[-1], horizon)


def main() -> None:
    products, sales, *_ = load_sample_data(ROOT)
    last_date = pd.to_datetime(sales["date"]).max().normalize()
    test_start = last_date - pd.Timedelta(days=TEST_DAYS - 1)
    train_end = test_start - pd.Timedelta(days=1)
    test_dates = pd.date_range(test_start, last_date, freq="D")

    actual_all, selected_all, naive_all = [], [], []
    model_counts: Counter[str] = Counter()
    skipped = 0

    for product_id in get_product_ids(products):
        train = build_product_demand_history(sales, product_id, as_of=train_end)
        if train.empty:
            skipped += 1
            continue
        # Extend to the cutoff so forecasts start on test_start even if the SKU had no sale on train_end.
        train = train.reindex(pd.date_range(train.index[0], train_end, freq="D"), fill_value=0)
        if len(train) < MIN_TRAIN_DAYS:
            skipped += 1
            continue

        full = build_product_demand_history(sales, product_id)
        actual = full.reindex(test_dates, fill_value=0).to_numpy(dtype=float)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = forecast_daily(train, TEST_DAYS)
        assert result.dates[0] == test_start, f"{product_id}: forecast misaligned with test window"

        actual_all.append(actual)
        selected_all.append(np.asarray(result.values, dtype=float))
        naive_all.append(naive_forecast(train, TEST_DAYS))
        model_counts[result.model_name] += 1

    evaluated = len(actual_all)
    print(f"SKUs evaluated: {evaluated}")
    print(f"SKUs skipped (< {MIN_TRAIN_DAYS} days of history before test window): {skipped}")
    print(f"Training data:  up to {train_end.date()}")
    print(f"Test window:    {test_start.date()} to {last_date.date()} ({TEST_DAYS} days)")
    if not evaluated:
        print("Nothing to evaluate.")
        return

    actual = np.concatenate(actual_all)
    total_actual = actual.sum()
    rows = []
    for label, forecasts in (("Selected model", selected_all), ("Naive baseline", naive_all)):
        abs_err = np.abs(actual - np.concatenate(forecasts))
        wape = abs_err.sum() / total_actual * 100 if total_actual else float("nan")
        rows.append((label, wape, abs_err.mean()))

    print()
    print(f"{'Method':<16}{'WAPE':>10}{'MAE':>12}")
    for label, wape, mae in rows:
        print(f"{label:<16}{wape:>9.2f}%{mae:>12.3f}")

    (_, sel_wape, sel_mae), (_, naive_wape, naive_mae) = rows
    print()
    print("Improvement over naive (naive - selected) / naive x 100:")
    print(f"  WAPE: {(naive_wape - sel_wape) / naive_wape * 100:+.2f}%" if naive_wape else "  WAPE: n/a")
    print(f"  MAE:  {(naive_mae - sel_mae) / naive_mae * 100:+.2f}%" if naive_mae else "  MAE:  n/a")

    print()
    print("Model selection frequency:")
    for name, count in model_counts.most_common():
        print(f"  {name:<24}{count:>4}  ({count / evaluated * 100:.1f}%)")


if __name__ == "__main__":
    main()
