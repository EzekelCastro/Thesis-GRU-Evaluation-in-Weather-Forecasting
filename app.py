"""
app.py
Streamlit web UI for the weather prediction model comparison pipeline.

Run with:
    streamlit run app.py
"""

import hashlib
import io
import json
import os
import pickle
import warnings
warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")          # non-interactive backend required by Streamlit
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime, date, timedelta

from data_fetch import fetch_all_data, TARGET_COLUMNS
from preprocessing import preprocess_station
from models import (
    DEVICE,
    build_model, train_deep_model, predict_deep,
    train_linear_regression, predict_linear_regression,
    train_all_arima, predict_arima,
)
from evaluation import evaluate_all_models
from visualization import MODEL_COLORS, VARIABLE_LABELS


# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Weather Prediction Comparison",
    page_icon="🌤",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Helper: inverse-transform a (N, n_cols) scaled array ──────────────────────

def _inverse(arr: np.ndarray, scalers: dict, columns: list) -> np.ndarray:
    out = np.empty_like(arr, dtype=np.float64)
    for i, col in enumerate(columns):
        out[:, i] = scalers[col].inverse_transform(
            arr[:, i].reshape(-1, 1)
        ).ravel()
    return out


# ── Helper: build a matplotlib figure for one station ─────────────────────────

def _make_prediction_figure(station_name: str, res: dict) -> plt.Figure:
    columns     = res["columns"]
    actuals     = res["actuals"]
    predictions = res["predictions"]
    dates       = res["dates"]
    model_names = list(predictions.keys())
    n_vars      = len(columns)

    fig, axes = plt.subplots(
        2, 2, figsize=(14, 9),
        constrained_layout=True,
    )
    axes = axes.flatten()

    for idx, col in enumerate(columns):
        ax = axes[idx]
        ax.plot(dates, actuals[:, idx],
                color="black", linewidth=1.8, label="Actual", zorder=5, alpha=0.9)
        for mn in model_names:
            ax.plot(dates, predictions[mn][:, idx],
                    color=MODEL_COLORS.get(mn, "gray"),
                    linewidth=1.1, linestyle="--", alpha=0.80, label=mn)
        ax.set_title(VARIABLE_LABELS.get(col, col), fontsize=11, fontweight="bold")
        ax.set_xlabel("Date", fontsize=8)
        ax.set_ylabel(VARIABLE_LABELS.get(col, col), fontsize=8)
        ax.legend(fontsize=7, loc="best", framealpha=0.7)
        ax.grid(True, alpha=0.25, linestyle=":")
        ax.tick_params(axis="x", rotation=30, labelsize=7)

    # Hide any unused subplot slots
    for idx in range(n_vars, len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle(f"Predictions — {station_name}", fontsize=14, fontweight="bold")
    return fig


# ── Helper: build a metrics DataFrame for one variable ────────────────────────

def _metrics_dataframe(metrics: dict, model_names: list, col: str) -> pd.DataFrame:
    rows = []
    for mn in model_names:
        m = metrics[mn][col]
        acc = m["Accuracy (%)"]
        rows.append({
            "Model":        mn,
            "Accuracy (%)": round(acc, 2) if not np.isnan(acc) else float("nan"),
            "MSE":          round(m["MSE"], 5),
            "MAE":          round(m["MAE"], 5),
            "R2":           round(m["R2"], 4),
        })
    return pd.DataFrame(rows).set_index("Model")


# ── Helper: save a figure to bytes for download ───────────────────────────────

def _fig_to_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    return buf.read()


# ── Cache helpers ──────────────────────────────────────────────────────────────

_CACHE_DIR = "cache"


def _make_cache_key(start_date, end_date, stations, models,
                    epochs, hidden_size, seq_len, batch_size,
                    patience, num_layers, dropout) -> str:
    s = "|".join([
        str(start_date), str(end_date),
        ",".join(sorted(stations)),
        ",".join(sorted(models)),
        str(epochs), str(hidden_size), str(seq_len),
        str(batch_size), str(patience), str(num_layers), str(dropout),
    ])
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def _pkl_path(key: str) -> str:
    return os.path.join(_CACHE_DIR, f"results_{key}.pkl")


def _meta_path(key: str) -> str:
    return os.path.join(_CACHE_DIR, f"meta_{key}.json")


def _save_cache(key: str, results: dict, meta: dict) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_pkl_path(key), "wb") as f:
        pickle.dump(results, f)
    with open(_meta_path(key), "w") as f:
        json.dump(meta, f)


