"""KubeSentinel MCP server (official `mcp` Python SDK, FastMCP, stdio transport).

The app launches this file as a subprocess (`sys.executable mcp_server/k8s_mcp_server.py`)
and talks to it over stdin/stdout with the Model Context Protocol (initialize,
tools/list, tools/call). The protocol and transport are real MCP.

The cluster is NOT live. Each tool replays public data for the scenario named in
the KS_SCENARIO environment variable (data/scenarios.json): verbatim example
output from kubernetes.io pages, verbatim Loghub log lines, and a real NAB metric
slice. Swapping these handlers for Kubernetes API calls would not change the client.

Every tool is read-only. There is deliberately no tool that changes cluster state.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from core.data_utils import get_scenario  # noqa: E402
from core.models import get_models  # noqa: E402
from core.rag import get_index  # noqa: E402
from core.stats import anomaly_score as _anomaly, error_budget  # noqa: E402

mcp = FastMCP("kubesentinel-k8s", log_level="WARNING")
SCENARIO_ID = os.environ.get("KS_SCENARIO", "crashloop-app")


def _sc() -> dict:
    return get_scenario(SCENARIO_ID)


def _j(obj) -> str:
    return json.dumps(obj, indent=1, default=str)


def _obs(*kinds) -> list[dict]:
    return [{"text": o["text"], "source": o["source"]} for o in _sc()["k8s_observations"] if o["kind"] in kinds]


@mcp.tool()
def get_cluster_overview() -> str:
    """Start here. Alert line, observation counts, the attached metric, and a note that the cluster is a replay."""
    sc = _sc()
    obs = sc["k8s_observations"]
    return _j({"scenario": SCENARIO_ID, "alert": obs[0]["text"], "observations": len(obs), "log_lines": len(sc["logs"]),
               "metric": sc["metric"]["metric"], "metric_points": len(sc["metric"]["values"]),
               "data_note": sc["replay_note"]})


@mcp.tool()
def get_pod_status() -> str:
    """Pod / node status lines (kubectl get output) for the incident."""
    return _j(_obs("status") or {"message": "no status lines recorded for this scenario"})


@mcp.tool()
def get_events() -> str:
    """Kubernetes events and node conditions (kubectl describe output) for the incident."""
    return _j(_obs("event", "condition") or {"message": "no events recorded for this scenario"})


@mcp.tool()
def get_reference_notes() -> str:
    """Documentation notes attached to the scenario (context, not live observations)."""
    return _j(_obs("excerpt") or {"message": "no reference notes for this scenario"})


@mcp.tool()
def get_pod_logs(tail: int = 20) -> str:
    """Recent log lines from the affected workload (raw text; may contain hostnames or IP addresses)."""
    sc = _sc()
    lines = [{"text": o["text"], "source": o["source"]} for o in sc["k8s_observations"] if o["kind"] == "log"]
    lines += [{"text": l["text"], "source": l["source"]} for l in sc["logs"]]
    return _j(lines[-max(1, min(tail, 200)):])


@mcp.tool()
def get_metric_summary() -> str:
    """Name, source and time range of the attached metric plus its last 12 samples (5-minute resolution)."""
    m = _sc()["metric"]
    return _j({"metric": m["metric"], "source": f"NAB {m['nab_file']}", "start": m["timestamps"][0], "end": m["timestamps"][-1],
               "points": len(m["values"]), "last_12": [round(v, 3) for v in m["values"][-12:]]})


@mcp.tool()
def anomaly_score() -> str:
    """z-scores of the last 2 h of the metric against its 24 h baseline, plus Welch's t-test (baseline vs recent)."""
    m = _sc()["metric"]
    return _j({"metric": m["metric"], **_anomaly(m["values"], baseline_points=m["baseline_points"])})


@mcp.tool()
def calculate_error_budget() -> str:
    """SLO error-budget use and burn rate, counting recent samples beyond 3 sigma as bad (SLO 99%, 30 days)."""
    m = _sc()["metric"]
    a = _anomaly(m["values"], baseline_points=m["baseline_points"])
    return _j({"metric": m["metric"], **error_budget(a["samples_over_3sigma"], a["recent_samples"])})


@mcp.tool()
def classify_metric_window() -> str:
    """Logistic-regression probability that the latest 1 h metric window is anomalous (trained on NAB labels)."""
    m = _sc()["metric"]
    r = get_models().report["metric_window"]
    return _j({"metric": m["metric"], **get_models().score_metric(m["values"], m["baseline_points"]),
               "model_test_f1": r["f1"], "reliability_note": "low held-out F1 on unseen series; treat as a weak signal"})


@mcp.tool()
def classify_log_lines() -> str:
    """Score each recent log line with the log-anomaly classifier trained on Loghub BGL; highest first."""
    sc = _sc()
    scored = get_models().score_log_lines([l["text"] for l in sc["logs"]])
    for row, l in zip(scored, sc["logs"]):
        row["source"] = l["source"]
    return _j(sorted(scored, key=lambda r: -r["anomaly_prob"]))


@mcp.tool()
def search_runbooks(query: str, k: int = 3) -> str:
    """TF-IDF search over Kubernetes documentation excerpts. Returns runbook id, title, excerpt, source URL."""
    return _j(get_index().search(query, k=max(1, min(k, 5))))


if __name__ == "__main__":
    mcp.run(transport="stdio")
