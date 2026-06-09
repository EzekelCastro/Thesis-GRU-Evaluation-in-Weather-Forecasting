"""
pages/2_Variable_Importance.py
Streamlit page — Variable Importance Analysis

Research question:
  "Which meteorological variables most significantly influence
   the predictive performance of GRU models in weather forecasting?"

Pipeline (both stations × all targets):
  Coverage → Stationarity → Correlation → Ablation → DM test
  → Friedman test → BH correction → Cross-Station Conclusion
"""

import os
import sys
import hashlib
import pickle
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime

from data_fetch import STATIONS
from feature_analysis import (
    VAR_LABELS,
    fetch_all_variables,
    filter_by_coverage,
    run_adf_tests,
    apply_stationarity,
    compute_correlation_matrix,
    run_ablation_study,
    run_dm_tests,
    run_friedman_test,
    bh_correction,
    generate_conclusion,
    generate_combined_conclusion,
    generate_cross_station_conclusion,
)

# ── Constants ──────────────────────────────────────────────────────────────────

_CACHE_DIR   = "cache"
_ALL_TARGETS = ["prcp", "temp", "wspd", "pres"]


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_key(cov: float, epochs: int, seq_len: int) -> str:
    s = f"both_stations|{cov:.2f}|{epochs}|{seq_len}"
    return "ablation_" + hashlib.sha1(s.encode()).hexdigest()[:12]


def _save_cache(key: str, data: dict) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(os.path.join(_CACHE_DIR, f"{key}.pkl"), "wb") as f:
        pickle.dump(data, f)


def _load_cache(key: str) -> dict | None:
    path = os.path.join(_CACHE_DIR, f"{key}.pkl")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 Variable Importance")
    st.divider()

    st.caption("Analysis runs for **both** Baguio City and Manila across all 4 forecast targets.")

    st.divider()
    st.subheader("Settings")

    coverage_pct = st.slider(
        "Min. Variable Coverage (%)", 50, 95, 70, step=5,
        help="Variables with fewer non-NaN values are excluded.",
    )
    seq_len = st.number_input("Sequence Length (days)", 15, 60, 30, step=5)
    epochs  = st.number_input(
        "Ablation Epochs", 30, 200, 100, step=10,
        help="Each ablation model trains for this many epochs (patience=15 early stop).",
    )

    st.divider()
    run_btn   = st.button("▶ Run Analysis", type="primary", use_container_width=True)
    clear_btn = st.button("🗑 Clear Cache", use_container_width=True)

    if clear_btn:
        removed = 0
        if os.path.exists(_CACHE_DIR):
            for fname in os.listdir(_CACHE_DIR):
                if fname.startswith("ablation_"):
                    os.remove(os.path.join(_CACHE_DIR, fname))
                    removed += 1
        st.success(f"Removed {removed} ablation cache file(s).")

# ── Page header ────────────────────────────────────────────────────────────────

st.title("📊 Variable Importance Analysis")
st.markdown(
    "> **Research Question:** Which meteorological variables most significantly "
    "influence the predictive performance of GRU models in weather forecasting?"
)
st.caption(
    "Both stations (Baguio City & Manila) × all 4 targets — "
    "Stationarity (ADF) → Correlation → Ablation → "
    "Diebold-Mariano → Friedman → BH FDR Correction → Cross-Station Conclusion"
)
st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────

tab_stat, tab_corr, tab_abl, tab_test, tab_conc = st.tabs([
    "① Stationarity",
    "② Correlation",
    "③ Ablation Study",
    "④ Statistical Tests",
    "⑤ Conclusion",
])

key = _cache_key(coverage_pct / 100, int(epochs), int(seq_len))

# ── Run analysis ───────────────────────────────────────────────────────────────