def _load_cache_meta(key: str) -> dict | None:
    path = _meta_path(key)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _load_cache(key: str) -> dict | None:
    path = _pkl_path(key)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def _clear_all_cache() -> int:
    if not os.path.exists(_CACHE_DIR):
        return 0
    removed = 0
    for fname in os.listdir(_CACHE_DIR):
        if fname.endswith((".pkl", ".json")):
            os.remove(os.path.join(_CACHE_DIR, fname))
            removed += 1
    return removed


def _models_pkl_path(key: str) -> str:
    return os.path.join(_CACHE_DIR, f"models_{key}.pkl")


def _save_models_cache(key: str, dl_states: dict) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_models_pkl_path(key), "wb") as f:
        pickle.dump(dl_states, f)


def _load_models_cache(key: str) -> dict | None:
    path = _models_pkl_path(key)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def _generate_forecast(
    forecast_data: dict,
    station_name: str,
    selected_models: list,
    dl_states: dict | None,
) -> tuple[dict, list]:
    """
    Rolling 7-day forecast from saved model data.

    Returns
    -------
    forecasts      : {model_name: np.ndarray (7, n_cols)} — original scale
    forecast_dates : list[datetime.date]
    """
    import torch

    scalers     = forecast_data["scalers"]
    columns     = forecast_data["columns"]
    cfg         = forecast_data["model_config"]
    seq_len     = cfg["seq_len"]
    n_feat      = cfg["n_feat"]
    n_out       = cfg["n_out"]
    hidden_size = cfg["hidden_size"]
    num_layers  = cfg["num_layers"]
    dropout     = cfg["dropout"]
    n_days      = 7

    df_vals   = forecast_data["df_scaled_values"]   # (N, n_cols) float32
    train_len = forecast_data["train_df_len"]
    last_date = forecast_data["last_test_date"]

    last_window = df_vals[-seq_len:].astype(np.float32)

    forecast_dates = [
        (pd.Timestamp(last_date) + timedelta(days=i + 1)).date()
        for i in range(n_days)
    ]

    def _inv(arr: np.ndarray) -> np.ndarray:
        out = np.empty_like(arr, dtype=np.float64)
        for i, col in enumerate(columns):
            out[:, i] = scalers[col].inverse_transform(arr[:, i : i + 1]).ravel()
        return out

    forecasts: dict = {}

    # ── ARIMA ──
    if "ARIMA" in selected_models and forecast_data.get("arima_models"):
        test_vals   = df_vals[train_len:].astype(np.float32)
        arima_preds = np.zeros((n_days, len(columns)), dtype=np.float32)
        for i, col in enumerate(columns):
            m = forecast_data["arima_models"][col]
            try:
                m.update(test_vals[:, i])
            except Exception:
                pass
            fc = np.array(m.predict(n_periods=n_days), dtype=np.float32)
            arima_preds[:, i] = np.clip(fc, 0.0, 1.0)
        forecasts["ARIMA"] = _inv(arima_preds)

    # ── Linear Regression ──
    if "LinearRegression" in selected_models and forecast_data.get("lr_model") is not None:
        lr = forecast_data["lr_model"]
        window = last_window.copy()
        rows = []
        for _ in range(n_days):
            x = window[-seq_len:].reshape(1, seq_len, len(columns))
            p = predict_linear_regression(lr, x).astype(np.float32)
            p = np.clip(p, 0.0, 1.0)
            rows.append(p[0])
            window = np.vstack([window, p])
        forecasts["LinearRegression"] = _inv(np.array(rows))

    # ── Deep Learning models ──
    for model_name in ["GRU", "LSTM", "SimpleRNN"]:
        if model_name not in selected_models:
            continue
        if not dl_states or model_name not in dl_states:
            continue
        model = build_model(model_name, n_feat, n_out, hidden_size, num_layers, dropout)
        model.load_state_dict({k: v.to(DEVICE) for k, v in dl_states[model_name].items()})
        model.eval()
        window = last_window.copy()
        rows = []
        for _ in range(n_days):
            x = torch.from_numpy(
                window[-seq_len:].reshape(1, seq_len, n_feat)
            ).to(DEVICE)
            with torch.no_grad():
                p = model(x).cpu().numpy().astype(np.float32)
            p = np.clip(p, 0.0, 1.0)
            rows.append(p[0])
            window = np.vstack([window, p])
        forecasts[model_name] = _inv(np.array(rows))

    return forecasts, forecast_dates


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Configuration")
    st.divider()

    st.subheader("Date Range")
    start_date = st.date_input("Start", value=date(2020, 1, 1), min_value=date(2000, 1, 1))
    end_date   = st.date_input("End",   value=date.today())

    st.divider()

    st.subheader("Stations")
    sel_baguio = st.checkbox("Baguio City  (ID: 98328)", value=True)
    sel_manila  = st.checkbox("Manila       (ID: 98425)", value=True)

    st.divider()

    st.subheader("Models")
    sel_models = {
        "GRU":               st.checkbox("GRU  (Bidirectional)", value=True),
        "LSTM":              st.checkbox("LSTM (Bidirectional)", value=True),
        "SimpleRNN":         st.checkbox("Simple RNN",           value=True),
        "LinearRegression":  st.checkbox("Linear Regression",    value=True),
        "ARIMA":             st.checkbox("ARIMA",                value=True),
    }

    st.divider()

    with st.expander("Deep Learning Settings", expanded=False):
        epochs      = st.slider("Epochs",                  10,  200,  100, step=10)
        hidden_size = st.select_slider("Hidden Size",      [64, 128, 256], value=256)
        seq_len     = st.slider("Sequence Length (days)",   7,   60,   30)
        batch_size  = st.select_slider("Batch Size",       [16, 32, 64],  value=32)
        patience    = st.slider("Early Stop Patience",      5,   30,   20)
        num_layers  = st.slider("Stacked RNN Layers",       1,    4,    3)
        dropout     = st.slider("Dropout",                0.0,  0.5, 0.2, step=0.05)

    st.divider()

    # Derive the cache key from current sidebar settings
    _preview_stations = [k for k, v in {"Baguio": sel_baguio, "Manila": sel_manila}.items() if v]
    _preview_models   = [k for k, v in sel_models.items() if v]
    _cache_key = _make_cache_key(
        start_date, end_date, _preview_stations, _preview_models,
        epochs, hidden_size, seq_len, batch_size, patience, num_layers, dropout,
    )
    _cached_meta = _load_cache_meta(_cache_key)

    if _cached_meta:
        st.success(
            f"Saved results found\n\n"
            f"**{_cached_meta['saved_at']}**\n\n"
            f"Stations: {', '.join(_cached_meta['stations'])}\n\n"
            f"Models: {', '.join(_cached_meta['models'])}"
        )
        load_cache_btn = st.button(
            "Load Saved Results", type="primary", use_container_width=True
        )
    else:
        load_cache_btn = False

    run_btn   = st.button(
        "Run Analysis",
        type="secondary" if _cached_meta else "primary",
        use_container_width=True,
    )
    clear_btn = st.button("Clear Display", type="secondary", use_container_width=True)

    st.divider()

    with st.expander("Cache Management"):
        cache_files = len(os.listdir(_CACHE_DIR)) // 2 if os.path.exists(_CACHE_DIR) else 0
        st.caption(f"{cache_files} saved result(s) on disk.")
        clear_cache_btn = st.button(
            "Delete All Saved Results", type="secondary", use_container_width=True
        )

    st.divider()
    st.caption(f"Device: `{DEVICE}`")
    st.caption("Meteostat · PyTorch · pmdarima · Streamlit")


