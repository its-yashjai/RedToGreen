"""Command line interface.

Level 1   redtogreen fix-local ./my-project            fix a project on your laptop
Level 2   redtogreen fix-github owner/repo 123456789   fix a failed GitHub Actions run, open a PR
Level 3   redtogreen serve / redtogreen worker         webhook server + background workers
Quality   redtogreen bench / redtogreen attacks        measure fix rate and safety
"""

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from redtogreen.config import PROJECT_ROOT, Settings, get_settings
from redtogreen.tracing import Tracer

app = typer.Typer(add_completion=False, no_args_is_help=True, help="RedToGreen: turn failing builds green.")
console = Console()
ROOT = PROJECT_ROOT

DEMO_WORKFLOW = """name: tests
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: pip install pytest
      - run: python -m pytest -q
"""


def _settings() -> Settings:
    return get_settings()


def _print_trace(tracer: Tracer) -> None:
    table = Table(title="Trace", show_lines=False)
    for col in ("attempt", "node", "tool", "ms", "tokens", "detail"):
        table.add_column(col, overflow="fold")
    for s in tracer.steps:
        style = "" if s.ok else "red"
        table.add_row(str(s.attempt), s.node, s.tool, str(s.ms), str(s.input_tokens + s.output_tokens),
                      s.detail[:120], style=style)
    console.print(table)


def _print_outcome(outcome) -> None:
    color = {"fixed": "green", "pr_opened": "green"}.get(outcome.status, "yellow")
    console.print(f"\n[bold {color}]Result: {outcome.status}[/] after {outcome.attempts} attempt(s), "
                  f"{outcome.duration_s:.1f}s, {outcome.input_tokens + outcome.output_tokens} tokens, "
                  f"${outcome.cost_usd:.4f}")
    if outcome.explanation:
        console.print(f"\n{outcome.explanation}")
    if outcome.diff:
        console.print("\n[bold]Diff[/]")
        console.print(outcome.diff, markup=False, highlight=False)
    if outcome.pr_url:
        console.print(f"\nPull request: {outcome.pr_url}")
    if outcome.error:
        console.print(f"[red]{outcome.error}[/]")


# ---------------------------------------------------------------- Level 1
@app.command("fix-local")
def fix_local_cmd(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Project folder with failing tests")],
    apply: Annotated[bool, typer.Option(help="Write the fix back into the folder")] = False,
    keep: Annotated[bool, typer.Option(help="Keep the temporary workspace for inspection")] = False,
    trace: Annotated[bool, typer.Option(help="Print every step")] = True,
):
    """Level 1: fix a project on disk (works on a copy; your folder changes only with --apply)."""
    from redtogreen.pipeline import apply_files, fix_local

    tracer = Tracer()
    try:
        outcome = asyncio.run(fix_local(path, _settings(), tracer=tracer, keep=keep))
    except (ValueError, RuntimeError) as exc:  # configuration problems: say what to fix, no traceback
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from None
    if trace:
        _print_trace(tracer)
    _print_outcome(outcome)
    if apply and outcome.status == "fixed":
        changed = apply_files(outcome, path)
        console.print(f"[green]Applied fix to {', '.join(changed)}[/]")
    raise typer.Exit(0 if outcome.status in ("fixed", "not_reproducible") else 1)


# ---------------------------------------------------------------- Level 2
@app.command("fix-github")
def fix_github_cmd(
    repo: Annotated[str, typer.Argument(help="owner/name")],
    run_id: Annotated[int, typer.Argument(help="ID of the failed workflow run (from its URL)")],
):
    """Level 2: fix a failed GitHub Actions run and open a pull request."""
    from redtogreen.github.fixer import fix_github_run, run_info_from_api
    from redtogreen.github.git import GitError
    from redtogreen.github.mcp import GitHubError
    from redtogreen.mcp_clients.toolbox import MCPStartError

    settings = _settings()
    owner, _, name = repo.partition("/")
    tracer = Tracer()
    try:
        run = asyncio.run(run_info_from_api(owner, name, run_id, settings))
        console.print(f"Run {run_id}: branch [bold]{run.head_branch}[/] commit {run.head_sha[:7]}")
        outcome = asyncio.run(fix_github_run(run, settings, tracer=tracer))
    except (ValueError, RuntimeError, GitHubError, GitError, MCPStartError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from None
    _print_trace(tracer)
    _print_outcome(outcome)


# ---------------------------------------------------------------- Level 3
@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000):
    """Level 3: run the webhook server and dashboard."""
    import uvicorn

    uvicorn.run("redtogreen.api.app:factory", factory=True, host=host, port=port, proxy_headers=True)


