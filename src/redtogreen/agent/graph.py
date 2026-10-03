"""The agent as a LangGraph state machine.

    START -> reproduce --(tests already pass)--> END ("not_reproducible")
                 |
                 v
              patch  (LLM explores the code and edits it through MCP tools)
                 |
                 v
              guard  (code-enforced rules: no test edits, small diff, some change made)
              |    \\ (rule broken)
              v     \\
             test    \\           (graph runs the tests in the sandbox; the LLM cannot)
              |       v
              +---> decide --(passed)--> success -> END
                      |  \\--(attempts left)--> patch   (fresh start + feedback)
                      \\--(no attempts left)--> give_up -> END

The LLM proposes, code verifies: a fix is only "done" when the real tests pass.
"""

import json
import operator
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from redtogreen.agent import prompts
from redtogreen.config import Settings
from redtogreen.llm.base import LLM, ToolResult
from redtogreen.mcp_clients.toolbox import Toolbox, ToolOutput
from redtogreen.policy import check_patch, is_protected
from redtogreen.tracing import Tracer
from redtogreen.workspace import Workspace


class FixState(TypedDict, total=False):
    ci_log: str               # failure log from GitHub Actions (empty for local runs)
    failure: str              # failing test output reproduced inside our sandbox
    attempt: int
    explanation: str          # the LLM's "Root cause / Fix" summary
    violations: list[str]     # safety rules the last patch broke
    passed: bool
    diff: str
    status: str               # fixed | gave_up | not_reproducible
    last_test_summary: str
    history: Annotated[list[dict], operator.add]  # one record per attempt (append-only)


@dataclass
class AgentDeps:
    llm: LLM
    tools: Toolbox        # every sandbox tool (used by the graph itself)
    llm_tools: Toolbox    # the safe subset the LLM may call
    workspace: Workspace  # host-side view for diff, guard and reset
    settings: Settings
    tracer: Tracer


async def _run_tests(deps: AgentDeps, attempt: int, node: str) -> tuple[bool, str]:
    with deps.tracer.span(attempt, node, "run_tests") as step:
        out = await deps.tools.call("run_tests", {})
        if out.is_error:
            raise RuntimeError(f"run_tests failed: {out.text}")
        passed = out.text.startswith("Tests PASSED")
        step.detail = out.text.splitlines()[0] if out.text else ""
        step.ok = passed
    return passed, out.text