# ── Session state ──────────────────────────────────────────────────────────────

if "results" not in st.session_state:
    st.session_state.results = None

if clear_btn:
    st.session_state.results = None
    st.rerun()

if clear_cache_btn:
    n = _clear_all_cache()
    st.session_state.results = None
    st.toast(f"Deleted {n} cache file(s).", icon="🗑️")
    st.rerun()

if load_cache_btn:
    cached = _load_cache(_cache_key)
    if cached:
        st.session_state.results = cached
        st.toast("Results loaded from cache!", icon="💾")
        st.rerun()
    else:
        st.error("Cache file not found. Please run a fresh analysis.")


# ── Page header ────────────────────────────────────────────────────────────────

st.title("Weather Prediction Model Comparison")
st.caption(
    "GRU · LSTM · SimpleRNN · Linear Regression · ARIMA  |  "
    "Baguio City vs Manila  |  Meteostat daily data from 2020"
)
st.divider()


# ── Run pipeline ───────────────────────────────────────────────────────────────

if run_btn:
    active_stations = [k for k, v in {"Baguio": sel_baguio, "Manila": sel_manila}.items() if v]
    active_models   = [k for k, v in sel_models.items() if v]

    # Validation
    if not active_stations:
        st.error("Please select at least one station.")
        st.stop()
    if not active_models:
        st.error("Please select at least one model.")
        st.stop()
    if start_date >= end_date:
        st.error("Start date must be before end date.")
        st.stop()

    station_results: dict = {}
    all_dl_states:   dict = {}   # station_name → {model_name: state_dict}
    total_steps = len(active_stations) * len(active_models)
    step = 0

    with st.status("Running analysis...", expanded=True) as run_status:

        # ── Fetch ──────────────────────────────────────────────────────────────
        st.write("Fetching weather data from Meteostat...")
        all_data = fetch_all_data(
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date,   datetime.min.time()),
        )
        filtered = {k: v for k, v in all_data.items() if k in active_stations}
        total_records = sum(len(v) for v in filtered.values())
        st.write(f"Fetched {total_records:,} records across {len(filtered)} station(s).")

        progress_bar = st.progress(0, text="Preparing...")

        for station_name, df in filtered.items():

            # ── Preprocess ─────────────────────────────────────────────────────
            st.write(f"Preprocessing {station_name}...")
            proc    = preprocess_station(df, columns=TARGET_COLUMNS, seq_len=seq_len)
            X_train = proc["X_train"]
            y_train = proc["y_train"]
            X_test  = proc["X_test"]
            y_test  = proc["y_test"]
            scalers = proc["scalers"]
            test_df = proc["test_df"]
            columns = proc["columns"]
            n_feat  = X_train.shape[2]
            n_out   = y_train.shape[1]

            raw_preds:         dict = {}
            _dl_states_station: dict = {}
            _arima_m_station        = None
            _lr_m_station           = None

            # ── Train each model ───────────────────────────────────────────────
            for model_name in active_models:
                pct  = step / total_steps
                text = f"Training {model_name} for {station_name}..."
                progress_bar.progress(pct, text=text)
                st.write(f"  {model_name} — {station_name}...")

                if model_name in ("GRU", "LSTM", "SimpleRNN"):
                    m = build_model(model_name, n_feat, n_out, hidden_size, num_layers, dropout)
                    m = train_deep_model(
                        m, X_train, y_train, X_test, y_test,
                        epochs, batch_size, patience,
                    )
                    raw_preds[model_name] = predict_deep(m, X_test)
                    _dl_states_station[model_name] = {
                        k: v.cpu() for k, v in m.state_dict().items()
                    }

                elif model_name == "LinearRegression":
                    m = train_linear_regression(X_train, y_train)
                    raw_preds[model_name] = predict_linear_regression(m, X_test)
                    _lr_m_station = m

                elif model_name == "ARIMA":
                    arima_m = train_all_arima(proc["train_df"], columns)
                    raw_preds[model_name] = predict_arima(
                        arima_m, len(test_df), seq_len, columns
                    )
                    _arima_m_station = arima_m

                step += 1
                progress_bar.progress(step / total_steps,
                                      text=f"Done: {model_name} — {station_name}")

            # ── Inverse transform & evaluate ───────────────────────────────────
            y_true_orig = _inverse(y_test, scalers, columns)
            preds_orig  = {n: _inverse(p, scalers, columns) for n, p in raw_preds.items()}
            metrics     = evaluate_all_models(preds_orig, y_true_orig, columns)

            station_results[station_name] = {
                "actuals":     y_true_orig,
                "predictions": preds_orig,
                "metrics":     metrics,
                "columns":     columns,
                "dates":       test_df.index[seq_len:],
                "forecast_data": {
                    "scalers":           scalers,
                    "columns":           columns,
                    "arima_models":      _arima_m_station,
                    "lr_model":          _lr_m_station,
                    "train_df_len":      len(proc["train_df"]),
                    "df_scaled_values":  proc["df_scaled"][columns].values.astype(np.float32),
                    "last_test_date":    test_df.index[-1],
                    "model_config": {
                        "n_feat":      n_feat,
                        "n_out":       n_out,
                        "hidden_size": hidden_size,
                        "num_layers":  num_layers,
                        "dropout":     dropout,
                        "seq_len":     seq_len,
                    },
                },
            }

            all_dl_states[station_name] = _dl_states_station

        progress_bar.progress(1.0, text="Complete!")
        run_status.update(label="Analysis complete!", state="complete", expanded=False)

    # Save DL model weights for forecasting (separate, larger file)
    if all_dl_states:
        _save_models_cache(_cache_key, all_dl_states)

    # Save results to cache so future visits skip retraining
    _save_cache(
        _cache_key,
        station_results,
        {
            "saved_at":   datetime.now().strftime("%Y-%m-%d %H:%M"),
            "stations":   active_stations,
            "models":     active_models,
            "date_range": f"{start_date} → {end_date}",
            "epochs":     epochs,
            "seq_len":    seq_len,
        },
    )
    st.toast("Results saved to cache.", icon="💾")
    st.session_state.results = station_results


