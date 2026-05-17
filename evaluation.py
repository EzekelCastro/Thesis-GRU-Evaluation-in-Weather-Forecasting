"""
evaluation.py
Computes four metrics per (model, variable) pair:
  • Accuracy  — (1 - MAPE) × 100 %     (NaN-safe; zero actual values skipped)
  • MSE       — Mean Squared Error
  • MAE       — Mean Absolute Error
  • R²        — Coefficient of determination
"""

import numpy as np
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score


# ── Individual metrics ─────────────────────────────────────────────────────────

def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """MAPE ignoring zero actual values to avoid division by zero."""
    mask = y_true != 0.0
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0)


def model_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Accuracy = max(0, 100 - MAPE)  [percentage]."""
    m = _mape(y_true, y_pred)
    return float("nan") if np.isnan(m) else max(0.0, 100.0 - m)


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Return all four metrics as a flat dict."""
    return {
        "Accuracy (%)": model_accuracy(y_true, y_pred),
        "MSE":           float(mean_squared_error(y_true, y_pred)),
        "MAE":           float(mean_absolute_error(y_true, y_pred)),
        "R2":            float(r2_score(y_true, y_pred)),
    }


# ── Multi-model evaluation ─────────────────────────────────────────────────────

def evaluate_all_models(
    predictions: dict[str, np.ndarray],
    y_true: np.ndarray,
    columns: list[str],
) -> dict[str, dict[str, dict]]:
    """
    Evaluate every model against the ground truth for every column.

    Parameters
    ----------
    predictions : {model_name: array (N, n_cols)}
    y_true      : array (N, n_cols)
    columns     : list of variable names matching axis-1 order

    Returns
    -------
    {model_name: {column_name: metrics_dict}}
    """
    results: dict = {}
    for model_name, y_pred in predictions.items():
        results[model_name] = {}
        for i, col in enumerate(columns):
            results[model_name][col] = compute_metrics(y_true[:, i], y_pred[:, i])
    return results


# ── Console summary ────────────────────────────────────────────────────────────

def print_metrics_summary(
    metrics: dict[str, dict[str, dict]],
    station_name: str,
    columns: list[str],
) -> None:
    """Pretty-print a metrics table for one station to stdout."""
    header = f"  Results — {station_name}"
    print(f"\n{header}")
    print("  " + "─" * (len(header) + 4))
    for model_name, col_metrics in metrics.items():
        print(f"  [{model_name}]")
        for col in columns:
            m = col_metrics[col]
            acc  = m["Accuracy (%)"]
            acc_s = f"{acc:.2f}%" if not np.isnan(acc) else "  N/A  "
            print(
                f"    {col:<6}  Acc={acc_s:>8}  "
                f"MSE={m['MSE']:>10.4f}  "
                f"MAE={m['MAE']:>9.4f}  "
                f"R²={m['R2']:>7.4f}"
            )