def build_graph(deps: AgentDeps):
    settings, tracer, ws = deps.settings, deps.tracer, deps.workspace

    async def reproduce(state: FixState) -> dict:
        with tracer.span(0, "reproduce", "prepare_sandbox") as step:
            prep = await deps.tools.call("prepare_sandbox", {})
            step.detail = prep.text[:500]
            if prep.is_error:
                raise RuntimeError(prep.text)
        passed, summary = await _run_tests(deps, 0, "reproduce")
        if passed:
            return {"status": "not_reproducible", "last_test_summary": summary, "passed": True}
        return {"failure": summary, "attempt": 0, "last_test_summary": summary}

    async def patch(state: FixState) -> dict:
        attempt = state.get("attempt", 0) + 1
        if attempt > 1:
            ws.reset()  # every attempt starts from the original code
            prompt = prompts.retry_attempt(state["failure"], attempt, state.get("history", []),
                                           state.get("ci_log", ""))
        else:
            prompt = prompts.first_attempt(state["failure"], state.get("ci_log", ""))

        conv = deps.llm.start(prompts.SYSTEM, prompt, await deps.llm_tools.specs())
        explanation, nudged = "", False
        for _ in range(settings.max_steps_per_attempt):
            with tracer.span(attempt, "llm") as step:
                turn = await conv.next_turn()
                step.input_tokens, step.output_tokens = turn.input_tokens, turn.output_tokens
                names = ", ".join(c.name for c in turn.tool_calls)
                step.detail = (turn.text[:400] + (f" [calls: {names}]" if names else "")).strip()
            if not turn.tool_calls:
                if not ws.changed_files() and not nudged:
                    conv.add_user_message(prompts.NUDGE_NO_TOOLS)
                    nudged = True
                    continue
                explanation = turn.text.strip()
                break
            results = []
            for call in turn.tool_calls:
                with tracer.span(attempt, "tool", call.name) as step:
                    if call.parse_error:
                        out = ToolOutput(call.parse_error, True)
                    else:
                        out = await deps.llm_tools.call(call.name, call.arguments)
                    step.ok = not out.is_error
                    step.detail = f"{json.dumps(call.arguments)[:300]} -> {out.text[:300]}"
                results.append(ToolResult(call=call, text=out.text, is_error=out.is_error))
            conv.add_tool_results(results)
        else:
            explanation = "(stopped: step budget for this attempt used up)"
        return {"attempt": attempt, "explanation": explanation}

    async def guard(state: FixState) -> dict:
        attempt = state["attempt"]
        with tracer.span(attempt, "guard") as step:
            stats = ws.patch_stats()
            violations = check_patch(stats, settings.protected_paths, settings.max_changed_files,
                                     settings.max_changed_lines)
            if not stats.files:
                violations.append("No code was changed.")
            protected = [f for f in stats.files if is_protected(f, settings.protected_paths)]
            if protected:
                ws.revert_paths(protected)  # defence in depth: the edit tool already blocks this
            step.detail = "; ".join(violations) or f"ok: {stats.files} (+{stats.added}/-{stats.removed})"
            step.ok = not violations
        if not violations:
            return {"violations": []}
        record = {"attempt": attempt, "diff": ws.diff(), "violations": violations, "passed": False,
                  "test_summary": "", "explanation": state.get("explanation", "")}
        return {"violations": violations, "passed": False, "history": [record]}

    async def test(state: FixState) -> dict:
        attempt = state["attempt"]
        passed, summary = await _run_tests(deps, attempt, "test")
        diff = ws.diff()
        record = {"attempt": attempt, "diff": diff, "violations": [], "passed": passed,
                  "test_summary": summary, "explanation": state.get("explanation", "")}
        return {"passed": passed, "diff": diff, "last_test_summary": summary, "history": [record]}

    async def success(state: FixState) -> dict:
        return {"status": "fixed", "diff": ws.diff()}

    async def give_up(state: FixState) -> dict:
        ws.reset()
        return {"status": "gave_up", "diff": ""}

    def after_reproduce(state: FixState) -> str:
        return "end" if state.get("status") == "not_reproducible" else "patch"

    def after_guard(state: FixState) -> str:
        return "decide" if state.get("violations") else "test"

    def route_decision(state: FixState) -> str:
        if state.get("passed"):
            return "success"
        if state["attempt"] >= settings.max_attempts:
            return "give_up"
        return "patch"

    g = StateGraph(FixState)
    g.add_node("reproduce", reproduce)
    g.add_node("patch", patch)
    g.add_node("guard", guard)
    g.add_node("test", test)
    g.add_node("success", success)
    g.add_node("give_up", give_up)
    g.add_edge(START, "reproduce")
    g.add_conditional_edges("reproduce", after_reproduce, {"end": END, "patch": "patch"})
    g.add_edge("patch", "guard")
    g.add_node("decide", lambda state: {})  # a no-op node so both paths share one routing rule
    g.add_conditional_edges("guard", after_guard, {"test": "test", "decide": "decide"})
    g.add_edge("test", "decide")
    g.add_conditional_edges("decide", route_decision,
                            {"success": "success", "give_up": "give_up", "patch": "patch"})
    g.add_edge("success", END)
    g.add_edge("give_up", END)
    return g.compile()


def mermaid() -> str:
    """Diagram of the graph (paste into any Mermaid viewer or a GitHub README)."""

    class _Null:
        def __getattr__(self, _):
            return None

    return build_graph(_Null()).get_graph().draw_mermaid()  # type: ignore[arg-type]
