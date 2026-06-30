"""
preprocessing.py
Full data-cleaning pipeline:
  1. Missing-value imputation  (forward-fill → backward-fill → linear interpolation)
  2. Outlier removal           (IQR-based; skipped for prcp and zero-IQR columns)
  3. Feature scaling           (MinMax per column; log1p applied first for prcp)
  4. Train / test split        (80 / 20, temporal order preserved)
  5. Sliding-window sequences  (for RNN/LSTM/GRU)
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

TARGET_COLUMNS = ["prcp", "temp", "wspd", "pres"]

# Precipitation is zero-inflated and right-skewed (typhoon days can exceed
# 200 mm). IQR fencing would cap those real extremes at ~12–15 mm, causing
# models to systematically under-predict rainfall.  Skip IQR for prcp only.
_SKIP_IQR = {"prcp"}

# Columns that need a log1p transform before MinMaxScaling.
# Without it, 10 mm rain maps to ~0.03 in scaled space (models learn "prcp ≈ 0").
# log1p: 0→0, 10→0.42, 50→0.68, 200→0.92  — distribution becomes learnable.
_LOG_TRANSFORM = {"prcp"}


class LogMinMaxScaler:
    """
    Drop-in replacement for MinMaxScaler that applies log1p before fitting
    and expm1 after inverse-transforming.  Identical interface so all existing
    scalers[col].inverse_transform(...) calls work without modification.
    """

    def __init__(self):
        self._sc = MinMaxScaler()

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        return self._sc.fit_transform(np.log1p(np.clip(X, 0, None)))

    def transform(self, X: np.ndarray) -> np.ndarray:
        return self._sc.transform(np.log1p(np.clip(X, 0, None)))

    def inverse_transform(self, X: np.ndarray) -> np.ndarray:
        return np.expm1(self._sc.inverse_transform(X))


# ── 1. Missing values ──────────────────────────────────────────────────────────

def handle_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill, then backward-fill, then linear interpolation."""
    df = df.copy()
    df = df.ffill()
    df = df.bfill()
    df = df.interpolate(method="linear", limit_direction="both")
    return df


# ── 2. Outlier removal ─────────────────────────────────────────────────────────

def remove_outliers_iqr(df: pd.DataFrame, columns: list | None = None) -> pd.DataFrame:
    """
    Replace values outside [Q1 - 1.5·IQR, Q3 + 1.5·IQR] with NaN, then
    re-impute.  Skips columns in _SKIP_IQR (prcp) and any column whose IQR
    is zero to avoid erasing legitimate data.
    """
    if columns is None:
        columns = TARGET_COLUMNS
    df = df.copy()
    for col in columns:
        if col not in df.columns:
            continue
        if col in _SKIP_IQR:
            continue
        q1 = df[col].quantile(0.25)
        q3 = df[col].quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        df[col] = df[col].where((df[col] >= lower) & (df[col] <= upper), other=np.nan)
    return handle_missing_values(df)


# ── 3. Scaling ─────────────────────────────────────────────────────────────────

def scale_data(
    df: pd.DataFrame, columns: list | None = None
) -> tuple[pd.DataFrame, dict]:
    """
    Fit one scaler per column and transform in-place.
    Columns in _LOG_TRANSFORM (prcp) use LogMinMaxScaler; others use MinMaxScaler.
    Returns (scaled_df, {col: scaler}) so callers can invert later.
    """
    if columns is None:
        columns = TARGET_COLUMNS
    df_scaled = df.copy()
    scalers: dict = {}
    for col in columns:
        if col not in df.columns:
            continue
        sc = LogMinMaxScaler() if col in _LOG_TRANSFORM else MinMaxScaler()
        df_scaled[col] = sc.fit_transform(df[[col]])
        scalers[col] = sc
    return df_scaled, scalers


# ── 4. Train / test split ──────────────────────────────────────────────────────

def train_test_split_time(
    df: pd.DataFrame, test_ratio: float = 0.2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Temporal split — no shuffling."""
    split_idx = int(len(df) * (1.0 - test_ratio))
    return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()


# ── 5. Sliding-window sequences ────────────────────────────────────────────────

def create_sequences(
    data: np.ndarray, seq_len: int = 30
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build (X, y) pairs with a sliding window of length seq_len.
    X : (N, seq_len, n_features)
    y : (N, n_features)
    """
    X, y = [], []
    for i in range(len(data) - seq_len):
        X.append(data[i : i + seq_len])
        y.append(data[i + seq_len])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


# ── Full pipeline ──────────────────────────────────────────────────────────────

def preprocess_station(
    df: pd.DataFrame,
    columns: list | None = None,
    seq_len: int = 30,
    test_ratio: float = 0.2,
) -> dict:
    """
    Run the entire preprocessing pipeline for one station.

    Returns a dict with keys:
      df_clean, df_scaled, scalers,
      train_df, test_df,
      X_train, y_train, X_test, y_test,
      columns, seq_len
    """
    if columns is None:
        columns = TARGET_COLUMNS

    df_clean = handle_missing_values(df[columns])
    df_clean = remove_outliers_iqr(df_clean, columns)

    # Drop columns that are still entirely NaN after imputation (station has no data).
    # MinMaxScaler cannot fit on all-NaN — this prevents a crash at scale time.
    valid_cols = [c for c in columns if df_clean[c].notna().any()]
    dropped = set(columns) - set(valid_cols)
    if dropped:
        print(f"    Warning: dropping all-NaN columns {sorted(dropped)}")
    columns = valid_cols

    df_scaled, scalers = scale_data(df_clean, columns)

    train_df, test_df = train_test_split_time(df_scaled, test_ratio)

    X_train, y_train = create_sequences(train_df[columns].values, seq_len)
    X_test, y_test = create_sequences(test_df[columns].values, seq_len)

    print(
        f"    Sequences — train: {X_train.shape}, test: {X_test.shape}"
    )

    return {
        "df_clean": df_clean,
        "df_scaled": df_scaled,
        "scalers": scalers,
        "train_df": train_df,
        "test_df": test_df,
        "X_train": X_train,
        "y_train": y_train,
        "X_test": X_test,
        "y_test": y_test,
        "columns": columns,
        "seq_len": seq_len,
    }
