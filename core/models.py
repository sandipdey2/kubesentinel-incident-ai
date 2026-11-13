"""Classical ML models trained on public data and exposed to agents through MCP tools.

* Log-anomaly text classifier (lineage: Project 4, IMDB sentiment LSTM).
  Project 4 treated a review as a token sequence and learned a binary label.
  Here a log line is the text and the Loghub BGL_2k alert label (Label != "-")
  is the binary target (He et al., 2023). TF-IDF + LogisticRegression is used
  instead of an LSTM: 2,000 short lines are too few for a 1.1M-parameter LSTM like
  Project 4's, and PyTorch would add a large dependency to the Streamlit Cloud image.
* Metric-window classifier (lineage: Project 3, breast-cancer classification).
  Same workflow as Project 3: numeric features, StandardScaler, LogisticRegression,
  held-out test set, accuracy / precision / recall / F1 / confusion matrix. Rows
  are 1-hour windows of NAB series; the label is whether the window lies inside a
  NAB labelled anomaly window (Lavin & Ahmad, 2015). The split is by series
  (GroupShuffleSplit) so test series are never seen in training.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .data_utils import RAW_DIR, clean_metric_series, load_bgl, load_nab_series, load_nab_windows

SEED = 42
WINDOW = 12        # 1 hour of 5-minute samples
HISTORY = 288      # 24 hours of trailing history
WINDOW_FEATURES = ["z_mean", "z_max", "std_ratio", "slope_z", "range_z"]


def _metrics(y_true, y_pred) -> dict:
    return {"accuracy": round(accuracy_score(y_true, y_pred), 4),
            "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
            "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
            "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist()}


def _slog(x: float) -> float:
    """Signed log1p: keeps the sign, compresses the very large z-scores seen on near-flat series."""
    return float(np.sign(x) * np.log1p(abs(x)))


def window_features(hist: np.ndarray, win: np.ndarray) -> dict:
    mu, sd = float(hist.mean()), float(hist.std(ddof=1))
    sd = max(sd, 0.01 * abs(mu), 1e-6)    # floor so flat baselines do not produce infinite z-scores
    slope = np.polyfit(np.arange(len(win)), win, 1)[0] if len(win) > 1 else 0.0
    return {"z_mean": _slog((win.mean() - mu) / sd), "z_max": _slog(float(np.abs(win - mu).max() / sd)),
            "std_ratio": _slog(float(win.std(ddof=1) / sd) if len(win) > 1 else 0.0),
            "slope_z": _slog(float(slope * len(win) / sd)), "range_z": _slog(float((win.max() - win.min()) / sd))}


def build_window_dataset() -> pd.DataFrame:
    windows = load_nab_windows()
    rows = []
    for path in sorted((RAW_DIR / "nab").glob("*.csv")):
        key = next(k for k in windows if k.endswith("/" + path.name))
        df = load_nab_series(path.name)
        v, ts = df["value"].to_numpy(), df["timestamp"]
        spans = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in windows[key]]
        for start in range(HISTORY, len(df) - WINDOW + 1, WINDOW):
            mid = ts.iloc[start + WINDOW // 2]
            feats = window_features(v[start - HISTORY:start], v[start:start + WINDOW])
            rows.append({"series": key, "start": ts.iloc[start], **feats,
                         "label": int(any(a <= mid <= b for a, b in spans))})
    return pd.DataFrame(rows)


class IncidentModels:
    def __init__(self):
        self.report: dict = {}
        # --- log-anomaly text classifier on Loghub BGL_2k ---
        bgl = load_bgl()
        X_tr, X_te, y_tr, y_te = train_test_split(bgl["Content"], bgl["anomaly"], test_size=0.25,
                                                  stratify=bgl["anomaly"], random_state=SEED)
        self.log_model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), token_pattern=r"[A-Za-z][A-Za-z_]+", sublinear_tf=True),
                                       LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED))
        self.log_model.fit(X_tr, y_tr)
        self.report["log_anomaly"] = {**_metrics(y_te, self.log_model.predict(X_te)), "dataset": "Loghub BGL_2k",
                                      "n_train": len(X_tr), "n_test": len(X_te), "positives_total": int(bgl["anomaly"].sum())}
        # --- metric-window classifier on NAB ---
        wd = build_window_dataset()
        gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=SEED)
        tr_idx, te_idx = next(gss.split(wd, wd["label"], groups=wd["series"]))
        tr, te = wd.iloc[tr_idx], wd.iloc[te_idx]
        self.window_model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED))
        self.window_model.fit(tr[WINDOW_FEATURES], tr["label"])
        self.report["metric_window"] = {**_metrics(te["label"], self.window_model.predict(te[WINDOW_FEATURES])),
                                        "dataset": "NAB realAWSCloudwatch + realKnownCause (20 series)",
                                        "n_train": len(tr), "n_test": len(te),
                                        "test_series": sorted(te["series"].unique().tolist()),
                                        "positive_rate_train": round(float(tr["label"].mean()), 3)}
        self.window_data = wd

    def score_log_lines(self, lines: list[str]) -> list[dict]:
        if not lines:
            return []
        probs = self.log_model.predict_proba(lines)[:, 1]
        return [{"line": l, "anomaly_prob": round(float(p), 3)} for l, p in zip(lines, probs)]

    def score_metric(self, values, baseline_points: int = HISTORY) -> dict:
        s = clean_metric_series(values).to_numpy()
        hist, win = s[:baseline_points], s[-WINDOW:]
        feats = window_features(hist, win)
        p = float(self.window_model.predict_proba(pd.DataFrame([feats])[WINDOW_FEATURES])[0, 1])
        return {"window_anomaly_prob": round(p, 3), "features": {k: round(float(v), 3) for k, v in feats.items()}}


@lru_cache(maxsize=1)
def get_models() -> IncidentModels:
    return IncidentModels()
