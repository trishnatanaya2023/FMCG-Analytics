# Demand Forecast Performance

## Dataset and evaluation configuration

- Source: `D:\Trishna Projects\FMCG-Analytics\data` (`products.csv`, `sales.csv`) via `load_sample_data`; production data was read only.
- Provenance caveat: repository documentation describes a reproducible realistic sample-data generator. The benchmark uses the CSVs already present and does not synthesize or alter rows, but their origin as actual distributor transactions is not independently verified.
- Sales records: 21,830; catalog SKUs: 60.
- Dataset sales dates: 2024-04-01 through 2025-03-31.
- Selection training cutoff: 2025-01-30.
- Validation window: 2025-01-31 through 2025-03-01 (30 days).
- Final test training cutoff: 2025-03-01.
- Untouched test window: 2025-03-02 through 2025-03-31 (30 days).
- Minimum pre-test history: 60 continuous daily observations.
- Eligible SKUs: 60; excluded SKUs: 0.
- Evaluated predictions: 1,800 SKU-days over the same eligible SKUs for every candidate.
- Models: naive last-value, additive damped-trend exponential smoothing, and per-SKU scikit-learn Random Forest.
- Selection: lowest validation-window MAE per SKU. Final model forecasts are refit through the day before test; test labels are untouched until scoring.
- Random Forest seed: 42; defaults: 200 trees, minimum leaf size 2, `max_features=0.8`, one job.
- Metrics: Aggregate WAPE = sum(abs(actual - predicted)) / sum(abs(actual)) * 100; MAE and RMSE pool all SKU-day errors. All candidates and the selected strategy share the same eligible SKU-day test observations.
- Recursive Random Forest evaluation: The Random Forest predicts each future day, appends that prediction to observed history, then rebuilds lag and rolling features for the next day. Actual validation/test demand is never included in recursive prediction inputs.
- Input SHA-256: {"products.csv": "0a19391ff5cd52d2573cac47e212a0f91f0908e133031e380a7402f1254c0f7c", "sales.csv": "0c5c713161b0f12159cda5d964d8ccacf93581d1c4879371448e386ea74e6dc6"}

## Untouched test results

| Model/strategy | WAPE (%) | MAE | RMSE | Selected SKUs | Test wins | Win share (%) |
|---|---:|---:|---:|---:|---:|---:|
| naive baseline | 75.287 | 8.625 | 11.625 | 11 | 10 | 16.667 |
| damped-trend exponential smoothing | 57.068 | 6.538 | 7.982 | 24 | 35 | 58.333 |
| Random Forest | 60.584 | 6.941 | 8.403 | 25 | 15 | 25.000 |
| Validation-selected per-SKU strategy | 61.071 | 6.996 | 8.692 | 60 | — | — |

The validation-selected strategy's relative WAPE reduction vs naive is **18.883%** using `((naive WAPE - selected WAPE) / naive WAPE) * 100`. This is reported only when naive WAPE is nonzero and both scores use the same test observations. Aggregate absolute actual demand was 20,621.00 units. 2 zero-demand SKU-days were retained. 

Test wins are a diagnostic ranking by per-SKU test MAE; ties are awarded once using the fixed order naive, exponential smoothing, Random Forest. They did not select the production winner. "Selected SKUs" counts validation-based model choices.

## Exclusions and limitations

- None

- The repository describes its reproducible dataset as realistic sample data. Verify that the evaluated CSVs are actual operational records before presenting this as measured Sahoo Traders business performance.
- This is one chronological test window. Repeated rolling-origin backtests are needed before treating the result as a stable estimate of future performance.

No model is presumed best. The selected-strategy result is a single fixed-window benchmark, not a causal claim or guarantee. The CSVs include per-SKU scores, chosen model, test winner, and exclusions.