if run_btn:
    start_dt = datetime(2020, 1, 1)
    end_dt   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    all_stations_data: dict = {}

    with st.status("Running pipeline…", expanded=True) as status:

        for stn_name, stn_id in STATIONS.items():
            st.write(f"─── **{stn_name}** ({'Station ID: ' + str(stn_id)}) ───")

            # Step 1 — Fetch
            st.write(f"  📡 Fetching all Meteostat variables…")
            try:
                raw_df = fetch_all_variables(stn_id, start_dt, end_dt)
            except Exception as exc:
                st.error(f"Data fetch failed for {stn_name}: {exc}")
                st.stop()
            st.write(f"     Retrieved {len(raw_df):,} records, {raw_df.shape[1]} raw variables.")

            # Step 2 — Coverage filter
            st.write(f"  📋 Filtering by coverage (≥ {coverage_pct}%)…")
            filtered_df, coverage_df = filter_by_coverage(raw_df, coverage_pct / 100)
            kept_vars = filtered_df.columns.tolist()
            st.write(f"     Kept {len(kept_vars)} variable(s): {', '.join(kept_vars)}")

            targets = [t for t in _ALL_TARGETS if t in kept_vars]
            if not targets:
                st.error(
                    f"No forecast targets passed the coverage filter for {stn_name}. "
                    "Lower the threshold and retry."
                )
                st.stop()
            st.write(f"     Targets: {', '.join(VAR_LABELS.get(t, t) for t in targets)}")

            # Step 3 — ADF
            st.write("  📈 Stationarity tests (ADF)…")
            adf_df  = run_adf_tests(filtered_df)
            proc_df = apply_stationarity(filtered_df, adf_df)
            n_ns    = (~adf_df["Stationary"]).sum()
            st.write(f"     {n_ns} variable(s) first-differenced.")

            # Step 4 — Correlation
            st.write("  🔗 Spearman correlation matrix…")
            corr_df = compute_correlation_matrix(proc_df)

            # Step 5 — Ablation for all targets
            per_target_ablation: dict = {}
            per_target_dm_bh:    dict = {}
            per_target_friedman: dict = {}

            for t_idx, target in enumerate(targets):
                tgt_label = VAR_LABELS.get(target, target)
                st.write(
                    f"  🔬 [{t_idx + 1}/{len(targets)}] Ablation → **{tgt_label}** "
                    f"({len(kept_vars) + 1} models × up to {epochs} epochs)…"
                )
                prog_bar = st.progress(0.0, text=f"Initialising {tgt_label}…")

                def _prog(frac: float, msg: str, _pb=prog_bar) -> None:
                    _pb.progress(frac, text=msg)

                abl_res = run_ablation_study(
                    proc_df, kept_vars, target,
                    seq_len=int(seq_len), epochs=int(epochs), patience=15,
                    progress_cb=_prog,
                )
                prog_bar.progress(1.0, text=f"{tgt_label} ✓")

                dm_df    = run_dm_tests(abl_res)
                friedman = run_friedman_test(abl_res)
                dm_bh    = bh_correction(dm_df)

                per_target_ablation[target] = abl_res
                per_target_dm_bh[target]    = dm_bh
                per_target_friedman[target] = friedman

                n_sig = dm_bh["Significant?"].sum()
                st.write(f"     {tgt_label}: {n_sig} significant variable(s).")

            all_stations_data[stn_name] = {
                "targets":              targets,
                "coverage_df":          coverage_df,
                "filtered_df":          filtered_df,
                "adf_df":               adf_df,
                "corr_df":              corr_df,
                "per_target_ablation":  per_target_ablation,
                "per_target_dm_bh":     per_target_dm_bh,
                "per_target_friedman":  per_target_friedman,
            }

        _save_cache(key, {"stations_data": all_stations_data})
        status.update(label="Analysis complete ✓", state="complete", expanded=False)

# ── Load from cache ────────────────────────────────────────────────────────────

cached = _load_cache(key)

if cached is None:
    st.info(
        "Configure the settings in the sidebar and click **▶ Run Analysis** to begin.\n\n"
        "The analysis trains GRU ablation models for **both Baguio City and Manila** "
        "across **all 4 forecast targets**. Allow 40–120 minutes depending on epoch count."
    )
    st.stop()

