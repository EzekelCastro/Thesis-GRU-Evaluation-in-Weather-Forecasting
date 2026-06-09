"""
feature_analysis.py
Statistical pipeline answering:
  "Which meteorological variables most significantly influence
   the predictive performance of GRU models in weather forecasting?"

Pipeline:
  1. Fetch all available Meteostat variables
  2. Filter by coverage (>= threshold % non-NaN)
  3. Stationarity — ADF test per variable; first-difference non-stationary ones
  4. Correlation — Spearman matrix
  5. Ablation study — leave-one-out GRU retraining (predict target_col)
  6. Diebold-Mariano test — HLN-corrected, per variable removed
  7. Friedman test — across subsets using temporal block-RMSE
  8. Benjamini-Hochberg FDR correction on DM p-values
  9. Auto-generated conclusion text
"""

import numpy as np
import pandas as pd
from datetime import datetime
from scipy import stats
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.multitest import multipletests
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.preprocessing import MinMaxScaler

from models import build_model, train_deep_model, predict_deep


# ── Constants ──────────────────────────────────────────────────────────────────

ALL_METEOSTAT_VARS = [
    "temp", "dwpt", "rhum", "prcp", "snow",
    "wdir", "wspd", "wpgt", "pres", "tsun",
]

VAR_LABELS = {
    "temp": "Avg Temperature (°C)",
    "dwpt": "Dew Point (°C)",
    "rhum": "Relative Humidity (%)",
    "prcp": "Precipitation (mm)",
    "snow": "Snow Depth (mm)",
    "wdir": "Wind Direction (°)",
    "wspd": "Wind Speed (km/h)",
    "wpgt": "Wind Peak Gust (km/h)",
    "pres": "Sea-level Pressure (hPa)",
    "tsun": "Sunshine Duration (min)",
}


# ── 1. Fetch all variables ─────────────────────────────────────────────────────

