"""Benchmark per-SKU forecasting on an untouched chronological test window.

Models are selected independently for each SKU using a preceding validation window.
All candidate and selected-strategy test metrics use exactly the same eligible SKUs.

Usage: python -m scripts.evaluate_forecast
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.data_loading import load_sample_data
from app.services.forecasting import (
    _exponential_smoothing_forecast,
    _random_forest_forecast,
    build_product_demand_history,
    get_product_ids,
)

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1] / "data"
REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
DEFAULT_TEST_DAYS = 30
DEFAULT_VALIDATION_DAYS = 30
DEFAULT_MIN_TRAIN_DAYS = 60
MODEL_NAMES = (
    "naive baseline",
    "damped-trend exponential smoothing",
    "Random Forest",
)


def _naive_forecast(history: pd.Series, horizon: int) -> np.ndarray:
    return np.repeat(float(history.iloc[-1]), horizon)


def _candidate_forecast(name: str, history: pd.Series, horizon: int) -> np.ndarray:
    functions: dict[str, Callable[[pd.Series, int], np.ndarray]] = {
        "naive baseline": _naive_forecast,
        "damped-trend exponential smoothing": _exponential_smoothing_forecast,
        "Random Forest": _random_forest_forecast,
    }
    prediction = np.asarray(functions[name](history, horizon), dtype=float)
    if prediction.shape != (horizon,):
        raise ValueError(f"{name} returned {prediction.size} values; expected {horizon}")
    if not np.isfinite(prediction).all():
        raise ValueError(f"{name} returned non-finite predictions")
    if (prediction < 0).any():
        raise ValueError(f"{name} returned negative predictions")
    return prediction


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    errors = np.asarray(actual, dtype=float) - np.asarray(predicted, dtype=float)
    absolute_errors = np.abs(errors)
    total_actual = float(np.abs(actual).sum())
    return {
        "wape_pct": float(absolute_errors.sum() / total_actual * 100) if total_actual else None,
        "mae": float(absolute_errors.mean()) if absolute_errors.size else None,
        "rmse": float(np.sqrt(np.mean(np.square(errors)))) if errors.size else None,
        "actual_units": float(total_actual),
        "absolute_error_units": float(absolute_errors.sum()),
    }


def relative_wape_reduction(naive_wape: float | None, selected_wape: float | None) -> float | None:
    if naive_wape is None or selected_wape is None or naive_wape == 0:
        return None
    return (naive_wape - selected_wape) / naive_wape * 100


def _error_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def run_benchmark(
    products: pd.DataFrame,
    sales: pd.DataFrame,
    test_days: int = DEFAULT_TEST_DAYS,
    validation_days: int = DEFAULT_VALIDATION_DAYS,
    min_train_days: int = DEFAULT_MIN_TRAIN_DAYS,
) -> dict:
    if test_days < 1 or validation_days < 1 or min_train_days < validation_days + 19:
        raise ValueError("Use positive horizons and min_train_days >= validation_days + 19")
    if products.empty or sales.empty:
        raise ValueError("The product and sales datasets must both be non-empty")
    if not {"product_id"}.issubset(products.columns):
        raise ValueError("products data must include product_id")
    if not {"product_id", "date", "quantity"}.issubset(sales.columns):
        raise ValueError("sales data must include product_id, date, and quantity")

    normalized_sales = sales[["product_id", "date", "quantity"]].copy()
    normalized_sales["date"] = pd.to_datetime(normalized_sales["date"]).dt.normalize()
    normalized_sales["quantity"] = pd.to_numeric(normalized_sales["quantity"], errors="raise")
    if normalized_sales.empty or normalized_sales["date"].isna().any():
        raise ValueError("sales data must contain valid dates")
    if not np.isfinite(normalized_sales["quantity"].to_numpy(dtype=float)).all():
        raise ValueError("sales quantities must be finite")

    last_date = normalized_sales["date"].max()
    first_date = normalized_sales["date"].min()
    test_start = last_date - pd.Timedelta(days=test_days - 1)
    test_end = last_date
    test_train_end = test_start - pd.Timedelta(days=1)
    validation_start = test_start - pd.Timedelta(days=validation_days)
    validation_end = test_start - pd.Timedelta(days=1)
    selection_train_end = validation_start - pd.Timedelta(days=1)
    test_dates = pd.date_range(test_start, test_end, freq="D")
    validation_dates = pd.date_range(validation_start, validation_end, freq="D")

    sku_rows: list[dict] = []
    eligible: list[dict] = []
    exclusion_counts: Counter[str] = Counter()
    ordered_product_ids = get_product_ids(products)
    for product_id in ordered_product_ids:
        sku = str(product_id)
        product_sales = normalized_sales[normalized_sales["product_id"].astype(str) == sku]
        first_sale = product_sales["date"].min() if not product_sales.empty else pd.NaT
        base_row = {
            "product_id": sku,
            "first_sale_date": first_sale.date().isoformat() if pd.notna(first_sale) else None,
            "status": "excluded",
            "exclusion_reason": None,
            "selected_model": None,
            "validation_selected_mae": None,
            "test_days": test_days,
        }

        if product_sales.empty or first_sale >= test_start:
            reason = "no sales before test window"
            sku_rows.append({**base_row, "exclusion_reason": reason})
            exclusion_counts[reason] += 1
            continue

        history = build_product_demand_history(normalized_sales, product_id, as_of=test_train_end)
        if history.empty or len(history) < min_train_days:
            reason = f"insufficient pre-test history (< {min_train_days} days)"
            sku_rows.append({**base_row, "exclusion_reason": reason})
            exclusion_counts[reason] += 1
            continue

        validation_history = build_product_demand_history(
            normalized_sales, product_id, as_of=selection_train_end
        )
        if validation_history.empty:
            reason = "insufficient history before validation window"
            sku_rows.append({**base_row, "exclusion_reason": reason})
            exclusion_counts[reason] += 1
            continue

        actual_validation = (
            product_sales.set_index("date")["quantity"].groupby(level=0).sum()
            .reindex(validation_dates, fill_value=0).to_numpy(dtype=float)
        )
        actual_test = (
            product_sales.set_index("date")["quantity"].groupby(level=0).sum()
            .reindex(test_dates, fill_value=0).to_numpy(dtype=float)
        )

        validation_predictions: dict[str, np.ndarray] = {}
        test_predictions: dict[str, np.ndarray] = {}
        model_errors: list[str] = []
        for name in MODEL_NAMES:
            try:
                validation_predictions[name] = _candidate_forecast(
                    name, validation_history, validation_days
                )
            except Exception as exc:
                detail = f"{name} validation: {_error_text(exc)}"
                LOGGER.warning("SKU %s excluded: %s", sku, detail)
                model_errors.append(detail)
                continue
            try:
                test_predictions[name] = _candidate_forecast(name, history, test_days)
            except Exception as exc:
                detail = f"{name} test: {_error_text(exc)}"
                LOGGER.warning("SKU %s excluded: %s", sku, detail)
                model_errors.append(detail)

        if model_errors:
            reason = "; ".join(model_errors)
            sku_rows.append({**base_row, "exclusion_reason": reason})
            exclusion_counts["invalid model predictions or fit failures"] += 1
            continue

        validation_scores = {
            name: float(np.mean(np.abs(actual_validation - prediction)))
            for name, prediction in validation_predictions.items()
        }
        # MODEL_NAMES order is the documented deterministic tie-break order.
        selected_model = min(MODEL_NAMES, key=lambda name: validation_scores[name])
        candidate_metrics = {
            name: _metrics(actual_test, test_predictions[name]) for name in MODEL_NAMES
        }
        selected_predictions = test_predictions[selected_model]
        row = {
            **base_row,
            "status": "evaluated",
            "selected_model": selected_model,
            "validation_selected_mae": validation_scores[selected_model],
            "test_actual_units": float(actual_test.sum()),
            "test_sku_days": int(actual_test.size),
            "test_winner": min(
                MODEL_NAMES,
                key=lambda name: candidate_metrics[name]["mae"]
                if candidate_metrics[name]["mae"] is not None else float("inf"),
            ),
            "selected_test_wape_pct": _metrics(actual_test, selected_predictions)["wape_pct"],
            "selected_test_mae": _metrics(actual_test, selected_predictions)["mae"],
            "selected_test_rmse": _metrics(actual_test, selected_predictions)["rmse"],
            "naive_test_wape_pct": candidate_metrics["naive baseline"]["wape_pct"],
            "naive_test_mae": candidate_metrics["naive baseline"]["mae"],
            "naive_test_rmse": candidate_metrics["naive baseline"]["rmse"],
            "relative_wape_reduction_pct": relative_wape_reduction(
                candidate_metrics["naive baseline"]["wape_pct"],
                _metrics(actual_test, selected_predictions)["wape_pct"],
            ),
        }
        for name, metrics in candidate_metrics.items():
            key = name.lower().replace(" ", "_").replace("-", "_")
            for metric_name in ("wape_pct", "mae", "rmse"):
                row[f"{key}_{metric_name}"] = metrics[metric_name]
            row[f"{key}_validation_mae"] = validation_scores[name]
        sku_rows.append(row)
        eligible.append({
            "product_id": sku,
            "actual": actual_test,
            "predictions": test_predictions,
            "selected_model": selected_model,
            "selected_predictions": selected_predictions,
        })

    if not eligible:
        raise ValueError("No SKUs had sufficient history and valid predictions for all three models")

    actual_all = np.concatenate([record["actual"] for record in eligible])
    candidate_aggregate: dict[str, dict[str, float | None]] = {
        name: _metrics(actual_all, np.concatenate([
            record["predictions"][name] for record in eligible
        ]))
        for name in MODEL_NAMES
    }
    selected_aggregate = _metrics(actual_all, np.concatenate([
        record["selected_predictions"] for record in eligible
    ]))
    selected_counts = Counter(record["selected_model"] for record in eligible)
    test_wins = Counter()
    for record in eligible:
        scores = {
            name: float(np.mean(np.abs(record["actual"] - record["predictions"][name])))
            for name in MODEL_NAMES
        }
        # Ties are awarded once, using the same stable model ordering as selection.
        test_wins[min(MODEL_NAMES, key=lambda name: scores[name])] += 1

    summary_rows: list[dict] = []
    for name in MODEL_NAMES:
        summary_rows.append({
            "record_type": "candidate_model",
            "model": name,
            **candidate_aggregate[name],
            "selected_for_skus": selected_counts[name],
            "test_wins": test_wins[name],
            "test_win_pct": test_wins[name] / len(eligible) * 100,
        })
    summary_rows.append({
        "record_type": "selected_strategy",
        "model": "validation-selected per-SKU strategy",
        **selected_aggregate,
        "selected_for_skus": len(eligible),
        "test_wins": None,
        "test_win_pct": None,
    })
    summary_rows.append({
        "record_type": "selected_vs_naive",
        "model": "selected strategy vs naive baseline",
        "relative_wape_reduction_pct": relative_wape_reduction(
            candidate_aggregate["naive baseline"]["wape_pct"],
            selected_aggregate["wape_pct"],
        ),
        "mae_delta_vs_naive": (
            candidate_aggregate["naive baseline"]["mae"] - selected_aggregate["mae"]
            if candidate_aggregate["naive baseline"]["mae"] is not None
            and selected_aggregate["mae"] is not None else None
        ),
        "rmse_delta_vs_naive": (
            candidate_aggregate["naive baseline"]["rmse"] - selected_aggregate["rmse"]
            if candidate_aggregate["naive baseline"]["rmse"] is not None
            and selected_aggregate["rmse"] is not None else None
        ),
        "actual_units": float(np.abs(actual_all).sum()),
        "absolute_error_units": None,
        "selected_for_skus": None,
        "test_wins": None,
        "test_win_pct": None,
    })

    return {
        "metadata": {
            "dataset_first_sale_date": first_date.date().isoformat(),
            "dataset_last_sale_date": last_date.date().isoformat(),
            "dataset_sku_count": len(ordered_product_ids),
            "sales_record_count": int(len(normalized_sales)),
            "test_start": test_start.date().isoformat(),
            "test_end": test_end.date().isoformat(),
            "test_days": test_days,
            "validation_start": validation_start.date().isoformat(),
            "validation_end": validation_end.date().isoformat(),
            "validation_days": validation_days,
            "selection_training_end": selection_train_end.date().isoformat(),
            "test_training_end": test_train_end.date().isoformat(),
            "min_pre_test_history_days": min_train_days,
            "eligible_skus": len(eligible),
            "excluded_skus": len(ordered_product_ids) - len(eligible),
            "sku_day_predictions": int(len(eligible) * test_days),
            "zero_actual_test_days": int((actual_all == 0).sum()),
            "total_test_actual_units": float(np.abs(actual_all).sum()),
            "zero_total_actual_demand": bool(np.abs(actual_all).sum() == 0),
            "exclusion_counts": dict(exclusion_counts),
            "selection_method": "Lowest validation-window MAE per SKU; deterministic ties follow candidate order.",
            "recursive_method": (
                "The Random Forest predicts each future day, appends that prediction to observed history, "
                "then rebuilds lag and rolling features for the next day. Actual validation/test demand "
                "is never included in recursive prediction inputs."
            ),
            "metrics_method": (
                "Aggregate WAPE = sum(abs(actual - predicted)) / sum(abs(actual)) * 100; "
                "MAE and RMSE pool all SKU-day errors. All candidates and the selected strategy share "
                "the same eligible SKU-day test observations."
            ),
        },
        "candidate_aggregate": candidate_aggregate,
        "selected_aggregate": selected_aggregate,
        "selected_counts": dict(selected_counts),
        "test_wins": dict(test_wins),
        "selected_vs_naive_wape_reduction_pct": relative_wape_reduction(
            candidate_aggregate["naive baseline"]["wape_pct"],
            selected_aggregate["wape_pct"],
        ),
        "sku_rows": sku_rows,
        "summary_rows": summary_rows,
        "eligible_sku_ids": [record["product_id"] for record in eligible],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_outputs(result: dict, data_root: Path, output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "forecast-performance.md"
    sku_csv_path = output_dir / "forecast-performance-per-sku.csv"
    summary_csv_path = output_dir / "forecast-performance-summary.csv"
    sku_frame = pd.DataFrame(result["sku_rows"])
    summary_frame = pd.DataFrame(result["summary_rows"])
    metadata = result["metadata"]
    csv_metadata = {
        "test_start": metadata["test_start"],
        "test_end": metadata["test_end"],
        "validation_start": metadata["validation_start"],
        "validation_end": metadata["validation_end"],
        "dataset_first_sale_date": metadata["dataset_first_sale_date"],
        "dataset_last_sale_date": metadata["dataset_last_sale_date"],
        "test_days": metadata["test_days"],
        "validation_days": metadata["validation_days"],
        "min_pre_test_history_days": metadata["min_pre_test_history_days"],
        "eligible_skus": metadata["eligible_skus"],
        "excluded_skus": metadata["excluded_skus"],
        "sku_day_predictions": metadata["sku_day_predictions"],
        "dataset_sales_records": metadata["sales_record_count"],
    }
    for frame in (sku_frame, summary_frame):
        for column, value in csv_metadata.items():
            if column in frame.columns:
                frame[column] = value
            else:
                frame.insert(0, column, value)
    sku_frame.to_csv(sku_csv_path, index=False)
    summary_frame.to_csv(summary_csv_path, index=False)

    candidate = result["candidate_aggregate"]
    selected = result["selected_aggregate"]
    naive = candidate["naive baseline"]
    reduction = result["selected_vs_naive_wape_reduction_pct"]
    data_files = [data_root / "products.csv", data_root / "sales.csv"]
    file_fingerprints = {
        path.name: _sha256(path) for path in data_files if path.exists()
    }
    summary_table = [
        "| Model/strategy | WAPE (%) | MAE | RMSE | Selected SKUs | Test wins | Win share (%) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in MODEL_NAMES:
        metrics = candidate[name]
        count = result["selected_counts"].get(name, 0)
        wins = result["test_wins"].get(name, 0)
        summary_table.append(
            f"| {name} | {_fmt(metrics['wape_pct'])} | {_fmt(metrics['mae'])} | "
            f"{_fmt(metrics['rmse'])} | {count} | {wins} | "
            f"{_fmt(wins / metadata['eligible_skus'] * 100)} |"
        )
    summary_table.append(
        f"| Validation-selected per-SKU strategy | {_fmt(selected['wape_pct'])} | "
        f"{_fmt(selected['mae'])} | {_fmt(selected['rmse'])} | "
        f"{metadata['eligible_skus']} | — | — |"
    )
    actual_total = metadata["total_test_actual_units"]
    actual_note = (
        f"{metadata['zero_actual_test_days']} zero-demand SKU-days were retained. "
        f"{'Total actual demand is zero, so WAPE and relative reduction are undefined.' if metadata['zero_total_actual_demand'] else ''}"
    )
    exclusions = metadata["exclusion_counts"]
    exclusion_text = (
        "\n".join(f"- {reason}: {count} SKU(s)" for reason, count in exclusions.items())
        if exclusions else "- None"
    )
    warning_rows = []
    warning_rows.append(
        "- The repository describes its reproducible dataset as realistic sample data. Verify that the evaluated CSVs "
        "are actual operational records before presenting this as measured Sahoo Traders business performance."
    )
    if metadata["eligible_skus"] < 20:
        warning_rows.append("- Fewer than 20 SKUs were eligible; aggregate findings may not generalize.")
    if metadata["zero_total_actual_demand"]:
        warning_rows.append("- WAPE and relative WAPE reduction are undefined because total actual demand is zero.")
    warning_rows.append(
        "- This is one chronological test window. Repeated rolling-origin backtests are needed before treating "
        "the result as a stable estimate of future performance."
    )
    warning_text = "\n".join(warning_rows)
    data_source = str(data_root.resolve())
    report = f"""# Demand Forecast Performance

