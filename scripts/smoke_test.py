"""End-to-end check with the real LLM: python scripts/smoke_test.py [scenario_id]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.pipeline import run_incident  # noqa: E402

sid = sys.argv[1] if len(sys.argv) > 1 else "oomkilled"
q = sys.argv[2] if len(sys.argv) > 2 else "What is wrong with this workload and how do we fix it safely?"
r = run_incident(q, sid)
print("status:", r["status"], "| latency_s:", r["latency_s"], "| tool calls:", r["tool_calls"])
print("route:", r.get("route"))
for t in r["trace"]:
    if t["type"] == "route":
        print(f"  supervisor -> {t['next']:12s} {t.get('override', '')} | {t['reason'][:90]}")
    elif t["type"] == "mcp_tool_call":
        print(f"    [{t['agent']}] MCP {t['tool']}({json.dumps(t['args'])}) redactions={t['redactions']}")
    elif t["type"] == "review":
        print(f"  reviewer verdict={t['verdict']} grounding={t['grounding_score']} issues={t['issues']}")
    elif t["type"] == "guardrail":
        print("  guardrail:", {k: v for k, v in t.items() if k not in ('agent', 'type')})
if r["status"] == "completed":
    print("triage:", r["triage"])
    print("diagnosis:", json.dumps(r["diagnosis"], indent=1)[:1200])
    print("plan:", [(s["command"], s["risk"]) for s in r["remediation"]["steps"]] if r.get("remediation") else None)
    print("blocked:", [b["command"] for b in (r.get("remediation") or {}).get("blocked", [])])
    print("postmortem chars:", len(r["postmortem"]))
