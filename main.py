"""
main.py
Entry point for the weather prediction model comparison application.

Pipeline per station:
  1. Fetch raw daily data  (data_fetch.py)
  2. Pre-process           (preprocessing.py)
  3. Train all five models (models.py)
  4. Evaluate              (evaluation.py)
  5. Visualise             (visualization.py)

Run with:
    python main.py
"""

import warnings
warnings.filterwarnings("ignore")

from datetime import datetime
import numpy as np
import pandas as pd

# ── Project modules ────────────────────────────────────────────────────────────
from data_fetch import fetch_all_data, TARGET_COLUMNS
from preprocessing import preprocess_station
# DEVICE is printed to console the moment models.py is imported
from models import (
    DEVICE,
    build_model, train_deep_model, predict_deep,
    train_linear_regression, predict_linear_regression,
    train_all_arima, predict_arima,
)
from evaluation import evaluate_all_models, print_metrics_summary
from visualization import create_comparison_figure, create_station_metrics_figure

# ── Hyper-parameters ───────────────────────────────────────────────────────────
SEQ_LEN     = 30
HIDDEN_SIZE = 256
NUM_LAYERS  = 3
DROPOUT     = 0.2
EPOCHS      = 200
BATCH_SIZE  = 32
PATIENCE    = 20


# ── Per-station pipeline ───────────────────────────────────────────────────────

def run_station(station_name: str, df: pd.DataFrame) -> dict:
    """
    Execute the full modelling pipeline for one station.
    Returns a result dict consumed by evaluation & visualization.
    """
    print(f"\n{'=' * 62}")
    print(f"  Station: {station_name}")
    print(f"{'=' * 62}")

    # ── Pre-processing ─────────────────────────────────────────────────────────
    proc = preprocess_station(df, columns=TARGET_COLUMNS, seq_len=SEQ_LEN)

    X_train  = proc["X_train"]
    y_train  = proc["y_train"]
    X_test   = proc["X_test"]
    y_test   = proc["y_test"]
    scalers  = proc["scalers"]
    test_df  = proc["test_df"]
    columns  = proc["columns"]

    n_features = X_train.shape[2]   # == len(columns)
    n_outputs  = y_train.shape[1]   # == len(columns)

    raw_predictions: dict[str, np.ndarray] = {}

    # ── GRU ───────────────────────────────────────────────────────────────────
    print("\n  [1/5] GRU (bidirectional, 3 layers) ...")
    gru = build_model("GRU", n_features, n_outputs, HIDDEN_SIZE, NUM_LAYERS, DROPOUT)
    gru = train_deep_model(gru, X_train, y_train, X_test, y_test,
                           EPOCHS, BATCH_SIZE, PATIENCE)
    raw_predictions["GRU"] = predict_deep(gru, X_test)

    # ── LSTM ──────────────────────────────────────────────────────────────────
    print("\n  [2/5] LSTM (bidirectional, 3 layers) ...")
    lstm = build_model("LSTM", n_features, n_outputs, HIDDEN_SIZE, NUM_LAYERS, DROPOUT)
    lstm = train_deep_model(lstm, X_train, y_train, X_test, y_test,
                            EPOCHS, BATCH_SIZE, PATIENCE)
    raw_predictions["LSTM"] = predict_deep(lstm, X_test)

    # ── Simple RNN ────────────────────────────────────────────────────────────
    print("\n  [3/5] SimpleRNN (unidirectional, 3 layers) ...")
    rnn = build_model("SimpleRNN", n_features, n_outputs, HIDDEN_SIZE, NUM_LAYERS, DROPOUT)
    rnn = train_deep_model(rnn, X_train, y_train, X_test, y_test,
                           EPOCHS, BATCH_SIZE, PATIENCE)
    raw_predictions["SimpleRNN"] = predict_deep(rnn, X_test)

    # ── Linear Regression ─────────────────────────────────────────────────────
    print("\n  [4/5] Linear Regression ...")
    lr_model = train_linear_regression(X_train, y_train)
    raw_predictions["LinearRegression"] = predict_linear_regression(lr_model, X_test)

    # ── ARIMA ─────────────────────────────────────────────────────────────────
    print("\n  [5/5] ARIMA (auto_arima, AIC, seasonal=False) ...")
    arima_models = train_all_arima(proc["train_df"], columns)
    # Forecast len(test_df) steps ahead, then trim to align with y_test
    raw_predictions["ARIMA"] = predict_arima(
        arima_models, len(test_df), SEQ_LEN, columns
    )

    # ── Inverse-transform back to original scale ───────────────────────────────
    def inverse(arr: np.ndarray) -> np.ndarray:
        """Apply the per-column MinMaxScaler inverse to a (N, n_cols) array."""
        out = np.empty_like(arr)
        for i, col in enumerate(columns):
            out[:, i] = scalers[col].inverse_transform(
                arr[:, i].reshape(-1, 1)
            ).ravel()
        return out

    y_test_orig   = inverse(y_test)
    predictions   = {name: inverse(p) for name, p in raw_predictions.items()}

    # ── Test-set dates aligned to y_test ──────────────────────────────────────
    test_dates = test_df.index[SEQ_LEN:]

    # ── Evaluate ───────────────────────────────────────────────────────────────
    metrics = evaluate_all_models(predictions, y_test_orig, columns)
    print_metrics_summary(metrics, station_name, columns)

    return {
        "actuals":     y_test_orig,
        "predictions": predictions,
        "metrics":     metrics,
        "columns":     columns,
        "dates":       test_dates,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n" + "=" * 62)
    print("  Weather Prediction Model Comparison")
    print(f"  Device : {DEVICE}")
    print(f"  Period : 2020-01-01 -> {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 62)

    # Fetch all raw data
    station_data = fetch_all_data(
        start=datetime(2020, 1, 1),
        end=datetime.now(),
    )

    # Run full pipeline per station
    station_results: dict = {}
    for station_name, df in station_data.items():
        station_results[station_name] = run_station(station_name, df)

    # Visualise
    print("\n" + "=" * 62)
    print("  Generating figures …")
    print("=" * 62)
    create_comparison_figure(station_results, output_dir="plots")
    create_station_metrics_figure(station_results, output_dir="plots")

    print("\nAll done — plots saved to ./plots/\n")


if __name__ == "__main__":
    main()