## Dataset and evaluation configuration

- Source: `{data_source}` (`products.csv`, `sales.csv`) via `load_sample_data`; production data was read only.
- Provenance caveat: repository documentation describes a reproducible realistic sample-data generator. The benchmark uses the CSVs already present and does not synthesize or alter rows, but their origin as actual distributor transactions is not independently verified.
- Sales records: {metadata['sales_record_count']:,}; catalog SKUs: {metadata['dataset_sku_count']}.
- Dataset sales dates: {metadata['dataset_first_sale_date']} through {metadata['dataset_last_sale_date']}.
- Selection training cutoff: {metadata['selection_training_end']}.
- Validation window: {metadata['validation_start']} through {metadata['validation_end']} ({metadata['validation_days']} days).
- Final test training cutoff: {metadata['test_training_end']}.
- Untouched test window: {metadata['test_start']} through {metadata['test_end']} ({metadata['test_days']} days).
- Minimum pre-test history: {metadata['min_pre_test_history_days']} continuous daily observations.
- Eligible SKUs: {metadata['eligible_skus']}; excluded SKUs: {metadata['excluded_skus']}.
- Evaluated predictions: {metadata['sku_day_predictions']:,} SKU-days over the same eligible SKUs for every candidate.
- Models: naive last-value, additive damped-trend exponential smoothing, and per-SKU scikit-learn Random Forest.
- Selection: lowest validation-window MAE per SKU. Final model forecasts are refit through the day before test; test labels are untouched until scoring.
- Random Forest seed: 42; defaults: 200 trees, minimum leaf size 2, `max_features=0.8`, one job.
- Metrics: {metadata['metrics_method']}
- Recursive Random Forest evaluation: {metadata['recursive_method']}
- Input SHA-256: {json.dumps(file_fingerprints, sort_keys=True)}