stations_data   = cached["stations_data"]
station_names   = list(stations_data.keys())


# ── Helper: station selectbox shared across tabs ───────────────────────────────

def _station_select(tab_key: str) -> str:
    return st.selectbox(
        "Station:", station_names,
        format_func=lambda s: s,
        key=f"stn_{tab_key}",
    )


# ── Tab 1: Stationarity — both stations side-by-side ──────────────────────────

with tab_stat:
    st.subheader("Variable Coverage & Stationarity")

    cols = st.columns(len(station_names))
    for ci, stn in enumerate(station_names):
        d = stations_data[stn]
        with cols[ci]:
            st.markdown(f"### {stn}")

            st.markdown("**Variable Coverage**")
            cov_show = d["coverage_df"][["Variable", "Coverage (%)", "Kept"]].copy()
            st.dataframe(
                cov_show.style.applymap(
                    lambda v: "color: #27ae60; font-weight: bold" if v == "✓"
                              else "color: #e74c3c",
                    subset=["Kept"],
                ),
                use_container_width=True, hide_index=True,
            )

            st.markdown("**ADF Stationarity Test**")
            st.caption("p < 0.05 → stationary. Non-stationary → first-differenced.")
            adf_show = d["adf_df"][["Label", "ADF Stat", "p-value", "Stationary", "Action"]].copy()
            adf_show["Stationary"] = adf_show["Stationary"].map({True: "✓ Yes", False: "✗ No"})

            def _style_adf(df):
                styles = pd.DataFrame("", index=df.index, columns=df.columns)
                for i, row in df.iterrows():
                    bg = "#d4edda" if "Yes" in str(row["Stationary"]) else "#f8d7da"
                    styles.loc[i, :] = f"background-color: {bg}"
                return styles

            st.dataframe(
                adf_show.style.apply(_style_adf, axis=None),
                use_container_width=True, hide_index=True,
            )


# ── Tab 2: Correlation ─────────────────────────────────────────────────────────

