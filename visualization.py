"""
visualization.py
Produces two output figures saved as PNG (and shown interactively):

  weather_model_comparison.png
      Subplot grid: rows = weather variables, columns = stations.
      Each cell contains:
        (a) prediction plot — actual (black) + one dashed line per model
        (b) metrics table   — Accuracy / MSE / MAE / R² for that cell

  metrics_<station>.png
      Stand-alone, wider metrics table per station for easy reading.
"""

import os
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# Use Agg backend when running headless; will still call plt.show() which
# is a no-op on Agg, allowing the file-save path to always succeed.
try:
    import tkinter  # noqa: F401 — test if a display is available
except Exception:
    matplotlib.use("Agg")

# ── Styling constants ──────────────────────────────────────────────────────────

MODEL_COLORS = {
    "GRU":               "#1f77b4",   # steel blue
    "LSTM":              "#ff7f0e",   # orange
    "SimpleRNN":         "#2ca02c",   # green
    "LinearRegression":  "#d62728",   # red
    "ARIMA":             "#9467bd",   # purple
}

VARIABLE_LABELS = {
    "prcp": "Rainfall (mm)",
    "temp": "Avg Temp (°C)",
    "wspd": "Wind Speed (km/h)",
    "pres": "Pressure (hPa)",
}

TABLE_HEADER_COLOR  = "#2c3e50"
TABLE_ROW_EVEN      = "#eaf0fb"
TABLE_ROW_ODD       = "#ffffff"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _render_metrics_table(ax, metrics: dict, model_names: list, col: str) -> None:
    """Draw a compact metrics table on a pre-existing Axes with axis off."""
    ax.axis("off")
    col_labels = ["Model", "Accuracy (%)", "MSE", "MAE", "R²"]
    rows = []
    row_colors = []
    for i, mn in enumerate(model_names):
        m = metrics[mn][col]
        acc = m["Accuracy (%)"]
        acc_s = f"{acc:.2f}" if not np.isnan(acc) else "N/A"
        rows.append([mn, acc_s, f"{m['MSE']:.4f}", f"{m['MAE']:.4f}", f"{m['R2']:.4f}"])
        row_colors.append(
            [TABLE_ROW_EVEN if i % 2 == 0 else TABLE_ROW_ODD] * len(col_labels)
        )

    tbl = ax.table(
        cellText=rows,
        colLabels=col_labels,
        cellColours=row_colors,
        cellLoc="center",
        loc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7.5)
    tbl.scale(1.0, 1.35)

    # Style the header row
    for j in range(len(col_labels)):
        cell = tbl[0, j]
        cell.set_facecolor(TABLE_HEADER_COLOR)
        cell.set_text_props(color="white", fontweight="bold")

    # Colour the model-name column to match plot lines
    for i, mn in enumerate(model_names):
        cell = tbl[i + 1, 0]
        cell.set_facecolor(MODEL_COLORS.get(mn, "#cccccc"))
        cell.set_text_props(color="white", fontweight="bold")


# ── Public API ─────────────────────────────────────────────────────────────────

def create_comparison_figure(
    station_results: dict,
    output_dir: str = "plots",
) -> str:
    """
    Build the main comparison figure.

    station_results format:
      {
        station_name: {
          "actuals":     np.ndarray  (N, n_cols),
          "predictions": {model_name: np.ndarray (N, n_cols)},
          "metrics":     {model_name: {col: metrics_dict}},
          "columns":     list[str],
          "dates":       pd.DatetimeIndex | np.ndarray,
        }
      }

    Layout: 2 grid rows per variable (plot row + table row) × n_stations columns.
    """
    os.makedirs(output_dir, exist_ok=True)

    stations    = list(station_results.keys())
    columns     = station_results[stations[0]]["columns"]
    model_names = list(station_results[stations[0]]["predictions"].keys())
    n_vars      = len(columns)
    n_stations  = len(stations)

    # 2 rows per variable: tall plot + shorter table
    n_grid_rows   = n_vars * 2
    height_ratios = [4, 2] * n_vars

    fig = plt.figure(figsize=(13 * n_stations, 8 * n_vars))
    gs  = gridspec.GridSpec(
        n_grid_rows, n_stations,
        height_ratios=height_ratios,
        hspace=0.55,
        wspace=0.30,
    )

    fig.suptitle(
        "Weather Prediction Model Comparison — Baguio City vs Manila (2020 – Present)",
        fontsize=17,
        fontweight="bold",
        y=1.005,
    )

    for col_idx, col in enumerate(columns):
        var_label = VARIABLE_LABELS.get(col, col)
        for st_idx, station in enumerate(stations):
            res     = station_results[station]
            actuals = res["actuals"][:, col_idx]
            dates   = res.get("dates", np.arange(len(actuals)))

            # ── Prediction plot ──────────────────────────────────────────────
            ax_plot = fig.add_subplot(gs[col_idx * 2, st_idx])

            ax_plot.plot(
                dates, actuals,
                color="black", linewidth=1.8, label="Actual", zorder=5, alpha=0.9,
            )
            for mn, preds in res["predictions"].items():
                ax_plot.plot(
                    dates, preds[:, col_idx],
                    color=MODEL_COLORS.get(mn, "gray"),
                    linewidth=1.1,
                    linestyle="--",
                    alpha=0.80,
                    label=mn,
                )

            ax_plot.set_title(f"{station}  —  {var_label}", fontsize=11, fontweight="bold")
            ax_plot.set_xlabel("Date", fontsize=8)
            ax_plot.set_ylabel(var_label, fontsize=8)
            ax_plot.legend(fontsize=7, loc="best", framealpha=0.7)
            ax_plot.grid(True, alpha=0.25, linestyle=":")
            ax_plot.tick_params(axis="x", rotation=30, labelsize=7)

            # ── Metrics table ────────────────────────────────────────────────
            ax_tbl = fig.add_subplot(gs[col_idx * 2 + 1, st_idx])
            _render_metrics_table(ax_tbl, res["metrics"], model_names, col)
            ax_tbl.set_title(
                f"Metrics — {station}  {var_label}",
                fontsize=8, pad=3, color="#555555",
            )

    plt.tight_layout()
    out_path = os.path.join(output_dir, "weather_model_comparison.png")
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"  Saved: {out_path}")
    plt.show()
    plt.close(fig)
    return out_path


def create_station_metrics_figure(
    station_results: dict,
    output_dir: str = "plots",
) -> list[str]:
    """
    Create one stand-alone metrics summary figure per station.
    Each figure has one column per weather variable showing a full table.
    """
    os.makedirs(output_dir, exist_ok=True)
    saved_paths = []

    for station, res in station_results.items():
        columns     = res["columns"]
        model_names = list(res["predictions"].keys())
        n_cols      = len(columns)

        fig, axes = plt.subplots(1, n_cols, figsize=(6 * n_cols, 3.5 + 0.5 * len(model_names)))
        if n_cols == 1:
            axes = [axes]

        fig.suptitle(f"Metrics Summary — {station}", fontsize=13, fontweight="bold")

        for ax, col in zip(axes, columns):
            _render_metrics_table(ax, res["metrics"], model_names, col)
            ax.set_title(VARIABLE_LABELS.get(col, col), fontsize=10, pad=6)

        plt.tight_layout()
        fname = f"metrics_{station.lower().replace(' ', '_')}.png"
        out_path = os.path.join(output_dir, fname)
        plt.savefig(out_path, dpi=120, bbox_inches="tight")
        print(f"  Saved: {out_path}")
        plt.show()
        plt.close(fig)
        saved_paths.append(out_path)

    return saved_paths
