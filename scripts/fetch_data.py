"""Download the public dataset subsets used by KubeSentinel into data/raw/.

    python scripts/fetch_data.py

Sources (see DATA_SOURCES.md for licences and citations):
* Loghub 2k structured log samples   https://github.com/logpai/loghub
* Numenta Anomaly Benchmark (NAB)     https://github.com/numenta/NAB
* Kubernetes documentation pages      https://kubernetes.io/docs/ (CC BY 4.0)
The committed copies in data/raw/ were produced by this script; re-running it
re-downloads the same upstream files.
"""
from __future__ import annotations

import html
import re
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
LOGHUB = "https://raw.githubusercontent.com/logpai/loghub/master/{0}/{0}_2k.log_structured.csv"
LOGHUB_SETS = ["BGL", "Hadoop", "OpenStack", "Thunderbird", "OpenSSH", "Apache"]
NAB = "https://raw.githubusercontent.com/numenta/NAB/master/"
NAB_FILES = [f"realAWSCloudwatch/{f}.csv" for f in [
    "ec2_cpu_utilization_24ae8d", "ec2_cpu_utilization_53ea38", "ec2_cpu_utilization_5f5533", "ec2_cpu_utilization_77c1ca",
    "ec2_cpu_utilization_825cc2", "ec2_cpu_utilization_ac20cd", "ec2_cpu_utilization_c6585a", "ec2_cpu_utilization_fe7f93",
    "ec2_disk_write_bytes_1ef3de", "ec2_disk_write_bytes_c0d644", "ec2_network_in_257a54", "ec2_network_in_5abac7",
    "elb_request_count_8c0756", "grok_asg_anomaly", "iio_us-east-1_i-a2eb1cd9_NetworkIn", "rds_cpu_utilization_cc0c53",
    "rds_cpu_utilization_e47b3b"]] + [f"realKnownCause/{f}.csv" for f in [
    "cpu_utilization_asg_misconfiguration", "ec2_request_latency_system_failure", "machine_temperature_system_failure"]]
NAB_LABELS = ["labels/combined_windows.json", "labels/combined_labels.json"]
K8S_DOCS = {
    "assign-memory": "https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/",
    "assign-cpu": "https://kubernetes.io/docs/tasks/configure-pod-container/assign-cpu-resource/",
    "probes": "https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
    "dns": "https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/",
    "debug-pods": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/",
    "debug-running-pod": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/",
    "term-reason": "https://kubernetes.io/docs/tasks/debug/debug-application/determine-reason-pod-failure/",
    "hpa": "https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/",
    "debug-cluster": "https://kubernetes.io/docs/tasks/debug/debug-cluster/",
    "nodes": "https://kubernetes.io/docs/concepts/architecture/nodes/",
    "pressure": "https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/",
    "pod-lifecycle": "https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/",
    "images": "https://kubernetes.io/docs/concepts/containers/images/",
    "private-reg": "https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/",
    "debug-service": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/",
    "pv": "https://kubernetes.io/docs/concepts/storage/persistent-volumes/",
    "storage-classes": "https://kubernetes.io/docs/concepts/storage/storage-classes/",
    "taints": "https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/",
    "assign-pod-node": "https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/",
    "resources": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
    "kubeadm-certs": "https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/",
    "ingress": "https://kubernetes.io/docs/concepts/services-networking/ingress/",
    "secret": "https://kubernetes.io/docs/concepts/configuration/secret/",
    "configmap": "https://kubernetes.io/docs/concepts/configuration/configmap/",
    "deployment": "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/",
    "drain": "https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/",
    "disruptions": "https://kubernetes.io/docs/concepts/workloads/pods/disruptions/",
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kubesentinel-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def html_to_text(page: str) -> str:
    m = re.search(r'<div class="td-content">(.*?)<div class="d-print-none', page, re.S)
    body = m.group(1) if m else page
    body = re.sub(r"<(script|style).*?</\1>", "", body, flags=re.S)
    body = re.sub(r"<br\s*/?>|</(p|div|li|h\d|pre|tr)>", "\n", body)
    text = html.unescape(re.sub(r"<[^>]+>", "", body))
    return re.sub(r"\n\s*\n+", "\n", text)


def main():
    for sub in ("loghub", "nab", "nab/labels", "k8s_docs"):
        (RAW / sub).mkdir(parents=True, exist_ok=True)
    for name in LOGHUB_SETS:
        (RAW / "loghub" / f"{name}_2k.log_structured.csv").write_bytes(_get(LOGHUB.format(name)))
    for f in NAB_FILES:
        (RAW / "nab" / Path(f).name).write_bytes(_get(NAB + "data/" + f))
    for f in NAB_LABELS:
        (RAW / "nab" / "labels" / Path(f).name).write_bytes(_get(NAB + f))
    for key, url in K8S_DOCS.items():
        (RAW / "k8s_docs" / f"{key}.txt").write_text(url + "\n" + html_to_text(_get(url).decode("utf-8")), encoding="utf-8")
    print("downloaded", len(LOGHUB_SETS), "Loghub files,", len(NAB_FILES), "NAB series,", len(K8S_DOCS), "Kubernetes doc pages")


if __name__ == "__main__":
    main()
