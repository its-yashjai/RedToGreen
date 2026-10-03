"""Runs one fix job end to end. Used by the CLI (Level 1 and 2) and by the worker (Level 3)."""

import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from redtogreen.agent.graph import AgentDeps, build_graph
from redtogreen.config import Settings
from redtogreen.llm import get_llm
from redtogreen.llm.base import LLM, LLMRefusal
from redtogreen.mcp_clients.toolbox import LLM_SANDBOX_TOOLS, Toolbox, open_sandbox
from redtogreen.tracing import Tracer
from redtogreen.workspace import Workspace


@dataclass
class FixOutcome:
    status: str  # fixed | gave_up | not_reproducible | superseded | error | pr_opened
    diff: str = ""
    explanation: str = ""
    attempts: int = 0
    changed_files: list[str] = field(default_factory=list)
    final_files: dict[str, str] = field(default_factory=dict)  # path -> new content
    history: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    pr_url: str = ""
    error: str = ""


def new_job_dir(settings: Settings, prefix: str = "job") -> Path:
    path = settings.workdir / f"{prefix}-{uuid.uuid4().hex[:10]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def run_agent(workspace: Workspace, settings: Settings, llm: LLM, tracer: Tracer,
                    ci_log: str = "") -> FixOutcome:
    """Start the sandbox MCP server for this workspace and run the LangGraph agent."""
    start = time.monotonic()
    try:
        async with open_sandbox(workspace.root, settings) as client:
            deps = AgentDeps(
                llm=llm,
                tools=Toolbox(client),
                llm_tools=Toolbox(client, LLM_SANDBOX_TOOLS),
                workspace=workspace,
                settings=settings,
                tracer=tracer,
            )
            state = await build_graph(deps).ainvoke(
                {"ci_log": ci_log, "history": []}, config={"recursion_limit": 100}
            )
    except LLMRefusal as exc:
        return FixOutcome(status="gave_up", error=str(exc), duration_s=time.monotonic() - start,
                          input_tokens=tracer.input_tokens, output_tokens=tracer.output_tokens)

    status = state.get("status", "error")
    changed = workspace.changed_files() if status == "fixed" else []
    history = state.get("history", [])
    explanation = state.get("explanation", "")
    if status == "gave_up" and history:
        explanation = history[-1].get("explanation", "") or explanation
    return FixOutcome(
        status=status,
        diff=state.get("diff", ""),
        explanation=explanation,
        attempts=state.get("attempt", 0),
        changed_files=changed,
        final_files={p: workspace.file_text(p) for p in changed},
        history=history,
        input_tokens=tracer.input_tokens,
        output_tokens=tracer.output_tokens,
        cost_usd=llm.cost_usd(tracer.input_tokens, tracer.output_tokens),
        duration_s=time.monotonic() - start,
    )


async def fix_local(path: Path, settings: Settings, llm: LLM | None = None, tracer: Tracer | None = None,
                    keep: bool = False) -> FixOutcome:
    """Level 1: fix a project on disk. The original folder is never touched (we work on a copy)."""
    job_dir = new_job_dir(settings, "local")
    try:
        ws = Workspace.from_directory(path.resolve(), job_dir / "repo", settings.protected_paths)
        return await run_agent(ws, settings, llm or get_llm(settings), tracer or Tracer())
    finally:
        if not keep:
            shutil.rmtree(job_dir, ignore_errors=True)


def apply_files(outcome: FixOutcome, target: Path) -> list[str]:
    """Write the fixed files back into the user's folder (only when they ask with --apply)."""
    for rel_path, content in outcome.final_files.items():
        (target / rel_path).write_text(content)
    return list(outcome.final_files)