with tab_corr:
    st.subheader("Spearman Correlation Matrix")
    st.caption(
        "Spearman rank correlation — robust to non-normal distributions (precipitation, wind)."
    )

    sel_stn_corr = _station_select("corr")
    d_corr = stations_data[sel_stn_corr]
    corr_df = d_corr["corr_df"]

    labels_raw  = corr_df.columns.tolist()
    labels_disp = [VAR_LABELS.get(c, c) for c in labels_raw]
    n = len(labels_raw)
    cell_sz = max(0.75, 6.5 / n)

    fig, ax = plt.subplots(figsize=(n * cell_sz + 2, n * cell_sz + 1))
    im = ax.imshow(corr_df.values, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
    plt.colorbar(im, ax=ax, shrink=0.8, label="Spearman ρ")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels_disp, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(labels_disp, fontsize=8)
    ax.set_title(f"Spearman Correlation — {sel_stn_corr}", fontweight="bold", pad=12)

    for i in range(n):
        for j in range(n):
            val = corr_df.values[i, j]
            clr = "white" if abs(val) >= 0.6 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=max(6, 8 - n // 3), color=clr)

    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    # 2×2 grid of ranked correlations with each target
    st.markdown("**Ranked Correlation with Each Forecast Target**")
    avail_targets = [t for t in d_corr["targets"] if t in corr_df.columns]
    if avail_targets:
        n_cols   = min(len(avail_targets), 2)
        grp_list = [avail_targets[i:i + n_cols] for i in range(0, len(avail_targets), n_cols)]
        for grp in grp_list:
            gcols = st.columns(len(grp))
            for ci, tgt in enumerate(grp):
                with gcols[ci]:
                    tgt_label = VAR_LABELS.get(tgt, tgt)
                    st.markdown(f"**{tgt_label}**")
                    tgt_corr = (
                        corr_df[tgt]
                        .drop(tgt, errors="ignore")
                        .rename("Spearman ρ")
                        .reset_index()
                        .rename(columns={"index": "Key"})
                    )
                    tgt_corr["Variable"]   = tgt_corr["Key"].map(lambda k: VAR_LABELS.get(k, k))
                    tgt_corr["|ρ|"]        = tgt_corr["Spearman ρ"].abs().round(3)
                    tgt_corr["Spearman ρ"] = tgt_corr["Spearman ρ"].round(3)
                    tgt_corr = (
                        tgt_corr[["Variable", "Spearman ρ", "|ρ|"]]
                        .sort_values("|ρ|", ascending=False)
                        .reset_index(drop=True)
                    )
                    st.dataframe(tgt_corr, use_container_width=True, hide_index=True)


# ── Tab 3: Ablation Study ──────────────────────────────────────────────────────

with tab_abl:
    st.subheader("Leave-One-Out Ablation Study")
    st.caption(
        "Each variable is removed from the GRU input and the model is retrained "
        "for **all 4 targets** at **both stations**. "
        "ΔRMSE = ablated − baseline. Larger positive ΔRMSE → more important variable."
    )

    sel_stn_abl = _station_select("abl")
    d_abl = stations_data[sel_stn_abl]
    _targets_abl = d_abl["targets"]
    per_dm_abl   = d_abl["per_target_dm_bh"]

    # ── Combined ΔRMSE heatmap ─────────────────────────────────────────────────
    st.markdown("#### Combined ΔRMSE Heatmap (all targets)")
    st.caption("Cell = ΔRMSE when that row variable is removed, for that column target.")

    all_vars = list(dict.fromkeys(
        row["variable"]
        for dm in per_dm_abl.values()
        for _, row in dm.iterrows()
    ))
    tgt_lbl_list = [VAR_LABELS.get(t, t) for t in _targets_abl]
    var_lbl_list = [VAR_LABELS.get(v, v) for v in all_vars]

    mat = np.full((len(all_vars), len(_targets_abl)), np.nan)
    for tj, tgt in enumerate(_targets_abl):
        if tgt not in per_dm_abl:
            continue
        dm = per_dm_abl[tgt]
        for vi, var in enumerate(all_vars):
            mask = dm["variable"] == var
            if mask.any():
                mat[vi, tj] = dm.loc[mask, "ΔRMSE"].values[0]

    abs_max = np.nanmax(np.abs(mat)) if not np.all(np.isnan(mat)) else 1.0
    fig_h, ax_h = plt.subplots(
        figsize=(len(_targets_abl) * 1.8 + 2, len(all_vars) * 0.55 + 1.5)
    )
    im_h = ax_h.imshow(mat, cmap="RdYlGn_r", vmin=-abs_max, vmax=abs_max, aspect="auto")
    plt.colorbar(im_h, ax=ax_h, shrink=0.8, label="ΔRMSE")
    ax_h.set_xticks(range(len(_targets_abl)))
    ax_h.set_yticks(range(len(all_vars)))
    ax_h.set_xticklabels(tgt_lbl_list, fontsize=9, fontweight="bold")
    ax_h.set_yticklabels(var_lbl_list, fontsize=8)
    ax_h.set_title(f"ΔRMSE Heatmap — {sel_stn_abl}", fontweight="bold", pad=10)

    for vi in range(len(all_vars)):
        for tj in range(len(_targets_abl)):
            v = mat[vi, tj]
            if not np.isnan(v):
                clr = "white" if abs(v) >= abs_max * 0.6 else "black"
                ax_h.text(tj, vi, f"{v:+.3f}", ha="center", va="center",
                          fontsize=7, color=clr)

    plt.tight_layout()
    st.pyplot(fig_h, use_container_width=True)
    plt.close(fig_h)

    st.divider()

    # ── Baseline metrics ───────────────────────────────────────────────────────
    st.markdown("#### Baseline GRU Metrics")
    bl_cols = st.columns(min(len(_targets_abl), 4))
    for ci, tgt in enumerate(_targets_abl):
        if tgt not in d_abl["per_target_ablation"]:
            continue
        bl = d_abl["per_target_ablation"][tgt]["baseline"]
        with bl_cols[ci % len(bl_cols)]:
            st.markdown(f"**{VAR_LABELS.get(tgt, tgt)}**")
            st.metric("RMSE", f"{bl['RMSE']:.4f}")
            st.metric("MAE",  f"{bl['MAE']:.4f}")
            st.metric("R²",   f"{bl['R2']:.4f}")

    st.divider()

    # ── Per-target bar chart ───────────────────────────────────────────────────
    st.markdown("#### Per-Target Ablation Detail")
    sel_tgt_abl = st.selectbox(
        "Forecast target:",
        _targets_abl,
        format_func=lambda t: VAR_LABELS.get(t, t),
        key="abl_tgt_select",
    )

    if sel_tgt_abl in per_dm_abl:
        dm_sel   = per_dm_abl[sel_tgt_abl]
        tgt_lbl2 = VAR_LABELS.get(sel_tgt_abl, sel_tgt_abl)

        plot_df  = dm_sel.sort_values("ΔRMSE", ascending=True)
        bar_lbls = plot_df["Label"].tolist()
        bar_vals = plot_df["ΔRMSE"].tolist()
        bar_clrs = ["#e74c3c" if v > 0 else "#3498db" for v in bar_vals]

        fig, ax = plt.subplots(figsize=(10, max(3.5, len(bar_lbls) * 0.65)))
        bars = ax.barh(bar_lbls, bar_vals, color=bar_clrs, edgecolor="white", linewidth=0.5)
        ax.axvline(0, color="black", linewidth=0.9)
        ax.set_xlabel("ΔRMSE  (ablated − baseline)", fontsize=10)
        ax.set_title(
            f"Variable Importance — {tgt_lbl2} @ {sel_stn_abl}", fontweight="bold"
        )
        ax.grid(True, axis="x", alpha=0.25, linestyle=":")

        for bar, val in zip(bars, bar_vals):
            offset = max(abs(max(bar_vals, default=0)), abs(min(bar_vals, default=0))) * 0.01
            ax.text(
                val + (offset if val >= 0 else -offset),
                bar.get_y() + bar.get_height() / 2,
                f"{val:+.4f}", va="center",
                ha="left" if val >= 0 else "right", fontsize=8,
            )

        plt.tight_layout()
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)

        st.markdown("**Detailed Ablation Metrics**")
        st.dataframe(
            dm_sel[["Label", "ΔRMSE", "ΔMAE", "ΔR²"]].style.background_gradient(
                subset=["ΔRMSE"], cmap="RdYlGn_r"
            ),
            use_container_width=True, hide_index=True,
        )


# ── Tab 4: Statistical Tests ───────────────────────────────────────────────────

with tab_test:
    st.subheader("Statistical Tests")

    sel_stn_test = _station_select("test")
    d_test = stations_data[sel_stn_test]

    # ── Friedman across all targets ────────────────────────────────────────────
    st.markdown(f"#### Friedman Test — {sel_stn_test} (all targets)")
    st.caption(
        "Tests whether variable-removal configurations produce different median "
        "block-RMSE. Significant → at least one variable substantially impacts accuracy."
    )
    fr_cols = st.columns(min(len(d_test["targets"]), 4))
    for ci, tgt in enumerate(d_test["targets"]):
        if tgt not in d_test["per_target_friedman"]:
            continue
        f_stat, f_p = d_test["per_target_friedman"][tgt]
        f_sig = not np.isnan(f_p) and f_p < 0.05
        with fr_cols[ci % len(fr_cols)]:
            st.markdown(f"**{VAR_LABELS.get(tgt, tgt)}**")
            st.metric("χ² Stat", f"{f_stat:.3f}" if not np.isnan(f_stat) else "N/A")
            st.metric("p-value",  f"{f_p:.4f}"   if not np.isnan(f_p)    else "N/A")
            st.metric("Result", "Significant ✓" if f_sig else "Not Sig. ✗")

    st.divider()

    # ── DM + BH for selected target ────────────────────────────────────────────
    st.markdown(f"#### Diebold-Mariano + BH Correction — {sel_stn_test}")
    st.caption(
        "H₀: removing the variable does not change accuracy.  "
        "BH p-value controls FDR at α = 0.05. Green = significant."
    )

    sel_tgt_test = st.selectbox(
        "Forecast target:",
        d_test["targets"],
        format_func=lambda t: VAR_LABELS.get(t, t),
        key="test_tgt_select",
    )

    if sel_tgt_test in d_test["per_target_dm_bh"]:
        dm_show = d_test["per_target_dm_bh"][sel_tgt_test][[
            "Label", "ΔRMSE", "DM Stat", "p-value", "BH p-value", "Significant?"
        ]].copy()
        dm_show["Significant?"] = dm_show["Significant?"].map({True: "Yes ✓", False: "No"})

        def _style_dm(df):
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            for i, row in df.iterrows():
                if row["Significant?"] == "Yes ✓":
                    styles.loc[i, :] = "background-color: #d4edda; font-weight: bold"
            return styles

        st.dataframe(
            dm_show.style.apply(_style_dm, axis=None),
            use_container_width=True, hide_index=True,
        )

        st.divider()
        st.markdown("#### p-value Comparison (raw vs BH-adjusted)")
        p_cmp = d_test["per_target_dm_bh"][sel_tgt_test][
            ["Label", "p-value", "BH p-value"]
        ].dropna().copy()
        if not p_cmp.empty:
            x = np.arange(len(p_cmp))
            fig, ax = plt.subplots(figsize=(max(6, len(p_cmp) * 0.9), 4))
            ax.bar(x - 0.2, p_cmp["p-value"],    width=0.38, label="Raw p",  color="#3498db", alpha=0.85)
            ax.bar(x + 0.2, p_cmp["BH p-value"], width=0.38, label="BH p",   color="#e67e22", alpha=0.85)
            ax.axhline(0.05, color="red", linewidth=1.2, linestyle="--", label="α = 0.05")
            ax.set_xticks(x)
            ax.set_xticklabels(p_cmp["Label"], rotation=30, ha="right", fontsize=8)
            ax.set_ylabel("p-value")
            ax.set_title(
                f"Raw vs BH-Corrected p-values — "
                f"{VAR_LABELS.get(sel_tgt_test, sel_tgt_test)} @ {sel_stn_test}",
                fontweight="bold",
            )
            ax.legend(fontsize=8)
            ax.grid(True, axis="y", alpha=0.25, linestyle=":")
            plt.tight_layout()
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)


