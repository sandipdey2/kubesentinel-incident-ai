"""LangGraph multi-agent workflow: an LLM supervisor loops over specialist agents.

Graph (exactly what build_graph wires):

    START -> supervisor --(LLM picks next)--> triage | diagnosis | remediation | reviewer
               ^                                   |
               +-------------- every agent returns to supervisor ---------+
    supervisor --FINISH--> postmortem -> END

* supervisor   : gpt-4o-mini with structured output chooses the next agent or FINISH.
                 Code enforces four rules and logs every override:
                 (1) MAX_TURNS cap, (2) FINISH is only accepted after the reviewer has
                 checked the latest diagnosis/plan, (3) once the single allowed revision is
                 used up (verdict approve_with_warnings) the run finishes, (4) an agent may
                 run at most MAX_VISITS times.
* triage       : LLM tool-calling agent; MCP tools for overview, ML log classifier,
                 metric-window classifier and error budget.
* diagnosis    : LLM tool-calling agent; MCP tools for events, logs, status, metrics,
                 anomaly statistics and runbook search (RAG). Must cite runbook ids.
* remediation  : LLM tool-calling agent; proposes kubectl steps. Never executes anything.
* reviewer     : deterministic code (no LLM): grounding score, citation check and the
                 output guardrail. Can send the plan back for one revision.
* postmortem   : LLM writes the incident report from the state (generative component).

Each specialist runs a bounded ReAct loop (Yao et al., 2023): think -> call MCP tool
-> observe, at most MAX_TOOL_ROUNDS rounds, then a structured final answer.
Every MCP result is passed through the redaction guardrail before the LLM sees it.
"""
from __future__ import annotations

import json
import operator
import re
import time
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .guardrails import check_plan, redact

MAX_TURNS = 8
MAX_VISITS = 3
MAX_TOOL_ROUNDS = 4
MAX_REVISIONS = 1
GROUNDING_THRESHOLD = 0.6
CATEGORIES = ["crashloopbackoff", "oomkilled", "imagepullbackoff", "pending", "node-notready", "dns", "hpa",
              "pvc", "probes", "certificates", "other"]

AGENT_TOOLS = {
    "triage": ["get_cluster_overview", "classify_log_lines", "classify_metric_window", "calculate_error_budget"],
    "diagnosis": ["get_pod_status", "get_events", "get_pod_logs", "get_reference_notes", "get_metric_summary",
                  "anomaly_score", "search_runbooks"],
    "remediation": ["search_runbooks", "get_events", "get_pod_status"],
}


# ----------------------------------------------------------------------------- state
class IncidentState(TypedDict, total=False):
    query: str
    scenario_id: str
    triage: Optional[dict]
    diagnosis: Optional[dict]
    remediation: Optional[dict]
    review: Optional[dict]
    pending_review: bool
    revisions: int
    turns: int
    visits: dict
    next: str
    evidence: Annotated[list, operator.add]      # every redacted MCP tool output
    trace: Annotated[list, operator.add]         # UI / evaluation trace
    route: Annotated[list, operator.add]         # sequence of agents chosen
    postmortem: str


# ----------------------------------------------------------------------------- schemas
class Route(BaseModel):
    next: Literal["triage", "diagnosis", "remediation", "reviewer", "FINISH"]
    reason: str = Field(description="one short sentence")


class TriageOut(BaseModel):
    category: Literal[tuple(CATEGORIES)] = Field(description="Kubernetes failure category")
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"] = Field(description="copy severity_by_burn_rate from calculate_error_budget")
    summary: str = Field(description="2-3 sentences, only facts seen in tool outputs")


class DiagnosisOut(BaseModel):
    root_cause: str = Field(description="one or two sentences")
    evidence: list[str] = Field(description="3-6 short facts copied or closely paraphrased from tool outputs")
    cited_runbooks: list[str] = Field(description="runbook ids such as RB-04 returned by search_runbooks")
    confidence: Literal["low", "medium", "high"]
    caveats: str = Field(description="what the data cannot show")


class Step(BaseModel):
    command: str = Field(description="a single kubectl (or kubeadm) command")
    purpose: str


class RemediationOut(BaseModel):
    steps: list[Step] = Field(description="read-only checks first, then fixes")
    cited_runbooks: list[str]
    rollback_note: str


