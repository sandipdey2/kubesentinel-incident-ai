# Data sources

**Repository:** https://github.com/sandipdey2/kubesentinel-incident-ai

KubeSentinel uses **public data only**. There is no synthetic data generator and no invented telemetry.
Everything under `data/raw/` was downloaded by `scripts/fetch_data.py`; `data/runbooks.csv` and
`data/scenarios.json` are derived from it deterministically by `scripts/build_runbooks.py` and
`scripts/build_scenarios.py`, and both builders fail if a copied string cannot be found verbatim in its source.

| Data | Upstream | Subset committed | Licence / terms | Used for |
|---|---|---|---|---|
| Loghub 2k structured logs: BGL, Hadoop, OpenStack, Thunderbird, OpenSSH, Apache | https://github.com/logpai/loghub (`<System>/<System>_2k.log_structured.csv`) | the six 2,000-line sample files, unchanged (`data/raw/loghub/`) | Loghub licence: free for research/academic use, and any use or redistribution must refer to https://github.com/logpai/loghub | BGL `Label` column trains the log-anomaly classifier; verbatim lines (with LineId) are replayed as scenario logs |
| Numenta Anomaly Benchmark (NAB) | https://github.com/numenta/NAB (`data/realAWSCloudwatch/*`, `data/realKnownCause/*`, `labels/combined_windows.json`, `labels/combined_labels.json`) | 17 realAWSCloudwatch series + 3 realKnownCause series + both label files, unchanged (`data/raw/nab/`) | MIT licence (NAB repository `LICENSE.txt`, © Numenta Inc.) | metric-window classifier, z-score detector evaluation, and each scenario's metric slice |
| Kubernetes documentation | https://kubernetes.io/docs/ (27 pages, URLs in `scripts/fetch_data.py`) | page text (`data/raw/k8s_docs/*.txt`, first line = URL) | CC BY 4.0, © The Kubernetes Authors | 29 runbooks of verbatim excerpts (`data/runbooks.csv`) and the example `kubectl` output strings in each scenario (`data/k8s_doc_strings.csv`) |

## How the subsets were taken
* **Loghub**: the official 2k samples, not modified. Labels: BGL `Label` is `-` for normal lines and an alert type (e.g. `KERNDTLB`) otherwise; KubeSentinel's target is `anomaly = Label != "-"` (143 of 2,000 lines).
* **NAB**: whole series files. Window labels come from `combined_windows.json`, point labels from `combined_labels.json`.
  A scenario slice is the 288 samples (24 h) before the first labelled anomaly point plus the 24 samples (2 h) from that point on.
  `ec2_cpu_utilization_c6585a` has no labelled anomaly, so its last 26 h are used as a negative control (imagepull scenario).
* **Kubernetes docs**: HTML converted to text by `scripts/fetch_data.py`. The runbook column `kubesentinel_policy` is **not** from the docs. It is this project's own approval rule.

## What is constructed (the only non-public element)
The **mapping**: which Kubernetes failure type a scenario represents, and which public log lines and metric slice are attached to it
(`MAPPING` in `scripts/build_scenarios.py`). For example, the `hpa-not-scaling` scenario attaches NAB's
`cpu_utilization_asg_misconfiguration` series, whose known cause is an autoscaling-group misconfiguration, to the HPA documentation's
statement that the metrics API comes from Metrics Server. The log lines and metrics were **not** recorded from the Kubernetes clusters in the
docs. They are replayed alongside them, so agreement between them is weak by construction. The evaluation reports this.
No numbers, events, or log lines were generated or edited.

## Ground truth used in evaluation
* Scenario failure category: the Kubernetes documentation page the scenario's observations were copied from.
* Metric anomaly: NAB labels.
* Log anomaly: Loghub BGL labels.
* Severity has **no** public ground truth. It comes from a documented policy rule (burn-rate thresholds from the Site Reliability Workbook) and is not scored as accuracy.

## Citations (APA 7)
* Zhu, J., He, S., He, P., Liu, J., & Lyu, M. R. (2023). Loghub: A large collection of system log datasets for AI-driven log analytics. In *2023 IEEE 34th International Symposium on Software Reliability Engineering (ISSRE)* (pp. 355–366). IEEE. https://doi.org/10.1109/ISSRE59848.2023.00071
* Lavin, A., & Ahmad, S. (2015). Evaluating real-time anomaly detection algorithms: The Numenta Anomaly Benchmark. In *2015 IEEE 14th International Conference on Machine Learning and Applications (ICMLA)* (pp. 38–44). IEEE. https://doi.org/10.1109/ICMLA.2015.141
* The Kubernetes Authors. (n.d.). *Kubernetes documentation*. Retrieved November 12, 2026, from https://kubernetes.io/docs/ (CC BY 4.0)
