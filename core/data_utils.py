"""Data loading and cleaning helpers (lineage: Project 1, AI Programming Foundations).

Project 1 wrapped each cleaning step in a small documented function
(handle_missing_values, remove_irrelevant_columns) before any analysis. The same
habit is applied here to the public datasets: validate structure, coerce types,
and drop or fill missing values explicitly.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"


@lru_cache(maxsize=1)
def load_scenarios() -> dict:
    """Load the replayed scenarios built by scripts/build_scenarios.py and validate their keys."""
    with open(DATA_DIR / "scenarios.json", encoding="utf-8") as fh:
        data = json.load(fh)
    required = {"title", "expected_category", "k8s_observations", "logs", "metric"}
    for sid, sc in data.items():
        missing = required - set(sc)
        if missing:
            raise ValueError(f"scenario {sid} is missing keys: {sorted(missing)}")
    return data


def get_scenario(scenario_id: str) -> dict:
    scenarios = load_scenarios()
    if scenario_id not in scenarios:
        raise KeyError(f"unknown scenario '{scenario_id}'. Known: {sorted(scenarios)}")
    return scenarios[scenario_id]


def clean_metric_series(values) -> pd.Series:
    """Coerce to float and fill any missing samples by linear interpolation (edges forward/back filled)."""
    s = pd.to_numeric(pd.Series(list(values)), errors="coerce").astype("float64")
    return s.interpolate(limit_direction="both").ffill().bfill()


def load_nab_series(fname: str) -> pd.DataFrame:
    """Load one NAB series (timestamp,value), parse dates, sort, and drop duplicate timestamps."""
    df = pd.read_csv(RAW_DIR / "nab" / fname, parse_dates=["timestamp"])
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    df["value"] = clean_metric_series(df["value"])
    return df


def load_nab_windows() -> dict:
    with open(RAW_DIR / "nab" / "labels" / "combined_windows.json", encoding="utf-8") as fh:
        return json.load(fh)


def load_bgl() -> pd.DataFrame:
    """Load Loghub BGL_2k, keep the columns the classifier needs, and add a binary anomaly target."""
    df = pd.read_csv(RAW_DIR / "loghub" / "BGL_2k.log_structured.csv")
    df = df.dropna(subset=["Content"])[["LineId", "Label", "Level", "Component", "Content", "EventTemplate"]].copy()
    df["anomaly"] = (df["Label"] != "-").astype(int)
    return df.reset_index(drop=True)


def load_runbooks() -> pd.DataFrame:
    """Load the runbook knowledge base and drop rows with empty content."""
    df = pd.read_csv(DATA_DIR / "runbooks.csv")
    df = df.dropna(subset=["content"]).reset_index(drop=True)
    df["topic"] = df["topic"].str.strip().str.lower()
    return df