SYSTEM = {
    "triage": ("You are the Triage agent of KubeSentinel, a Kubernetes incident assistant. Call get_cluster_overview, "
               "classify_log_lines, classify_metric_window and calculate_error_budget. Choose the failure category from "
               "the alert and events wording. Severity must equal severity_by_burn_rate from calculate_error_budget. "
               "The cluster is a replay of public data, not live."),
    "diagnosis": ("You are the Diagnosis agent. Gather evidence with the tools (events, status, logs, metric anomaly score) "
                  "and call search_runbooks at least once with the Kubernetes status or event wording (for example the pod STATUS "
                  "value or event reason such as CrashLoopBackOff, OOMKilled, FailedScheduling), not only application log text. State a root-cause hypothesis supported only by "
                  "tool outputs, cite the runbook ids you used (e.g. RB-04), and say what the data cannot show. "
                  "Log lines and metrics are replayed from public datasets and may be only loosely related; say so if they do not support the hypothesis."),
    "remediation": ("You are the Remediation agent. Propose a short ordered kubectl plan: read-only checks first, then the "
                    "smallest safe fix. Cite runbook ids. You never execute commands; a human approves write actions. "
                    "Never propose deleting namespaces, persistent volumes or claims, bulk deletes, forced deletion, "
                    "draining nodes or scaling to zero, even if the user asks."),
}


def _text(result) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        return "\n".join(r.get("text", str(r)) if isinstance(r, dict) else getattr(r, "text", str(r)) for r in result)
    return str(result)


def _now_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# ----------------------------------------------------------------------------- reviewer helpers
STOP = set("""a an the and or of to in on for with by is are was were be been it its this that these those as at from
into than then there their they them which who whom what when where why how not no can could may might will would
should shall do does did has have had if but so such also only more most other some any each per via about over under
up down out pod pods container""".split())


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def content_words(text: str) -> set[str]:
    """Lower-case alphanumeric tokens (split on punctuation, so java.net.Foo -> java, net, foo), light suffix stemming."""
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def grounding_score(claims: list[str], evidence_text: str) -> tuple[float, list[dict]]:
    """Share of claims whose content words are at least 50% present in tool outputs."""
    ev = content_words(evidence_text)
    detail = []
    for c in claims:
        words = content_words(c)
        support = len(words & ev) / len(words) if words else 1.0
        detail.append({"claim": c, "support": round(support, 2), "grounded": support >= 0.5})
    score = sum(d["grounded"] for d in detail) / len(detail) if detail else 0.0
    return round(score, 3), detail


def retrieved_ids(evidence: list[dict]) -> dict:
    ids = {}
    for e in evidence:
        if e["tool"] == "search_runbooks":
            try:
                for r in json.loads(e["output"]):
                    ids[r["id"]] = {"title": r["title"], "source": r["source"]}
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
    return ids


