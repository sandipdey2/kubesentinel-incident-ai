"""Statistical helpers (lineage: Project 2, Statistical Analysis).

Project 2 tested a difference in means with Welch's t-test
(scipy.stats.ttest_ind, equal_var=False). Here the same test compares a NAB
metric's 24-hour baseline with its most recent 2 hours, and a z-score against the
baseline flags anomalous samples. The SLO / error-budget arithmetic and the
burn-rate thresholds (14.4x, 6x, 1x) follow Beyer et al. (2016, 2018).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .data_utils import clean_metric_series

Z_THRESHOLD = 3.0
RECENT_POINTS = 24          # 2 hours of 5-minute samples
SAMPLE_MINUTES = 5
SLO_TARGET = 0.99           # demo policy: 99% of 5-minute samples inside normal bounds
SLO_WINDOW_DAYS = 30


def anomaly_score(values, baseline_points: int = 288, recent_points: int = RECENT_POINTS) -> dict:
    s = clean_metric_series(values)
    base, recent = s.iloc[:baseline_points], s.iloc[-recent_points:]
    mu, sd = float(base.mean()), float(base.std(ddof=1))
    sd = sd if sd > 1e-12 else 1e-12
    z = (recent - mu) / sd
    t_stat, p_val = stats.ttest_ind(recent, base, equal_var=False)
    return {"baseline_mean": round(mu, 3), "baseline_std": round(sd, 3), "recent_mean": round(float(recent.mean()), 3),
            "latest": round(float(s.iloc[-1]), 3), "max_abs_z_recent": round(float(z.abs().max()), 2),
            "z_recent_mean": round(float((recent.mean() - mu) / sd), 2),
            "samples_over_3sigma": int((z.abs() > Z_THRESHOLD).sum()), "recent_samples": int(recent_points),
            "welch_t": round(float(t_stat), 3), "p_value": float(f"{p_val:.3g}"),
            "anomalous": bool((z.abs() > Z_THRESHOLD).sum() > 0 and p_val < 0.01)}


def error_budget(bad_samples: int, total_samples: int = RECENT_POINTS, slo_target: float = SLO_TARGET,
                 window_days: int = SLO_WINDOW_DAYS) -> dict:
    """Budget used by the observed bad samples and the burn rate over the recent window."""
    budget_min = (1 - slo_target) * window_days * 24 * 60
    bad_min = bad_samples * SAMPLE_MINUTES
    bad_fraction = bad_samples / total_samples if total_samples else 0.0
    burn = bad_fraction / (1 - slo_target)
    return {"slo_target": slo_target, "window_days": window_days, "budget_minutes": round(budget_min, 1),
            "bad_minutes_observed": bad_min, "budget_used_pct": round(100 * bad_min / budget_min, 2),
            "burn_rate_recent_2h": round(burn, 2), "severity_by_burn_rate": severity_from_burn(burn)}


def severity_from_burn(burn: float) -> str:
    """KubeSentinel policy mapping of burn rate to severity, using the Site Reliability Workbook thresholds."""
    if burn >= 14.4:
        return "SEV1"
    if burn >= 6:
        return "SEV2"
    if burn >= 1:
        return "SEV3"
    return "SEV4"


def rolling_zscore_detector(values: pd.Series, window: int = 288, threshold: float = Z_THRESHOLD) -> pd.Series:
    """Boolean Series: |value - trailing mean| / trailing std > threshold (trailing window excludes the point)."""
    mu = values.shift(1).rolling(window, min_periods=window).mean()
    sd = values.shift(1).rolling(window, min_periods=window).std().replace(0, np.nan)
    return ((values - mu).abs() / sd > threshold).fillna(False)


def evaluate_detector_on_nab(series: dict, windows: dict, window: int = 288, threshold: float = Z_THRESHOLD) -> pd.DataFrame:
    """Per-file window recall and detection precision of the z-score detector against NAB labelled windows."""
    rows = []
    for key, df in series.items():
        det = rolling_zscore_detector(df["value"], window, threshold)
        wins = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in windows[key]]
        in_win = np.zeros(len(df), dtype=bool)
        hit = 0
        for a, b in wins:
            m = (df["timestamp"] >= a) & (df["timestamp"] <= b)
            in_win |= m.to_numpy()
            hit += int((det & m).any())
        n_det = int(det.sum())
        rows.append({"series": key, "labelled_windows": len(wins), "windows_detected": hit,
                     "detections": n_det, "detections_in_windows": int((det.to_numpy() & in_win).sum())})
    out = pd.DataFrame(rows)
    out["window_recall"] = (out["windows_detected"] / out["labelled_windows"].replace(0, np.nan)).round(3)
    out["detection_precision"] = (out["detections_in_windows"] / out["detections"].replace(0, np.nan)).round(3)
    return out
