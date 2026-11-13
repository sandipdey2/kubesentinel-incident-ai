"""Input and output guardrails.

Input side:  prompt-injection patterns, out-of-scope requests, secret/PII redaction.
Output side: every proposed command is classified READ / WRITE / DESTRUCTIVE.
DESTRUCTIVE commands are removed from the plan; WRITE commands are kept but
marked requires_approval=True. KubeSentinel never executes any command.
These are deterministic regex rules, chosen so the safety layer is testable
and cannot be talked out of its decision by the LLM (Greshake et al., 2023).
"""
from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (the |all )?(system|previous) (prompt|instructions)",
    r"(reveal|print|show|repeat) (me )?(your|the) (system prompt|instructions|hidden prompt)",
    r"you are now (dan|in developer mode|unrestricted)",
    r"jailbreak", r"act as (an? )?(unfiltered|unrestricted)",
    r"(print|reveal|show|dump|echo).{0,30}(api[_ -]?key|openai_api_key|secret key|token)",
]

K8S_TERMS = [
    "kubernetes", "k8s", "kubectl", "pod", "pods", "node", "nodes", "cluster", "deployment", "namespace", "service",
    "container", "crash", "crashloop", "oom", "memory", "cpu", "image", "pull", "pending", "schedul", "dns", "coredns",
    "hpa", "autoscal", "scale", "scaling", "pvc", "volume", "storage", "cert", "tls", "ssl", "x509", "ingress", "probe",
    "liveness", "readiness", "restart", "rollout", "rollback", "incident", "outage", "error", "latency", "slo", "sla",
    "budget", "alert", "logs", "log", "events", "root cause", "fix", "remediat", "postmortem", "down", "failing",
    "failure", "sev", "severity", "helm", "taint", "drain", "evict", "kubelet", "secret", "configmap", "replica",
    "diagnos", "triage", "what happened", "why", "broken", "degraded", "timeout", "health",
]

SECRET_PATTERNS = [
    (r"sk-[A-Za-z0-9_\-]{16,}", "[REDACTED_API_KEY]"),
    (r"voc-[A-Za-z0-9_\-]{12,}", "[REDACTED_API_KEY]"),
    (r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]"),
    (r"gh[pousr]_[A-Za-z0-9]{20,}", "[REDACTED_GITHUB_TOKEN]"),
    (r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{16,}=*", "Bearer [REDACTED_TOKEN]"),
    (r"(?i)\b([A-Z0-9_]*(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY)[A-Z0-9_]*)\s*[=:]\s*\S+", r"\1=[REDACTED]"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[REDACTED_IP]"),
]

DESTRUCTIVE_PATTERNS = [
    (r"kubectl\s+delete\s+(namespace|ns)\b", "deletes a whole namespace"),
    (r"kubectl\s+delete\b.*--all\b", "bulk delete with --all"),
    (r"kubectl\s+delete\s+(pv|pvc|persistentvolume|persistentvolumeclaim)s?\b", "deletes persistent storage"),
    (r"kubectl\s+delete\s+(node|nodes|crd|customresourcedefinition)s?\b", "deletes cluster-level objects"),
    (r"--grace-period[= ]0\b.*--force|--force\b.*--grace-period[= ]0\b", "forced immediate deletion"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "recursive forced file removal"),
    (r"etcdctl\s+(del|delete)\b", "deletes etcd keys"),
    (r"kubectl\s+drain\b(?!.*--dry-run)", "drain without dry-run (disruptive, needs change review)"),
    (r"kubectl\s+scale\b.*--replicas[= ]0\b", "scales a workload to zero"),
    (r"\bmkfs\b|\bdd\s+if=", "disk wipe"),
]

WRITE_VERBS = r"kubectl\s+(apply|patch|edit|set|scale|rollout\s+(restart|undo)|create|replace|label|annotate|cordon|uncordon|taint|delete|autoscale)\b|helm\s+(upgrade|install|rollback|uninstall)|kubeadm\s+certs\s+renew"
READ_VERBS = r"kubectl\s+(get|describe|logs|top|explain|auth\s+can-i|rollout\s+(status|history)|events|diff)\b|nslookup|dig\b|openssl\s+(x509|s_client)|kubeadm\s+certs\s+check-expiration"


def detect_injection(text: str) -> str | None:
    low = text.lower()
    for p in INJECTION_PATTERNS:
        if re.search(p, low):
            return p
    return None


def is_in_scope(text: str) -> bool:
    low = text.lower()
    return any(t in low for t in K8S_TERMS)


def redact(text: str) -> tuple[str, int]:
    """Return (redacted_text, number_of_redactions)."""
    count = 0
    for pat, rep in SECRET_PATTERNS:
        text, n = re.subn(pat, rep, text)
        count += n
    return text, count


def check_input(query: str) -> dict:
    """Run the input guardrail. Returns allowed flag, reason, and the redacted query."""
    clean, n = redact(query)
    inj = detect_injection(query)
    if inj:
        return {"allowed": False, "reason": "prompt_injection", "detail": inj, "query": clean, "redactions": n}
    if not is_in_scope(query):
        return {"allowed": False, "reason": "out_of_scope",
                "detail": "KubeSentinel only answers Kubernetes incident-response questions.", "query": clean, "redactions": n}
    return {"allowed": True, "reason": "ok", "detail": "", "query": clean, "redactions": n}


def classify_command(cmd: str) -> tuple[str, str]:
    """Return (risk, reason) where risk is READ, WRITE or DESTRUCTIVE."""
    c = " ".join(cmd.strip().split())
    for pat, why in DESTRUCTIVE_PATTERNS:
        if re.search(pat, c, flags=re.IGNORECASE):
            return "DESTRUCTIVE", why
    if re.search(WRITE_VERBS, c, flags=re.IGNORECASE):
        return "WRITE", "changes cluster state"
    if re.search(READ_VERBS, c, flags=re.IGNORECASE):
        return "READ", "read-only"
    return "WRITE", "unrecognised command treated as a write"


def check_plan(steps: list[dict]) -> dict:
    """Apply the output guardrail to remediation steps [{'command':..., 'purpose':...}]."""
    kept, blocked = [], []
    for st in steps:
        cmd = str(st.get("command", "")).strip()
        if not cmd:
            continue
        risk, why = classify_command(cmd)
        item = {**st, "command": redact(cmd)[0], "risk": risk, "policy_reason": why,
                "requires_approval": risk != "READ"}
        (blocked if risk == "DESTRUCTIVE" else kept).append(item)
    return {"steps": kept, "blocked": blocked,
            "needs_human_approval": any(s["requires_approval"] for s in kept)}