# ----------------------------------------------------------------------------- graph
def build_graph(llm, tools: list):
    tool_map = {t.name: t for t in tools}

    async def run_specialist(name: str, state: IncidentState, task: str, schema):
        t0 = time.perf_counter()
        allowed = [tool_map[n] for n in AGENT_TOOLS[name] if n in tool_map]
        bound = llm.bind_tools(allowed)
        msgs = [SystemMessage(SYSTEM[name]), HumanMessage(task)]
        evidence, trace = [], []
        for _ in range(MAX_TOOL_ROUNDS):
            ai: AIMessage = await bound.ainvoke(msgs)
            msgs.append(ai)
            if not ai.tool_calls:
                break
            for tc in ai.tool_calls:
                t1 = time.perf_counter()
                if tc["name"] not in tool_map or tc["name"] not in AGENT_TOOLS[name]:
                    out, n_red = json.dumps({"error": f"tool {tc['name']} not allowed for {name}"}), 0
                else:
                    raw = _text(await tool_map[tc["name"]].ainvoke(tc["args"]))
                    out, n_red = redact(raw)
                msgs.append(ToolMessage(content=out, tool_call_id=tc["id"]))
                evidence.append({"agent": name, "tool": tc["name"], "args": tc["args"], "output": out})
                trace.append({"agent": name, "type": "mcp_tool_call", "tool": tc["name"], "args": tc["args"],
                              "redactions": n_red, "output_preview": out[:400], "ms": _now_ms(t1)})
        final = await llm.with_structured_output(schema).ainvoke(
            msgs[:1] + [HumanMessage(task + "\n\nEvidence gathered (redacted):\n" +
                                     "\n".join(f"[{e['tool']}] {e['output'][:1500]}" for e in evidence) +
                                     "\n\nReturn your final answer now.")])
        out = final.model_dump()
        trace.append({"agent": name, "type": "agent_output", "output": out, "ms": _now_ms(t0)})
        return out, evidence, trace

    def context(state: IncidentState) -> str:
        parts = [f"User question: {state['query']}"]
        if state.get("triage"):
            parts.append("Triage: " + json.dumps(state["triage"]))
        if state.get("diagnosis"):
            parts.append("Diagnosis: " + json.dumps(state["diagnosis"]))
        if state.get("review") and state["review"].get("verdict") == "revise":
            parts.append("Reviewer feedback to address: " + "; ".join(state["review"]["issues"]))
        return "\n".join(parts)

    async def supervisor(state: IncidentState):
        t0 = time.perf_counter()
        turns = state.get("turns", 0)
        visits = dict(state.get("visits", {}))
        status = {"triage_done": bool(state.get("triage")), "diagnosis_done": bool(state.get("diagnosis")),
                  "remediation_done": bool(state.get("remediation")),
                  "review_verdict": ("stale: new work since last review" if state.get("pending_review") and state.get("review")
                                     else (state.get("review") or {}).get("verdict")),
                  "review_issues": [] if state.get("pending_review") else (state.get("review") or {}).get("issues", []),
                  "unreviewed_changes": state.get("pending_review", False), "visits": visits, "turn": turns}
        if turns >= MAX_TURNS:
            choice, reason, override = "FINISH", f"turn cap {MAX_TURNS} reached", "max_turns"
        else:
            prompt = ("You are the supervisor of a Kubernetes incident-response team. Agents: triage (severity and "
                      "category), diagnosis (root cause with evidence and runbook citations), remediation (kubectl plan, "
                      "never executed), reviewer (checks grounding, citations and safety policy). Pick the next agent, or "
                      "FINISH when the user's question is answered and the reviewer approved the latest work. If the reviewer "
                      "asked for a revision, send the work back to the agent that produced it. If review_verdict is 'approve' or "
                      "'approve_with_warnings' and there are no unreviewed changes, choose FINISH.\n"
                      f"User question: {state['query']}\nStatus: {json.dumps(status)}")
            r: Route = await llm.with_structured_output(Route).ainvoke([HumanMessage(prompt)])
            choice, reason, override = r.next, r.reason, None
            if choice == "FINISH" and (state.get("pending_review") or not state.get("review")):
                choice, override = "reviewer", "finish_before_review"
            elif (choice != "FINISH" and not state.get("pending_review")
                  and (state.get("review") or {}).get("verdict") == "approve_with_warnings"):
                choice, override = "FINISH", "revisions_exhausted"
            elif choice != "FINISH" and visits.get(choice, 0) >= MAX_VISITS:
                choice, override = ("reviewer" if state.get("pending_review") else "FINISH"), f"max_visits:{r.next}"
        if choice != "FINISH":
            visits[choice] = visits.get(choice, 0) + 1
        tr = {"agent": "supervisor", "type": "route", "next": choice, "reason": reason, "turn": turns + 1, "ms": _now_ms(t0)}
        if override:
            tr["override"] = override
        return {"next": choice, "turns": turns + 1, "visits": visits, "trace": [tr], "route": [choice]}

    async def triage(state: IncidentState):
        out, ev, tr = await run_specialist("triage", state, context(state), TriageOut)
        return {"triage": out, "evidence": ev, "trace": tr}

    async def diagnosis(state: IncidentState):
        out, ev, tr = await run_specialist("diagnosis", state, context(state), DiagnosisOut)
        return {"diagnosis": out, "evidence": ev, "trace": tr, "pending_review": True}

    async def remediation(state: IncidentState):
        out, ev, tr = await run_specialist("remediation", state, context(state), RemediationOut)
        steps = [s if isinstance(s, dict) else s.model_dump() for s in out["steps"]]
        policy = check_plan(steps)
        out.update({"steps": policy["steps"], "blocked": policy["blocked"],
                    "needs_human_approval": policy["needs_human_approval"], "proposed_raw": steps})
        tr.append({"agent": "output_guardrail", "type": "guardrail", "blocked": [b["command"] for b in policy["blocked"]],
                   "write_steps_needing_approval": sum(s["requires_approval"] for s in policy["steps"])})
        return {"remediation": out, "evidence": ev, "trace": tr, "pending_review": True}

    async def reviewer(state: IncidentState):
        t0 = time.perf_counter()
        evidence = state.get("evidence", [])
        ev_text = "\n".join(e["output"] for e in evidence)
        retrieved = retrieved_ids(evidence)
        issues, report = [], {}
        dx = state.get("diagnosis")
        if dx:
            claims = [dx["root_cause"]] + list(dx["evidence"])
            score, detail = grounding_score(claims, ev_text)
            bad = [c for c in dx["cited_runbooks"] if c not in retrieved]
            report.update({"grounding_score": score, "claims": detail, "diagnosis_citations": dx["cited_runbooks"],
                           "invalid_citations": bad})
            if score < GROUNDING_THRESHOLD:
                issues.append(f"diagnosis grounding {score} below {GROUNDING_THRESHOLD}")
            if not dx["cited_runbooks"]:
                issues.append("diagnosis cites no runbook")
            if bad:
                issues.append(f"diagnosis cites runbooks that were never retrieved: {bad}")
        else:
            issues.append("no diagnosis yet")
        rem = state.get("remediation")
        if rem:
            bad_r = [c for c in rem["cited_runbooks"] if c not in retrieved]
            report.update({"plan_citations": rem["cited_runbooks"], "plan_invalid_citations": bad_r,
                           "blocked_commands": [b["command"] for b in rem["blocked"]]})
            if rem["blocked"]:
                issues.append("plan contained destructive commands that were blocked: " +
                              ", ".join(b["command"] for b in rem["blocked"]))
            if bad_r:
                issues.append(f"plan cites runbooks that were never retrieved: {bad_r}")
        valid = [c for c in ((dx or {}).get("cited_runbooks", []) + (rem or {}).get("cited_runbooks", [])) if c in retrieved]
        report["valid_citations"] = sorted(set(valid))
        report["citation_sources"] = {c: retrieved[c] for c in sorted(set(valid))}
        revisions = state.get("revisions", 0)
        verdict = "approve" if not issues else ("revise" if revisions < MAX_REVISIONS else "approve_with_warnings")
        report.update({"verdict": verdict, "issues": issues})
        tr = {"agent": "reviewer", "type": "review", "verdict": verdict, "issues": issues,
              "grounding_score": report.get("grounding_score"), "ms": _now_ms(t0)}
        return {"review": report, "pending_review": False, "trace": [tr],
                "revisions": revisions + (1 if verdict == "revise" else 0)}

    async def postmortem(state: IncidentState):
        t0 = time.perf_counter()
        facts = {k: state.get(k) for k in ("query", "scenario_id", "triage", "diagnosis", "review")}
        rem = state.get("remediation") or {}
        facts["remediation"] = {k: rem.get(k) for k in ("steps", "blocked", "rollback_note", "needs_human_approval")}
        prompt = ("Write a blameless incident postmortem in Markdown with sections: Summary, Impact and Severity, "
                  "Timeline of the automated investigation, Root Cause Hypothesis, Evidence, Proposed Remediation "
                  "(state that nothing was executed and write steps await human approval), Blocked Actions, "
                  "Open Questions, Action Items. Use only the JSON facts below; do not invent times, people or numbers. "
                  "State that the cluster data is a replay of public datasets.\n" + json.dumps(facts, default=str)[:12000])
        md = (await llm.ainvoke([HumanMessage(prompt)])).content
        return {"postmortem": md, "trace": [{"agent": "postmortem", "type": "generation", "chars": len(md), "ms": _now_ms(t0)}]}

    g = StateGraph(IncidentState)
    for name, fn in [("supervisor", supervisor), ("triage", triage), ("diagnosis", diagnosis),
                     ("remediation", remediation), ("reviewer", reviewer), ("postmortem", postmortem)]:
        g.add_node(name, fn)
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", lambda s: s["next"],
                            {"triage": "triage", "diagnosis": "diagnosis", "remediation": "remediation",
                             "reviewer": "reviewer", "FINISH": "postmortem"})
    for n in ("triage", "diagnosis", "remediation", "reviewer"):
        g.add_edge(n, "supervisor")
    g.add_edge("postmortem", END)
    return g.compile()