@app.command()
def worker():
    """Level 3: run a background worker (start as many as you like)."""
    from rq import Worker

    from redtogreen.worker.queue import get_queue, get_redis
    from redtogreen.worker.tasks import requeue_stale_jobs

    settings = _settings()
    requeued = requeue_stale_jobs(settings)
    if requeued:
        console.print(f"Re-queued {requeued} job(s) left behind by a crashed worker")
    Worker([get_queue(settings)], connection=get_redis(settings)).work(with_scheduler=False)


@app.command("db-upgrade")
def db_upgrade():
    """Create or migrate the database tables (Alembic)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    console.print("[green]Database is up to date[/]")


# ---------------------------------------------------------------- quality
@app.command()
def bench(
    verify: Annotated[bool, typer.Option(help="Only check that every seeded bug breaks the tests")] = False,
    llm: Annotated[str, typer.Option(help="'real' (your LLM) or 'oracle' (pipeline check)")] = "real",
    only: Annotated[str, typer.Option(help="Comma-separated bug ids, e.g. B01,B07")] = "",
    min_fix_rate: Annotated[float, typer.Option(help="Exit 1 if the fix rate is below this (CI gate)")] = 0.0,
):
    """Run the 30-bug benchmark."""
    from redtogreen.bench import run_bench, verify_bugs, write_report

    settings = _settings()
    if verify:
        rows = asyncio.run(verify_bugs(settings))
        for r in rows:
            console.print(f"{'[green]OK [/]' if r['ok'] else '[red]BAD[/]'} {r['id']:<6} {r['detail']}")
        raise typer.Exit(0 if all(r["ok"] for r in rows) else 1)
    ids = {x.strip() for x in only.split(",") if x.strip()} or None
    report = asyncio.run(run_bench(settings, llm, ids))
    json_path, md_path = write_report(report, llm)
    s = report["summary"]
    console.print(f"\n[bold]Fix rate {s['fixed']}/{s['cases']} = {s['fix_rate']:.0%}[/]  "
                  f"median {s['median_seconds']}s  cost ${s['total_cost_usd']}")
    console.print(f"Report: {md_path}")
    if s["fix_rate"] < min_fix_rate:
        console.print(f"[red]Below the gate of {min_fix_rate:.0%}[/]")
        raise typer.Exit(1)


@app.command()
def attacks(with_llm: Annotated[bool, typer.Option(help="Also run attacks that need the LLM")] = False):
    """Run the attack set (prompt injection, secret theft, sandbox escape...)."""
    from redtogreen.bench import run_attacks

    rows = asyncio.run(run_attacks(_settings(), with_llm))
    failed = [r for r in rows if r["result"] == "GOT THROUGH"]
    console.print(f"\n{len(rows) - len(failed)} of {len(rows)} attacks blocked or skipped")
    raise typer.Exit(1 if failed else 0)


# ---------------------------------------------------------------- helpers
@app.command("sandbox-build")
def sandbox_build():
    """Build the Docker image the tests run in."""
    import docker

    settings = _settings()
    console.print(f"Building {settings.sandbox_image} from sandbox/Dockerfile ...")
    docker.from_env().images.build(path=str(ROOT / "sandbox"), tag=settings.sandbox_image, rm=True)
    console.print("[green]Done[/]")


@app.command("init-demo")
def init_demo(dest: Annotated[Path, typer.Argument(help="Folder to create")]):
    """Create the demo repo (shopkit + tests + a GitHub Actions workflow) to push to GitHub."""
    if dest.exists():
        console.print(f"[red]{dest} already exists[/]")
        raise typer.Exit(1)
    shutil.copytree(ROOT / "benchmark" / "demo_repo", dest, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / ".github" / "workflows").mkdir(parents=True)
    (dest / ".github" / "workflows" / "tests.yml").write_text(DEMO_WORKFLOW)
    console.print(f"[green]Created {dest}[/]. Next: cd {dest} && git init && git add . && git commit -m init")


@app.command("break-demo")
def break_demo(
    path: Annotated[Path, typer.Argument(help="Your demo repo folder")],
    bug: Annotated[str, typer.Option(help="Bug id from benchmark/bugs.yaml, e.g. B01")] = "",
    list_bugs: Annotated[bool, typer.Option("--list", help="Show all bug ids")] = False,
):
    """Plant one benchmark bug in your demo repo (for a live demo)."""
    from redtogreen.bench import apply_edits, load_bugs

    bugs = {b.id: b for b in load_bugs()}
    if list_bugs or not bug:
        for b in bugs.values():
            console.print(f"{b.id}  {b.category:<18} {b.file}")
        return
    apply_edits(path, bugs[bug].edits)
    console.print(f"Planted {bug} in {bugs[bug].file}. Commit and push it to see CI go red.")


@app.command()
def graph():
    """Print the agent's LangGraph as a Mermaid diagram."""
    from redtogreen.agent.graph import mermaid

    sys.stdout.write(mermaid() + "\n")


if __name__ == "__main__":
    app()