# ── Display results ────────────────────────────────────────────────────────────

if st.session_state.results:
    results     = st.session_state.results
    all_columns = next(iter(results.values()))["columns"]
    model_names = list(next(iter(results.values()))["predictions"].keys())

    tab_pred, tab_metrics, tab_fc, tab_dl = st.tabs(
        ["Predictions", "Metrics", "Forecast", "Download"]
    )

    # ── Tab 1: Prediction plots ────────────────────────────────────────────────
    with tab_pred:
        st.subheader("Actual vs Predicted")
        station_list = list(results.keys())

        if len(station_list) == 2:
            left_col, right_col = st.columns(2)
            col_map = {station_list[0]: left_col, station_list[1]: right_col}
        else:
            col_map = {station_list[0]: st}   # full width

        for station_name, res in results.items():
            container = col_map[station_name]
            fig = _make_prediction_figure(station_name, res)
            container.pyplot(fig, use_container_width=True)
            plt.close(fig)

    # ── Tab 2: Metrics tables ──────────────────────────────────────────────────
    with tab_metrics:
        st.subheader("Performance Metrics")
        st.caption(
            "Accuracy = 100 - MAPE (higher is better).  "
            "MSE / MAE in original physical units.  "
            "R² closer to 1.0 is better."
        )

        metric_choice = st.radio(
            "Metric to chart:",
            ["Accuracy (%)", "R2", "MSE", "MAE"],
            horizontal=True,
            index=0,
        )

        _short = {
            "GRU":              "GRU",
            "LSTM":             "LSTM",
            "SimpleRNN":        "RNN",
            "LinearRegression": "LR",
            "ARIMA":            "ARIMA",
        }

        for station_name, res in results.items():
            st.markdown(f"### {station_name}")

            # ── Metric tables ──────────────────────────────────────────────────
            metric_cols = st.columns(len(all_columns))
            for col_idx, col in enumerate(all_columns):
                with metric_cols[col_idx]:
                    st.markdown(f"**{VARIABLE_LABELS.get(col, col)}**")
                    df_m = _metrics_dataframe(res["metrics"], model_names, col)

                    def _style(df):
                        best  = df["R2"].idxmax()
                        worst = df["R2"].idxmin()
                        colors = pd.DataFrame("", index=df.index, columns=df.columns)
                        colors.loc[best,  :] = "background-color: #d4edda"
                        colors.loc[worst, :] = "background-color: #f8d7da"
                        return colors

                    styled = df_m.style.apply(_style, axis=None).format(precision=4)
                    st.dataframe(styled, use_container_width=True)

            # ── Bar charts ─────────────────────────────────────────────────────
            st.markdown(f"**{metric_choice} by Model — {station_name}**")
            chart_cols = st.columns(len(all_columns))
            for col_idx, col in enumerate(all_columns):
                with chart_cols[col_idx]:
                    labels = [_short.get(mn, mn) for mn in model_names]
                    values = [
                        res["metrics"][mn][col].get(metric_choice, float("nan"))
                        for mn in model_names
                    ]
                    bar_colors = [MODEL_COLORS.get(mn, "#cccccc") for mn in model_names]

                    fig, ax = plt.subplots(figsize=(4, 3.2))
                    bars = ax.bar(labels, values, color=bar_colors,
                                  edgecolor="white", linewidth=0.6)

                    for bar, val in zip(bars, values):
                        if not np.isnan(val):
                            ax.text(
                                bar.get_x() + bar.get_width() / 2,
                                bar.get_height(),
                                f"{val:.3f}",
                                ha="center", va="bottom", fontsize=6.5,
                            )

                    ax.set_title(VARIABLE_LABELS.get(col, col),
                                 fontsize=9, fontweight="bold")
                    ax.set_xlabel("Model", fontsize=8)
                    ax.set_ylabel(metric_choice, fontsize=8)
                    ax.tick_params(axis="x", labelsize=7.5)
                    ax.tick_params(axis="y", labelsize=7)
                    ax.grid(axis="y", alpha=0.25, linestyle=":")
                    ax.spines[["top", "right"]].set_visible(False)
                    plt.tight_layout()
                    st.pyplot(fig, use_container_width=True)
                    plt.close(fig)

            st.divider()

        # Summary: best model per variable
        st.subheader("Best Model per Variable (by R²)")
        summary_rows = []
        for station_name, res in results.items():
            for col in all_columns:
                best_model = max(
                    model_names,
                    key=lambda mn: res["metrics"][mn][col]["R2"]
                )
                best_r2  = res["metrics"][best_model][col]["R2"]
                best_acc = res["metrics"][best_model][col]["Accuracy (%)"]
                summary_rows.append({
                    "Station":      station_name,
                    "Variable":     VARIABLE_LABELS.get(col, col),
                    "Best Model":   best_model,
                    "R²":           round(best_r2, 4),
                    "Accuracy (%)": round(best_acc, 2) if not np.isnan(best_acc) else float("nan"),
                })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    # ── Tab 3: Forecast ────────────────────────────────────────────────────────
    with tab_fc:
        st.subheader("7-Day Weather Forecast")
        st.caption(
            "Rolling day-by-day forecast generated from saved model data.  "
            "Dates are the 7 days immediately after the last date in the dataset."
        )

        fc_station = st.radio(
            "Station", list(results.keys()), horizontal=True, key="fc_station"
        )
        fc_res = results[fc_station]

        if "forecast_data" not in fc_res:
            st.warning(
                "Forecast data not found in this cache entry.  "
                "Re-run the analysis with the updated code to enable forecasting."
            )
        else:
            forecast_data = fc_res["forecast_data"]
            fc_columns    = fc_res["columns"]
            dl_states_all = _load_models_cache(_cache_key)
            station_dl    = dl_states_all.get(fc_station) if dl_states_all else None
            has_dl        = station_dl is not None

            st.divider()
            col_m, col_v = st.columns(2)

            with col_m:
                st.markdown("**Select Models**")
                fc_sel: dict = {}
                for mn in ["GRU", "LSTM", "SimpleRNN"]:
                    available = has_dl and mn in station_dl
                    note      = "" if available else "  *(run locally to enable)*"
                    fc_sel[mn] = st.checkbox(
                        f"{mn}{note}",
                        value=available,
                        disabled=not available,
                        key=f"fc_m_{mn}",
                    )
                lr_ok   = forecast_data.get("lr_model") is not None
                arima_ok = forecast_data.get("arima_models") is not None
                fc_sel["LinearRegression"] = st.checkbox(
                    "Linear Regression",
                    value=lr_ok, disabled=not lr_ok, key="fc_m_lr",
                )
                fc_sel["ARIMA"] = st.checkbox(
                    "ARIMA", value=arima_ok, disabled=not arima_ok, key="fc_m_arima",
                )

            with col_v:
                st.markdown("**Select Variables**")
                fc_vars: dict = {}
                for col in fc_columns:
                    fc_vars[col] = st.checkbox(
                        VARIABLE_LABELS.get(col, col), value=True, key=f"fc_v_{col}"
                    )

            active_fc_models = [mn for mn, v in fc_sel.items()  if v]
            active_fc_vars   = [col for col, v in fc_vars.items() if v]

            if not active_fc_models:
                st.error("Select at least one model.")
            elif not active_fc_vars:
                st.error("Select at least one variable.")
            else:
                last_d = pd.Timestamp(forecast_data["last_test_date"])
                st.info(
                    f"Last data point in cache: **{last_d.strftime('%B %d, %Y')}**  "
                    f"— forecast covers the following 7 days."
                )
                gen_btn = st.button(
                    "Generate 7-Day Forecast", type="primary", key="fc_gen"
                )

                if gen_btn:
                    with st.spinner("Generating forecast..."):
                        try:
                            forecasts, forecast_dates = _generate_forecast(
                                forecast_data,
                                fc_station,
                                active_fc_models,
                                station_dl,
                            )
                        except Exception as exc:
                            st.error(f"Forecast failed: {exc}")
                            st.stop()

                    st.success(
                        f"Forecast ready — "
                        f"**{forecast_dates[0].strftime('%A, %b %d')}** "
                        f"to "
                        f"**{forecast_dates[-1].strftime('%A, %b %d %Y')}**"
                    )

                    col_idx_map = {col: i for i, col in enumerate(fc_columns)}

                    for col in active_fc_vars:
                        ci        = col_idx_map[col]
                        var_label = VARIABLE_LABELS.get(col, col)

                        st.markdown(f"#### {var_label}")

                        # ── Detailed table ─────────────────────────────────────
                        rows = []
                        for d_i, d in enumerate(forecast_dates):
                            row = {
                                "Day":  d.strftime("%A"),
                                "Date": d.strftime("%b %d, %Y"),
                            }
                            for mn in active_fc_models:
                                if mn in forecasts:
                                    row[mn] = round(float(forecasts[mn][d_i, ci]), 4)
                            rows.append(row)

                        st.dataframe(
                            pd.DataFrame(rows),
                            use_container_width=True,
                            hide_index=True,
                        )

                        # ── Line chart ─────────────────────────────────────────
                        fig, ax = plt.subplots(figsize=(10, 3.5))
                        x_labels = [
                            f"{d.strftime('%a')}\n{d.strftime('%b %d')}"
                            for d in forecast_dates
                        ]
                        for mn in active_fc_models:
                            if mn in forecasts:
                                ax.plot(
                                    x_labels,
                                    forecasts[mn][:, ci],
                                    marker="o",
                                    color=MODEL_COLORS.get(mn, "gray"),
                                    linewidth=2.0,
                                    markersize=6,
                                    label=mn,
                                )
                        ax.set_title(
                            f"{fc_station}  —  {var_label}  |  7-Day Forecast",
                            fontsize=11, fontweight="bold",
                        )
                        ax.set_ylabel(var_label, fontsize=9)
                        ax.legend(fontsize=8, loc="best")
                        ax.grid(True, alpha=0.25, linestyle=":")
                        ax.spines[["top", "right"]].set_visible(False)
                        plt.tight_layout()
                        st.pyplot(fig, use_container_width=True)
                        plt.close(fig)

                        st.divider()

    # ── Tab 4: Download ────────────────────────────────────────────────────────
    with tab_dl:
        st.subheader("Download Plots")
        st.caption("Each figure is saved at 150 dpi as a PNG.")

        for station_name, res in results.items():
            fig = _make_prediction_figure(station_name, res)
            png = _fig_to_bytes(fig)
            plt.close(fig)
            fname = f"predictions_{station_name.lower().replace(' ', '_')}.png"
            st.download_button(
                label=f"Download — {station_name} prediction plot",
                data=png,
                file_name=fname,
                mime="image/png",
                use_container_width=True,
            )

else:
    # ── Welcome screen ─────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    col1.metric("Stations",  "2", "Baguio City & Manila")
    col2.metric("Models",    "5", "GRU · LSTM · RNN · LR · ARIMA")
    col3.metric("Variables", "4", "Precipitation · Temp · Wind · Pressure")

    st.info(
        "Configure the settings in the sidebar, then click **Run Analysis** to start.\n\n"
        "Training on CPU typically takes 5 – 20 minutes depending on epochs and models selected. "
        "Results persist in the session — you can switch tabs without re-running."
    )
