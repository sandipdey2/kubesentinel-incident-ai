"""Draw architecture_diagram.png / .pdf with matplotlib.  python scripts/draw_architecture.py"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
fig, ax = plt.subplots(figsize=(16, 10.5))
ax.set_xlim(0, 160); ax.set_ylim(0, 105); ax.axis("off")

C = {"ui": "#e8f0fe", "guard": "#fde7e7", "llm": "#fff4d6", "rule": "#e6f4ea", "mcp": "#efe7fb", "data": "#f1f3f4", "state": "#fff"}


def box(x, y, w, h, title, body="", color="#fff", fs=9.5, bold=True, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2", fc=color, ec="#333", lw=1.2, ls=ls))
    ax.text(x + w / 2, y + h - 2.2, title, ha="center", va="top", fontsize=fs, weight="bold" if bold else "normal")
    if body:
        ax.text(x + w / 2, y + h - 5.6, body, ha="center", va="top", fontsize=7.6, linespacing=1.25)


def arrow(x1, y1, x2, y2, label="", both=False, color="#333", ls="-", rad=0.0, lx=0, ly=0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="<|-|>" if both else "-|>", mutation_scale=13,
                                 color=color, lw=1.3, ls=ls, connectionstyle=f"arc3,rad={rad}"))
    if label:
        ax.text((x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly, label, fontsize=7.3, ha="center", va="center",
                bbox=dict(fc="white", ec="none", pad=0.6))


ax.text(80, 103, "KubeSentinel - architecture as implemented (core/agents.py, core/pipeline.py, mcp_server/k8s_mcp_server.py)",
        ha="center", fontsize=12.5, weight="bold")

box(2, 84, 26, 13, "Streamlit UI (app.py)", "scenario selector + question\nlive trace, charts, citations\napproval buttons (record only)\npostmortem download", C["ui"])
box(34, 86, 28, 11, "Input guardrail", "regex: prompt injection, out-of-scope,\nsecret / email / IP redaction\n(core/guardrails.py)", C["guard"])
box(68, 84, 40, 13, "Supervisor  (LLM: gpt-4o-mini, T=0)", "structured output: next agent or FINISH\ncode rules: max 8 turns | FINISH only after\nreviewer saw latest work | max 3 visits/agent", C["llm"])
box(118, 85, 38, 12, "IncidentState (LangGraph state)", "query, triage, diagnosis, remediation,\nreview, evidence[], trace[], route[],\nturns, visits, revisions (per run, no memory)", C["state"], ls="--")

arrow(28, 91, 34, 91.5)
arrow(62, 91.5, 68, 91.5, "allowed")
ax.text(48, 82.5, "blocked -> refusal shown in UI,\nno LLM call", fontsize=7.3, ha="center", color="#b00")
arrow(108, 91, 118, 91, ls="--")

# specialists
box(6, 52, 30, 20, "Triage agent (LLM)", "ReAct tool loop <= 4 rounds\nget_cluster_overview\nclassify_log_lines, classify_metric_window\ncalculate_error_budget\n-> category, severity (burn-rate rule)", C["llm"])
box(42, 52, 32, 20, "Diagnosis agent (LLM)", "ReAct tool loop <= 4 rounds\nget_pod_status, get_events, get_pod_logs,\nget_reference_notes, get_metric_summary,\nanomaly_score, search_runbooks (RAG)\n-> root cause + evidence + RB-xx citations", C["llm"])
box(80, 52, 32, 20, "Remediation agent (LLM)", "ReAct tool loop <= 4 rounds\nsearch_runbooks, get_events, get_pod_status\n-> ordered kubectl plan + citations\nNEVER executes anything", C["llm"])
box(118, 52, 38, 20, "Reviewer (rule-based, no LLM)", "grounding = share of claims with >=50%\ncontent words found in tool outputs (>=0.6)\ncitations must be retrieved runbook ids\nblocked commands -> verdict 'revise'\n(max 1 revision) else approve", C["rule"])

for x in (21, 58, 96, 137):
    arrow(88, 84, x, 72, both=True, rad=0.0)
ax.text(66, 78.5, "supervisor -> agent -> supervisor (loop until FINISH)", fontsize=8, style="italic",
        bbox=dict(fc="white", ec="none"))

box(80, 35.5, 32, 12, "Output guardrail", "READ: allowed | WRITE: requires_approval\nDESTRUCTIVE: removed (delete ns, drain,\nrm -rf, delete pv/pvc, --force, scale 0)", C["guard"])
arrow(96, 52, 96, 47.5)

box(118, 36, 38, 11, "Postmortem generator (LLM)", "on FINISH: blameless Markdown report\nfrom state only (generative component)\n-> UI + human approval line + download", C["llm"])
arrow(106, 84, 124, 47, "FINISH", lx=3, ly=6)

# MCP
box(6, 33, 68, 13, "MCP client  (mcp SDK ClientSession + langchain-mcp-adapters load_mcp_tools)",
    "tools/list -> LangChain tools bound with bind_tools; every tools/call result is redacted before the LLM sees it\n"
    "one server subprocess per run: sys.executable mcp_server/k8s_mcp_server.py, env KS_SCENARIO", C["mcp"])
for x1, x2 in ((21, 21), (58, 58), (84, 70)):
    arrow(x1, 52, x2, 46, both=True, color="#6a3fb5")
box(6, 13, 68, 14, "MCP server  (FastMCP, stdio transport, 11 read-only tools)",
    "get_cluster_overview  get_pod_status  get_events  get_reference_notes  get_pod_logs\n"
    "get_metric_summary  anomaly_score  calculate_error_budget\nclassify_metric_window  classify_log_lines  search_runbooks", C["mcp"])
arrow(40, 33, 40, 27, "JSON-RPC over stdin/stdout", both=True, color="#6a3fb5", lx=13)

box(80, 2, 25, 19, "Replayed public data", "data/scenarios.json\n8 scenarios built from:\nkubernetes.io example\noutput (verbatim)\nLoghub log lines\nNAB metric slices\n(not a live cluster)", C["data"], fs=9)
box(108, 2, 22, 19, "RAG store", "data/runbooks.csv\n29 verbatim\nkubernetes.io excerpts\n(CC BY 4.0)\nTF-IDF + topic boost\n(core/rag.py)", C["data"], fs=9)
box(133, 2, 25, 19, "Models / statistics", "BGL log-anomaly\nTF-IDF+LogReg (P4)\nNAB window LogReg (P3)\nz-score + Welch t (P2)\nSLO burn rate\n(core/models.py, stats.py)", C["data"], fs=9)
arrow(74, 22, 90, 21.6)
arrow(74, 24, 119, 21.6)
arrow(74, 26, 145, 21.6)
ax.text(110, 26.5, "tool handlers read / call (in-process imports inside the server)", fontsize=7.3, ha="center")

ax.text(2, 0.5, "Solid boxes = code that runs. Yellow = LLM calls, green = deterministic code, red = guardrails, purple = real MCP. "
        "Repo: https://github.com/sandipdey2/kubesentinel-incident-ai", fontsize=7.8, color="#444")
plt.savefig(ROOT / "architecture_diagram.png", dpi=170, bbox_inches="tight")
plt.savefig(ROOT / "architecture_diagram.pdf", bbox_inches="tight")
print("saved")