## Untouched test results

{chr(10).join(summary_table)}

The validation-selected strategy's relative WAPE reduction vs naive is **{_fmt(reduction)}%** using `((naive WAPE - selected WAPE) / naive WAPE) * 100`. This is reported only when naive WAPE is nonzero and both scores use the same test observations. Aggregate absolute actual demand was {actual_total:,.2f} units. {actual_note}

Test wins are a diagnostic ranking by per-SKU test MAE; ties are awarded once using the fixed order naive, exponential smoothing, Random Forest. They did not select the production winner. "Selected SKUs" counts validation-based model choices.

## Exclusions and limitations

{exclusion_text}

{warning_text}

No model is presumed best. The selected-strategy result is a single fixed-window benchmark, not a causal claim or guarantee. The CSVs include per-SKU scores, chosen model, test winner, and exclusions.
"""
    report_path.write_text(report, encoding="utf-8")
    return report_path, sku_csv_path, summary_csv_path


def _fmt(value: float | int | None) -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value:.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--test-days", type=int, default=DEFAULT_TEST_DAYS)
    parser.add_argument("--validation-days", type=int, default=DEFAULT_VALIDATION_DAYS)
    parser.add_argument("--min-train-days", type=int, default=DEFAULT_MIN_TRAIN_DAYS)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    products, sales, *_ = load_sample_data(args.data_dir)
    result = run_benchmark(
        products,
        sales,
        test_days=args.test_days,
        validation_days=args.validation_days,
        min_train_days=args.min_train_days,
    )
    report_path, sku_csv_path, summary_csv_path = write_outputs(
        result, args.data_dir, args.output_dir
    )
    print(f"Eligible SKUs: {result['metadata']['eligible_skus']}")
    print(f"Excluded SKUs: {result['metadata']['excluded_skus']}")
    print(f"SKU-day predictions: {result['metadata']['sku_day_predictions']}")
    print(f"Selected WAPE: {_fmt(result['selected_aggregate']['wape_pct'])}%")
    print(f"Naive WAPE: {_fmt(result['candidate_aggregate']['naive baseline']['wape_pct'])}%")
    print(f"Relative WAPE reduction: {_fmt(result['selected_vs_naive_wape_reduction_pct'])}%")
    print(f"Report: {report_path}")
    print(f"Per-SKU CSV: {sku_csv_path}")
    print(f"Summary CSV: {summary_csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