# ── Tab 5: Conclusion ──────────────────────────────────────────────────────────

with tab_conc:
    st.subheader("Conclusion")

    # ── Cross-station combined importance chart ────────────────────────────────
    st.markdown("#### Overall Variable Importance (Average ΔRMSE — Both Stations × All Targets)")
    st.caption(
        "Average ΔRMSE across both stations and all 4 targets. "
        "Green = significant in ≥ 2 combinations. Yellow = 1. Gray = none."
    )

    combined_imp: dict = {}
    total_combos = 0
    for stn, data in stations_data.items():
        for tgt, dm_bh in data["per_target_dm_bh"].items():
            total_combos += 1
            for _, row in dm_bh.iterrows():
                var = row["variable"]
                if var not in combined_imp:
                    combined_imp[var] = {"Label": row["Label"], "vals": [], "sig": 0}
                combined_imp[var]["vals"].append(row["ΔRMSE"])
                if row["Significant?"]:
                    combined_imp[var]["sig"] += 1

    combined_list = sorted(
        [
            {"Variable": var, "Label": d["Label"],
             "Avg ΔRMSE": np.mean(d["vals"]), "Sig Count": d["sig"]}
            for var, d in combined_imp.items()
        ],
        key=lambda r: r["Avg ΔRMSE"],
        reverse=True,
    )

    if combined_list:
        clabels = [r["Label"] for r in combined_list]
        cvals   = [r["Avg ΔRMSE"] for r in combined_list]
        ccolors = [
            "#27ae60" if r["Sig Count"] >= 2 else
            "#f39c12" if r["Sig Count"] == 1 else
            "#bdc3c7"
            for r in combined_list
        ]

        fig, ax = plt.subplots(figsize=(11, max(3.5, len(clabels) * 0.65)))
        bars = ax.barh(clabels[::-1], cvals[::-1], color=ccolors[::-1],
                       edgecolor="white", linewidth=0.5)
        ax.axvline(0, color="black", linewidth=0.9)
        ax.set_xlabel("Average ΔRMSE (both stations × all targets)", fontsize=10)
        ax.set_title("Overall Variable Importance — Baguio City & Manila", fontweight="bold")
        ax.grid(True, axis="x", alpha=0.25, linestyle=":")

        offset = max(abs(v) for v in cvals) * 0.01 if cvals else 0.001
        for bar, val in zip(bars, cvals[::-1]):
            ax.text(
                val + (offset if val >= 0 else -offset),
                bar.get_y() + bar.get_height() / 2,
                f"{val:+.4f}", va="center",
                ha="left" if val >= 0 else "right", fontsize=8,
            )

        legend_handles = [
            mpatches.Patch(color="#27ae60", label="Significant ≥ 2 combinations"),
            mpatches.Patch(color="#f39c12", label="Significant 1 combination"),
            mpatches.Patch(color="#bdc3c7", label="Not significant"),
        ]
        ax.legend(handles=legend_handles, loc="lower right", fontsize=8)
        plt.tight_layout()
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)

    st.divider()

    # ── Cross-station conclusion markdown ──────────────────────────────────────
    cross_md = generate_cross_station_conclusion({
        stn: {
            "adf_df":               data["adf_df"],
            "per_target_dm_bh":     data["per_target_dm_bh"],
            "per_target_friedman":  data["per_target_friedman"],
        }
        for stn, data in stations_data.items()
    })
    st.markdown(cross_md)

    st.divider()

    # ── Per-station conclusions ────────────────────────────────────────────────
    st.markdown("#### Per-Station Breakdown")
    for stn, data in stations_data.items():
        with st.expander(f"Per-station details — {stn}"):
            stn_md = generate_combined_conclusion(
                stn,
                data["adf_df"],
                data["per_target_dm_bh"],
                data["per_target_friedman"],
            )
            st.markdown(stn_md)

            st.markdown("---")
            st.markdown("**Per-Target Details**")
            for tgt in data["targets"]:
                if tgt not in data["per_target_dm_bh"]:
                    continue
                tgt_lbl = VAR_LABELS.get(tgt, tgt)
                with st.expander(f"{tgt_lbl}"):
                    per_md = generate_conclusion(
                        stn, tgt,
                        data["adf_df"],
                        data["per_target_dm_bh"][tgt],
                        data["per_target_friedman"][tgt],
                    )
                    st.markdown(per_md)

    st.divider()

    # ── Download all results ───────────────────────────────────────────────────
    st.markdown("**Download Combined Results (both stations × all targets)**")
    dl_rows = []
    for stn, data in stations_data.items():
        for tgt in data["targets"]:
            if tgt not in data["per_target_dm_bh"]:
                continue
            tgt_lbl = VAR_LABELS.get(tgt, tgt)
            for _, row in data["per_target_dm_bh"][tgt].iterrows():
                dl_rows.append({
                    "Station":         stn,
                    "Target Variable": tgt_lbl,
                    "Input Variable":  row["Label"],
                    "ΔRMSE":           row["ΔRMSE"],
                    "ΔMAE":            row["ΔMAE"],
                    "ΔR²":             row["ΔR²"],
                    "DM Stat":         row["DM Stat"],
                    "p-value":         row["p-value"],
                    "BH p-value":      row["BH p-value"],
                    "Significant?":    row["Significant?"],
                })

    if dl_rows:
        st.download_button(
            "📥 Download CSV (all stations × all targets)",
            data=pd.DataFrame(dl_rows).to_csv(index=False).encode(),
            file_name="variable_importance_all_stations_all_targets.csv",
            mime="text/csv",
        )