def fetch_all_variables(station_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch every available Meteostat daily column for a station."""
    from meteostat import daily
    df = daily(station_id, start, end).fetch()
    df.index.name = "time"
    if df.empty:
        raise RuntimeError(f"No data returned for station {station_id}.")
    kept = [c for c in ALL_METEOSTAT_VARS if c in df.columns]
    return df[kept].copy()


# ── 2. Coverage filter ────────────────────────────────────────────────────────

def filter_by_coverage(
    df: pd.DataFrame, min_coverage: float = 0.70
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Keep only columns whose non-NaN fraction >= min_coverage.
    Returns (filtered_df, coverage_summary_df).
    """
    frac   = df.notna().mean()
    kept   = frac[frac >= min_coverage].index.tolist()
    cov_df = pd.DataFrame({
        "Variable":    [VAR_LABELS.get(c, c) for c in frac.index],
        "Key":         list(frac.index),
        "Coverage (%)": (frac.values * 100).round(1),
        "Kept":        ["✓" if c in kept else "✗" for c in frac.index],
    })
    return df[kept].copy(), cov_df


# ── 3. Stationarity ────────────────────────────────────────────────────────────

def run_adf_tests(df: pd.DataFrame) -> pd.DataFrame:
    """
    ADF test for each column.
    H0: unit root (non-stationary). p < 0.05 → stationary.
    """
    rows = []
    for col in df.columns:
        series = df[col].dropna()
        if len(series) < 30:
            rows.append({
                "Variable": col, "Label": VAR_LABELS.get(col, col),
                "ADF Stat": float("nan"), "p-value": float("nan"),
                "Stationary": False, "Action": "Insufficient data",
            })
            continue
        try:
            stat, p, _, _, _, _ = adfuller(series, autolag="AIC")
            stationary = p < 0.05
            rows.append({
                "Variable":   col,
                "Label":      VAR_LABELS.get(col, col),
                "ADF Stat":   round(float(stat), 4),
                "p-value":    round(float(p), 4),
                "Stationary": stationary,
                "Action":     "Use as-is" if stationary else "First-difference",
            })
        except Exception as exc:
            rows.append({
                "Variable": col, "Label": VAR_LABELS.get(col, col),
                "ADF Stat": float("nan"), "p-value": float("nan"),
                "Stationary": False, "Action": f"Error: {exc}",
            })
    return pd.DataFrame(rows)


def apply_stationarity(df: pd.DataFrame, adf_df: pd.DataFrame) -> pd.DataFrame:
    """First-difference columns flagged as non-stationary by ADF."""
    df = df.copy()
    non_stat = adf_df[~adf_df["Stationary"]]["Variable"].tolist()
    for col in non_stat:
        if col in df.columns:
            df[col] = df[col].diff().fillna(0.0)
    return df


# ── 4. Correlation ────────────────────────────────────────────────────────────

def compute_correlation_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Spearman rank correlation — handles non-normal distributions."""
    clean = df.apply(lambda col: col.fillna(col.median()))
    return clean.corr(method="spearman").round(3)


# ── 5. Ablation study ─────────────────────────────────────────────────────────

def _impute(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill → backward-fill → median fill."""
    df = df.copy()
    if "prcp" in df.columns:
        df["prcp"] = df["prcp"].fillna(0.0)
    df = df.ffill().bfill()
    for col in df.columns:
        if df[col].isna().any():
            df[col] = df[col].fillna(df[col].median())
    return df


def _scale(df: pd.DataFrame, cols: list) -> tuple[pd.DataFrame, dict]:
    """MinMaxScale each column; prcp uses log1p first."""
    out      = df.copy()
    scalers  = {}
    for col in cols:
        sc = MinMaxScaler()
        if col == "prcp":
            vals = np.log1p(np.clip(df[[col]].values, 0, None))
            out[col] = sc.fit_transform(vals)
        else:
            out[col] = sc.fit_transform(df[[col]])
        scalers[col] = (sc, col == "prcp")   # (scaler, is_log)
    return out, scalers


def _inverse_col(arr: np.ndarray, scaler_info: tuple) -> np.ndarray:
    sc, is_log = scaler_info
    vals = sc.inverse_transform(arr.reshape(-1, 1)).ravel()
    if is_log:
        vals = np.clip(np.expm1(vals), 0, None)
    return vals


def _make_sequences(X: np.ndarray, Y: np.ndarray, seq_len: int):
    Xs, Ys = [], []
    for i in range(len(X) - seq_len):
        Xs.append(X[i : i + seq_len])
        Ys.append(Y[i + seq_len])
    return np.array(Xs, dtype=np.float32), np.array(Ys, dtype=np.float32)


def run_one_ablation(
    df: pd.DataFrame,
    input_vars: list,
    target_col: str,
    seq_len: int,
    epochs: int,
    patience: int,
) -> dict:
    """
    Train a GRU on input_vars predicting target_col.
    Returns RMSE, MAE, R² and raw error array in original units.
    """
    cols   = list(set(input_vars + [target_col]))
    df_imp = _impute(df[cols])
    df_sc, scalers = _scale(df_imp, cols)

    split  = int(len(df_sc) * 0.8)
    train  = df_sc.iloc[:split]
    test   = df_sc.iloc[split:]

    X_tr, y_tr = _make_sequences(train[input_vars].values, train[[target_col]].values, seq_len)
    X_te, y_te = _make_sequences(test[input_vars].values,  test[[target_col]].values,  seq_len)

    if len(X_tr) < 10 or len(X_te) < 5:
        return {"RMSE": float("nan"), "MAE": float("nan"), "R2": float("nan"),
                "errors": np.array([]), "y_true": np.array([]), "y_pred": np.array([])}

    model = build_model("GRU", len(input_vars), 1, hidden_size=128, num_layers=3, dropout=0.2)
    model = train_deep_model(model, X_tr, y_tr, X_te, y_te,
                             epochs=epochs, patience=patience)

    preds_sc   = predict_deep(model, X_te)                      # (N, 1)
    y_true_orig = _inverse_col(y_te[:, 0], scalers[target_col])
    y_pred_orig = _inverse_col(preds_sc[:, 0], scalers[target_col])

    errors = y_true_orig - y_pred_orig
    return {
        "RMSE":   float(np.sqrt(mean_squared_error(y_true_orig, y_pred_orig))),
        "MAE":    float(mean_absolute_error(y_true_orig, y_pred_orig)),
        "R2":     float(r2_score(y_true_orig, y_pred_orig)),
        "errors": errors,
        "y_true": y_true_orig,
        "y_pred": y_pred_orig,
    }


def run_ablation_study(
    df: pd.DataFrame,
    input_vars: list,
    target_col: str,
    seq_len: int = 30,
    epochs: int = 100,
    patience: int = 15,
    progress_cb=None,
) -> dict:
    """
    Leave-one-out ablation: train baseline (all vars), then remove each
    variable one at a time and measure the performance change.

    Returns {
        "baseline":  metrics_dict,
        "ablations": {removed_var: metrics_dict},
    }
    """
    total  = 1 + len(input_vars)
    step   = 0
    result = {}

    if progress_cb:
        progress_cb(0.0, f"Training baseline ({len(input_vars)} variables)…")
    result["baseline"] = run_one_ablation(df, input_vars, target_col, seq_len, epochs, patience)
    step += 1

    result["ablations"] = {}
    for var in input_vars:
        remaining = [v for v in input_vars if v != var]
        if not remaining:
            continue
        if progress_cb:
            progress_cb(step / total, f"Ablation: removing {VAR_LABELS.get(var, var)}…")
        result["ablations"][var] = run_one_ablation(
            df, remaining, target_col, seq_len, epochs, patience
        )
        step += 1

    if progress_cb:
        progress_cb(1.0, "Ablation complete.")
    return result


# ── 6. Diebold-Mariano test ────────────────────────────────────────────────────

def diebold_mariano_test(e1: np.ndarray, e2: np.ndarray, h: int = 1) -> tuple[float, float]:
    """
    Two-sided DM test with Harvey-Leybourne-Newbold (1997) correction.

    e1, e2 : forecast errors (y_true − y_pred) for the two models.
    Loss differential d[t] = e1[t]² − e2[t]²
    Positive DM stat → model-1 errors (e1) are larger → model-1 is worse.

    When used as run_dm_tests(ablated_errors, baseline_errors):
        positive stat → ablated model is worse → removed variable was important.
    """
    e1, e2 = np.asarray(e1, float), np.asarray(e2, float)
    T = len(e1)
    d = e1**2 - e2**2
    d_bar = np.mean(d)

    # Newey-West long-run variance
    gamma0 = np.mean((d - d_bar) ** 2)
    gamma_k = sum(
        np.mean((d[k:] - d_bar) * (d[:T - k] - d_bar))
        for k in range(1, h)
    )
    var_d = (gamma0 + 2 * gamma_k) / T
    if var_d <= 0:
        return float("nan"), float("nan")

    dm = d_bar / np.sqrt(var_d)

    # HLN correction factor
    hlm_c = (T + 1 - 2 * h + max(h * (h - 1) / T, 0.0)) / T
    dm_hlm = dm * np.sqrt(max(hlm_c, 0.0))

    p = float(2 * stats.t.sf(abs(dm_hlm), df=T - 1))
    return float(dm_hlm), p


def run_dm_tests(ablation_results: dict) -> pd.DataFrame:
    """
    Compare each ablated model against the baseline via DM test.
    Positive ΔRMSE and positive DM stat both indicate the variable matters.
    """
    baseline = ablation_results["baseline"]
    rows     = []

    for var, res in ablation_results["ablations"].items():
        if len(res["errors"]) == 0 or len(baseline["errors"]) == 0:
            dm_stat, p_val = float("nan"), float("nan")
        else:
            dm_stat, p_val = diebold_mariano_test(res["errors"], baseline["errors"])

        rows.append({
            "variable": var,
            "Label":    VAR_LABELS.get(var, var),
            "ΔRMSE":    round(res["RMSE"] - baseline["RMSE"], 4),
            "ΔMAE":     round(res["MAE"]  - baseline["MAE"],  4),
            "ΔR²":      round(res["R2"]   - baseline["R2"],   4),
            "DM Stat":  round(dm_stat, 4) if not np.isnan(dm_stat) else float("nan"),
            "p-value":  round(p_val,   4) if not np.isnan(p_val)   else float("nan"),
        })

    return pd.DataFrame(rows).sort_values("ΔRMSE", ascending=False).reset_index(drop=True)


# ── 7. Friedman test ───────────────────────────────────────────────────────────

def run_friedman_test(ablation_results: dict, n_blocks: int = 10) -> tuple[float, float]:
    """
    Friedman test on temporal block-RMSE across all model configurations.
    Groups test errors into n_blocks temporal segments and tests whether
    median block-RMSE distributions differ across model subsets.
    """
    configs = {"Baseline": ablation_results["baseline"]["errors"]}
    for var, res in ablation_results["ablations"].items():
        configs[f"−{VAR_LABELS.get(var, var)}"] = res["errors"]

    T = min(len(e) for e in configs.values() if len(e) > 0)
    if T == 0:
        return float("nan"), float("nan")

    block_size    = max(1, T // n_blocks)
    actual_blocks = T // block_size
    if actual_blocks < 3:
        return float("nan"), float("nan")

    matrix = np.array([
        [
            np.sqrt(np.mean(errors[i * block_size:(i + 1) * block_size] ** 2))
            for errors in configs.values()
        ]
        for i in range(actual_blocks)
    ])   # (actual_blocks, n_configs)

    try:
        stat, p = stats.friedmanchisquare(*[matrix[:, j] for j in range(matrix.shape[1])])
        return float(stat), float(p)
    except Exception:
        return float("nan"), float("nan")


# ── 8. BH correction ──────────────────────────────────────────────────────────

def bh_correction(dm_df: pd.DataFrame, alpha: float = 0.05) -> pd.DataFrame:
    """Apply Benjamini-Hochberg FDR correction to the DM p-values."""
    dm_df   = dm_df.copy()
    pvals   = dm_df["p-value"].values
    valid   = ~np.isnan(pvals)
    adj_p   = np.full(len(pvals), float("nan"))
    rejected = np.zeros(len(pvals), dtype=bool)

    if valid.sum() > 0:
        rej, p_corr, _, _ = multipletests(pvals[valid], alpha=alpha, method="fdr_bh")
        adj_p[valid]    = p_corr
        rejected[valid] = rej

    dm_df["BH p-value"]   = np.round(adj_p, 4)
    dm_df["Significant?"] = rejected
    return dm_df


# ── 9. Conclusion ─────────────────────────────────────────────────────────────

def generate_conclusion(
    station_name: str,
    target_col: str,
    adf_df: pd.DataFrame,
    dm_bh_df: pd.DataFrame,
    friedman_result: tuple[float, float],
) -> str:
    """Return a markdown-formatted conclusion block from all analysis results."""
    target_label = VAR_LABELS.get(target_col, target_col)
    n_tested     = len(dm_bh_df)
    sig_mask     = dm_bh_df["Significant?"]
    sig_rows     = dm_bh_df[sig_mask]
    non_sig_rows = dm_bh_df[~sig_mask]

    top_vars     = dm_bh_df.sort_values("ΔRMSE", ascending=False)
    top1         = top_vars.iloc[0] if len(top_vars) > 0 else None

    non_stat     = adf_df[~adf_df["Stationary"]]["Variable"].tolist()
    ns_labels    = [VAR_LABELS.get(v, v) for v in non_stat]

    f_stat, f_p  = friedman_result
    f_str        = f"χ² = {f_stat:.3f}, p = {f_p:.4f}" if not np.isnan(f_stat) else "N/A"
    f_sig_word   = "**statistically significant**" if (not np.isnan(f_p) and f_p < 0.05) \
                   else "not statistically significant"

    lines = [
        f"### Conclusion — {station_name}",
        "",
        "**Research Question:** Which meteorological variables most significantly "
        "influence the predictive performance of GRU models in weather forecasting?",
        "",
        f"Of the **{n_tested} meteorological variables** tested for their influence on "
        f"**{target_label}** prediction at **{station_name}**, "
        f"**{len(sig_rows)}** showed a statistically significant impact on GRU forecast "
        f"accuracy after Benjamini-Hochberg FDR correction (α = 0.05).",
        "",
    ]

    if top1 is not None:
        bh_p_str = (
            f", BH p = {top1['BH p-value']:.4f}"
            if not np.isnan(top1["BH p-value"]) else ""
        )
        lines += [
            f"The **most influential variable** was **{top1['Label']}** "
            f"(ΔRMSE = {top1['ΔRMSE']:+.4f}{bh_p_str}). "
            "Removing it caused the largest degradation in GRU forecast accuracy.",
            "",
        ]

    if len(top_vars) >= 3:
        top3_names = [f"**{r['Label']}**" for _, r in top_vars.head(3).iterrows()]
        lines.append(f"**Top 3 most influential variables:** {', '.join(top3_names)}.")
        lines.append("")

    if len(sig_rows) > 0:
        sig_names = [f"**{r['Label']}**" for _, r in sig_rows.iterrows()]
        lines.append(
            f"✅ **Statistically significant** (BH-adjusted p < 0.05): "
            f"{', '.join(sig_names)}."
        )

    if len(non_sig_rows) > 0:
        ns_names = [r["Label"] for _, r in non_sig_rows.iterrows()]
        lines.append(
            f"⬜ **Not significant** (BH-adjusted p ≥ 0.05): "
            f"{', '.join(ns_names)}. "
            "Removing these variables did not significantly change accuracy."
        )

    lines += [
        "",
        f"The **Friedman test** found that performance differences across all "
        f"variable subsets were {f_sig_word} ({f_str}).",
        "",
    ]

    if ns_labels:
        verb = "was" if len(ns_labels) == 1 else "were"
        lines.append(
            f"⚠️ **Stationarity note:** {', '.join(ns_labels)} {verb} non-stationary "
            f"(ADF p ≥ 0.05) and {verb} first-differenced before analysis."
        )
        lines.append("")

    # Final recommendation
    lines.append("---")
    if len(sig_rows) > 0:
        rec = sig_rows.sort_values("ΔRMSE", ascending=False)
        rec_names = [r["Label"] for _, r in rec.head(5).iterrows()]
        lines += [
            "**Recommendation:**",
            f"For optimal GRU forecasting of **{target_label}** at **{station_name}**, "
            f"prioritize these variables as model inputs:",
            "",
            "\n".join(f"  {i+1}. {name}" for i, name in enumerate(rec_names)),
            "",
            "These variables demonstrated both the highest ablation impact and "
            "statistically significant contributions per the Diebold-Mariano test.",
        ]
    else:
        lines += [
            "**Recommendation:**",
            "No single variable showed a dominant, statistically significant influence. "
            "The full available variable set is recommended for robust GRU predictions.",
        ]

    return "\n".join(lines)


# ── 10. Combined Conclusion (all targets) ──────────────────────────────────────

def generate_combined_conclusion(
    station_name: str,
    adf_df: pd.DataFrame,
    per_target_dm_bh: dict,
    per_target_friedman: dict,
) -> str:
    """Return a markdown conclusion that aggregates results across all four targets."""
    n_targets = len(per_target_dm_bh)

    # Build combined importance table: variable → {label, rmse_sum, rmse_count, sig_count}
    combined: dict = {}
    for target, dm_bh in per_target_dm_bh.items():
        tgt_label = VAR_LABELS.get(target, target)
        for _, row in dm_bh.iterrows():
            var = row["variable"]
            if var not in combined:
                combined[var] = {
                    "Label": row["Label"],
                    "rmse_sum": 0.0,
                    "rmse_count": 0,
                    "sig_count": 0,
                    "sig_targets": [],
                }
            combined[var]["rmse_sum"]   += row["ΔRMSE"]
            combined[var]["rmse_count"] += 1
            if row["Significant?"]:
                combined[var]["sig_count"] += 1
                combined[var]["sig_targets"].append(tgt_label)

    rows_sorted = sorted(
        combined.items(),
        key=lambda kv: kv[1]["rmse_sum"] / max(kv[1]["rmse_count"], 1),
        reverse=True,
    )

    # Non-stationary variables
    non_stat  = adf_df[~adf_df["Stationary"]]["Variable"].tolist()
    ns_labels = [VAR_LABELS.get(v, v) for v in non_stat]

    target_labels_str = ", ".join(VAR_LABELS.get(t, t) for t in per_target_dm_bh)

    lines = [
        f"### Combined Conclusion — {station_name}",
        "",
        "**Research Question:** Which meteorological variables most significantly "
        "influence the predictive performance of GRU models in weather forecasting?",
        "",
        f"The analysis evaluated **{n_targets} forecast targets** "
        f"({target_labels_str}) using leave-one-out ablation, "
        "Diebold-Mariano tests (HLN-corrected), Friedman test, "
        "and Benjamini-Hochberg FDR correction (α = 0.05) at **{station_name}**.".replace(
            "{station_name}", station_name
        ),
        "",
    ]

    if rows_sorted:
        top_var, top_data = rows_sorted[0]
        avg_top = top_data["rmse_sum"] / max(top_data["rmse_count"], 1)
        lines += [
            f"**The most consistently influential variable was {top_data['Label']}** "
            f"(average ΔRMSE = {avg_top:+.4f} across all targets, "
            f"statistically significant for {top_data['sig_count']} of {n_targets} targets).",
            "",
        ]

    if len(rows_sorted) >= 3:
        top3_str = ", ".join(f"**{d['Label']}**" for _, d in rows_sorted[:3])
        lines.append(f"**Top 3 most influential variables** (by average ΔRMSE): {top3_str}.")
        lines.append("")

    # Per-target significance summary
    lines.append("**Significance summary per forecast target:**")
    lines.append("")
    for target, dm_bh in per_target_dm_bh.items():
        tgt_label = VAR_LABELS.get(target, target)
        sig_rows  = dm_bh[dm_bh["Significant?"]]
        f_stat, f_p = per_target_friedman[target]
        f_word = "significant" if not np.isnan(f_p) and f_p < 0.05 else "not significant"
        if len(sig_rows) > 0:
            names = ", ".join(f"**{r['Label']}**" for _, r in sig_rows.iterrows())
            lines.append(
                f"- **{tgt_label}:** {len(sig_rows)} significant variable(s) — "
                f"{names}. Friedman: {f_word}."
            )
        else:
            lines.append(
                f"- **{tgt_label}:** No variables were statistically significant "
                f"after BH correction. Friedman: {f_word}."
            )

    lines.append("")

    if ns_labels:
        verb = "was" if len(ns_labels) == 1 else "were"
        lines.append(
            f"⚠️ **Stationarity note:** {', '.join(ns_labels)} {verb} non-stationary "
            f"and {verb} first-differenced before analysis."
        )
        lines.append("")

    lines.append("---")

    sig_vars = [(var, data) for var, data in rows_sorted if data["sig_count"] > 0]
    if sig_vars:
        lines += [
            "**Overall Recommendation:**",
            f"For GRU weather forecasting at **{station_name}**, the following variables "
            "demonstrated statistically significant influence across one or more targets:",
            "",
        ]
        for i, (var, data) in enumerate(sig_vars[:5]):
            avg_rmse = data["rmse_sum"] / max(data["rmse_count"], 1)
            lines.append(
                f"  {i + 1}. **{data['Label']}** — "
                f"avg ΔRMSE = {avg_rmse:+.4f}, "
                f"significant for {data['sig_count']}/{n_targets} target(s)"
            )
        lines += [
            "",
            "These variables should be prioritized as GRU model inputs for robust "
            "multi-variable weather forecasting.",
        ]
    else:
        lines += [
            "**Overall Recommendation:**",
            "No variable showed consistent statistically significant influence across all targets. "
            "Use the full available variable set and consider regularization in the GRU model.",
        ]

    return "\n".join(lines)


# ── 11. Cross-Station Conclusion (both stations, all targets) ──────────────────

def generate_cross_station_conclusion(
    stations_data: dict,
) -> str:
    """
    Return a markdown conclusion aggregating results across all stations and targets.

    Parameters
    ----------
    stations_data : {station_name: {"adf_df": df,
                                    "per_target_dm_bh": {target: dm_bh_df},
                                    "per_target_friedman": {target: (f_stat, f_p)}}}
    """
    station_names = list(stations_data.keys())
    n_stations    = len(station_names)

    # Aggregate ΔRMSE and significance across all (station, target) combinations
    combined: dict = {}
    total_combinations = 0
    for stn, data in stations_data.items():
        for tgt, dm_bh in data["per_target_dm_bh"].items():
            total_combinations += 1
            tgt_label = VAR_LABELS.get(tgt, tgt)
            for _, row in dm_bh.iterrows():
                var = row["variable"]
                if var not in combined:
                    combined[var] = {
                        "Label":    row["Label"],
                        "rmse_vals": [],
                        "sig_count": 0,
                    }
                combined[var]["rmse_vals"].append(row["ΔRMSE"])
                if row["Significant?"]:
                    combined[var]["sig_count"] += 1

    rows_sorted = sorted(
        combined.items(),
        key=lambda kv: (
            np.mean(kv[1]["rmse_vals"]) if kv[1]["rmse_vals"] else 0.0
        ),
        reverse=True,
    )

    stations_str = " and ".join(f"**{s}**" for s in station_names)

    lines = [
        "### Cross-Station Combined Conclusion",
        "",
        "**Research Question:** Which meteorological variables most significantly "
        "influence the predictive performance of GRU models in weather forecasting?",
        "",
        f"Analysis was conducted across {stations_str}, evaluating **all four forecast "
        "targets** (Precipitation, Temperature, Wind Speed, Pressure) per station "
        "via leave-one-out ablation, Diebold-Mariano tests (HLN-corrected), "
        "Friedman test, and Benjamini-Hochberg FDR correction (α = 0.05). "
        f"Results aggregate **{total_combinations} target/station combinations**.",
        "",
    ]

    if rows_sorted:
        top_var, top_data = rows_sorted[0]
        avg_top = np.mean(top_data["rmse_vals"])
        lines += [
            f"**The most consistently influential variable across both stations and all "
            f"targets was {top_data['Label']}** "
            f"(average ΔRMSE = {avg_top:+.4f}, statistically significant in "
            f"{top_data['sig_count']} of {total_combinations} combinations).",
            "",
        ]

    if len(rows_sorted) >= 3:
        top3_str = ", ".join(f"**{d['Label']}**" for _, d in rows_sorted[:3])
        lines.append(
            f"**Top 3 most influential variables** "
            f"(by average ΔRMSE across all combinations): {top3_str}."
        )
        lines.append("")

    # Per-station significance summary
    lines.append("**Significance summary by station:**")
    lines.append("")
    for stn, data in stations_data.items():
        n_t = len(data["per_target_dm_bh"])
        sig_labels: set = set()
        for tgt, dm_bh in data["per_target_dm_bh"].items():
            for _, row in dm_bh[dm_bh["Significant?"]].iterrows():
                sig_labels.add(row["Label"])
        if sig_labels:
            names_str = ", ".join(f"**{v}**" for v in sorted(sig_labels))
            lines.append(
                f"- **{stn}:** {len(sig_labels)} unique variable(s) significant "
                f"across {n_t} target(s) — {names_str}."
            )
        else:
            lines.append(
                f"- **{stn}:** No variables were statistically significant "
                f"after BH correction across any target."
            )

    lines.append("")
    lines.append("---")

    sig_vars = [(var, data) for var, data in rows_sorted if data["sig_count"] > 0]
    if sig_vars:
        lines += [
            "**Overall Recommendation:**",
            f"For GRU weather forecasting at both stations, prioritize these variables:",
            "",
        ]
        for i, (var, data) in enumerate(sig_vars[:5]):
            avg_rmse = np.mean(data["rmse_vals"])
            lines.append(
                f"  {i + 1}. **{data['Label']}** — "
                f"avg ΔRMSE = {avg_rmse:+.4f}, "
                f"significant for {data['sig_count']}/{total_combinations} combination(s)"
            )
        lines += [
            "",
            "These variables demonstrated consistent, statistically significant influence "
            "on GRU forecast accuracy across multiple stations and forecast targets.",
        ]
    else:
        lines += [
            "**Overall Recommendation:**",
            "No variable showed consistent statistical significance across both stations. "
            "Results vary by location — use the full available variable set per station.",
        ]

    return "\n".join(lines)
