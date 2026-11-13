"""Build data/scenarios.json by replaying public data onto eight Kubernetes incident scenarios.

    python scripts/build_scenarios.py      (after scripts/fetch_data.py)

Every observable value in a scenario comes from a public source:
* events / pod status strings   -> verbatim example output from kubernetes.io pages (data/k8s_doc_strings.csv);
                                   the build fails if a string is not found on its page
* container / node log lines    -> verbatim Loghub 2k lines (dataset name + LineId kept)
* metric time series            -> a real NAB series slice: 24 h before the first NAB-labelled anomaly
                                   point plus 2 h after it, with the NAB labels that fall in the slice
The only constructed element is the mapping (scenario name, Kubernetes failure type, which public
slice is attached to it). No values are generated or edited.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BASELINE_PTS, AFTER_PTS = 288, 24   # NAB series are 5-minute samples: 24 h baseline, 2 h after the label

# scenario -> (category label from the Kubernetes docs, NAB file, Loghub dataset, LineIds, title)
MAPPING = {
    "crashloop-app": ("crashloopbackoff", "ec2_request_latency_system_failure.csv", "Hadoop",
                      [1020, 1021], "Application pod in CrashLoopBackOff"),
    "oomkilled": ("oomkilled", "rds_cpu_utilization_cc0c53.csv", "Hadoop", [111, 113], "Container OOMKilled and restarting"),
    "pending-cpu": ("pending", "ec2_cpu_utilization_825cc2.csv", "OpenStack", [36], "Pod Pending: insufficient CPU"),
    "node-notready": ("node-notready", "machine_temperature_system_failure.csv", "BGL", None, "Worker node NotReady"),
    "dns-resolution": ("dns", "ec2_network_in_257a54.csv", "OpenSSH", [1, 15], "Cluster DNS resolution failures"),
    "hpa-not-scaling": ("hpa", "cpu_utilization_asg_misconfiguration.csv", "Hadoop", [111], "Autoscaler not scaling under CPU load"),
    "liveness-probe": ("probes", "elb_request_count_8c0756.csv", "Apache", None, "Liveness probe failures restarting pods"),
    "imagepull": ("imagepullbackoff", "ec2_cpu_utilization_c6585a.csv", "BGL", [362, 372], "Rollout stuck on ImagePullBackOff"),
}
# Loghub selections that are filters rather than fixed LineIds
FILTERS = {
    ("node-notready", "BGL"): lambda df: df[(df["Label"] != "-") & df["Component"].eq("KERNEL")].drop_duplicates("Label").head(4),
    ("liveness-probe", "Apache"): lambda df: df[df["Content"].str.contains("workerEnv in error state", regex=False)].head(3),
}
EXTRA_LOGS = {"dns-resolution": ("Thunderbird", lambda df: df[df["Content"].str.contains("failed to resolve", regex=False)].head(1))}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def doc_pages() -> dict:
    pages = {}
    for p in (RAW / "k8s_docs").glob("*.txt"):
        url, _, text = p.read_text(encoding="utf-8").partition("\n")
        pages[p.stem] = (url.strip(), norm(text))
    return pages


def loghub_lines(scenario: str, dataset: str, line_ids) -> list[dict]:
    df = pd.read_csv(RAW / "loghub" / f"{dataset}_2k.log_structured.csv")
    sel = FILTERS[(scenario, dataset)](df) if line_ids is None else df[df["LineId"].isin(line_ids)]
    rows = [{"text": r["Content"], "source": f"Loghub {dataset}_2k LineId {r['LineId']}",
             "level": str(r.get("Level", "")) if "Level" in r else "",
             "loghub_label": str(r["Label"]) if "Label" in r else ""} for _, r in sel.iterrows()]
    if scenario in EXTRA_LOGS:
        ds, fn = EXTRA_LOGS[scenario]
        d2 = pd.read_csv(RAW / "loghub" / f"{ds}_2k.log_structured.csv")
        rows += [{"text": r["Content"], "source": f"Loghub {ds}_2k LineId {r['LineId']}", "level": "",
                  "loghub_label": str(r.get("Label", ""))} for _, r in fn(d2).iterrows()]
    if not rows:
        raise ValueError(f"no Loghub lines selected for {scenario}")
    return rows


def nab_slice(fname: str) -> dict:
    df = pd.read_csv(RAW / "nab" / fname, parse_dates=["timestamp"])
    windows = json.loads((RAW / "nab" / "labels" / "combined_windows.json").read_text())
    points = json.loads((RAW / "nab" / "labels" / "combined_labels.json").read_text())
    key = next(k for k in points if k.endswith("/" + fname))
    pts = pd.to_datetime(points[key])
    if len(pts):
        anchor = int(df.index[df["timestamp"] >= pts[0]][0])
        start, end = max(0, anchor - BASELINE_PTS), anchor + AFTER_PTS
    else:   # NAB labels no anomaly in this file: use the last 26 h as a negative control
        end = len(df)
        start = end - BASELINE_PTS - AFTER_PTS
    sl = df.iloc[start:end]
    t0, t1 = sl["timestamp"].iloc[0], sl["timestamp"].iloc[-1]
    return {"nab_file": key, "metric": fname.removesuffix(".csv"),
            "timestamps": sl["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
            "values": [float(v) for v in sl["value"]],
            "nab_anomaly_points_in_slice": [str(p) for p in pts if t0 <= p <= t1],
            "nab_windows_overlapping": [w for w in windows[key] if pd.Timestamp(w[0]) <= t1 and pd.Timestamp(w[1]) >= t0],
            "baseline_points": min(BASELINE_PTS, len(sl) - AFTER_PTS)}


def main():
    pages = doc_pages()
    docs = pd.read_csv(ROOT / "data" / "k8s_doc_strings.csv")
    out = {}
    for sid, (cat, nab_file, logset, line_ids, title) in MAPPING.items():
        items = []
        for _, d in docs[docs["scenario"] == sid].iterrows():
            url, text = pages[d["doc_key"]]
            if norm(d["text"]) not in text:
                raise ValueError(f"{d['id']} not found verbatim on {url}")
            items.append({"id": d["id"], "kind": d["kind"], "text": norm(d["text"]), "source": url})
        out[sid] = {"title": title, "expected_category": cat,
                    "category_ground_truth_source": items[0]["source"],
                    "k8s_observations": items, "logs": loghub_lines(sid, logset, line_ids),
                    "metric": nab_slice(nab_file),
                    "replay_note": "Replayed public data mapped onto a Kubernetes scenario; not a live cluster."}
    (ROOT / "data" / "scenarios.json").write_text(json.dumps(out, indent=1))
    for sid, sc in out.items():
        m = sc["metric"]
        print(f"{sid:16s} {sc['expected_category']:17s} obs={len(sc['k8s_observations'])} logs={len(sc['logs'])} "
              f"metric={m['metric']} n={len(m['values'])} nab_points={len(m['nab_anomaly_points_in_slice'])}")


if __name__ == "__main__":
    main()
