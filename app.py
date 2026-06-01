"""
app.py
Streamlit web UI for the weather prediction model comparison pipeline.

Run with:
    streamlit run app.py
"""

import io
import warnings
warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")          # non-interactive backend required by Streamlit
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime, date

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

    run_btn   = st.button("Run Analysis", type="primary",    use_container_width=True)
    clear_btn = st.button("Clear Results", type="secondary", use_container_width=True)

    st.divider()
    st.caption(f"Device: `{DEVICE}`")
    st.caption("Meteostat · PyTorch · pmdarima · Streamlit")


# ── Session state ──────────────────────────────────────────────────────────────

if "results" not in st.session_state:
    st.session_state.results = None

if clear_btn:
    st.session_state.results = None
    st.rerun()


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

            raw_preds: dict = {}

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

                elif model_name == "LinearRegression":
                    m = train_linear_regression(X_train, y_train)
                    raw_preds[model_name] = predict_linear_regression(m, X_test)

                elif model_name == "ARIMA":
                    arima_m = train_all_arima(proc["train_df"], columns)
                    raw_preds[model_name] = predict_arima(
                        arima_m, len(test_df), seq_len, columns
                    )

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
            }

        progress_bar.progress(1.0, text="Complete!")
        run_status.update(label="Analysis complete!", state="complete", expanded=False)

    st.session_state.results = station_results


# ── Display results ────────────────────────────────────────────────────────────

if st.session_state.results:
    results     = st.session_state.results
    all_columns = next(iter(results.values()))["columns"]
    model_names = list(next(iter(results.values()))["predictions"].keys())

    tab_pred, tab_metrics, tab_dl = st.tabs(["Predictions", "Metrics", "Download"])

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
            "R2 closer to 1.0 is better."
        )

        for station_name, res in results.items():
            st.markdown(f"### {station_name}")
            metric_cols = st.columns(len(all_columns))

            for col_idx, col in enumerate(all_columns):
                with metric_cols[col_idx]:
                    st.markdown(f"**{VARIABLE_LABELS.get(col, col)}**")
                    df_m = _metrics_dataframe(res["metrics"], model_names, col)

                    # Highlight best R2 row green, worst red
                    def _style(df):
                        best  = df["R2"].idxmax()
                        worst = df["R2"].idxmin()
                        colors = pd.DataFrame("", index=df.index, columns=df.columns)
                        colors.loc[best,  :] = "background-color: #d4edda"
                        colors.loc[worst, :] = "background-color: #f8d7da"
                        return colors

                    styled = df_m.style.apply(_style, axis=None).format(precision=4)
                    st.dataframe(styled, use_container_width=True)

            st.divider()

        # Summary: best model per variable
        st.subheader("Best Model per Variable (by R2)")
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
                    "Station":    station_name,
                    "Variable":   VARIABLE_LABELS.get(col, col),
                    "Best Model": best_model,
                    "R2":         round(best_r2, 4),
                    "Accuracy (%)": round(best_acc, 2) if not np.isnan(best_acc) else float("nan"),
                })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    # ── Tab 3: Download ────────────────────────────────────────────────────────
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
