# RedToGreen

**An AI agent that turns failing builds green.** When tests fail on GitHub, RedToGreen reads the
error, finds the bug, tries a fix inside a locked Docker sandbox, and opens a pull request only if
the whole test suite passes. A human still clicks merge.

```
push ──▶ CI fails ──▶ webhook ──▶ queue ──▶ worker runs the agent
                                               │
          reproduce ─▶ patch ─▶ guard ─▶ test ─┤ (up to 3 attempts)
                                               ▼
                                  tests pass ─▶ pull request ─▶ human merges
```

## Why it is interesting

| Idea | Where it shows up |
|---|---|
| **Agent with a real loop** | LangGraph state machine: reproduce → patch → guard → test → decide, max 3 attempts, each retry learns from the last failure |
| **MCP used for real** | The agent is an MCP *client*. It uses my sandbox MCP server (read, search, edit, run tests) and GitHub's official MCP server (logs, branch, push, PR) |
| **Security in code, not in prompts** | Tests and CI files are read-only, the sandbox has no network and no secrets, code is mounted read-only, non-root user, CPU/memory/process limits, hard timeout |
| **Objective evaluation** | 30 seeded bugs; a fix counts only if the real test suite passes. No LLM judge needed |
| **Production shape** | FastAPI webhook (HMAC-verified, deduplicated) → Redis queue → workers → Postgres → live dashboard with full traces and cost |

## Results

Measured in this repo, reproducible with one command each:

| Check | Result | Command |
|---|---|---|
| Every seeded bug really breaks the tests (in the Docker sandbox) | 30/30 | `redtogreen bench --verify` |
| Full pipeline with an oracle LLM (proves the plumbing, not AI skill) | 30/30 | `redtogreen bench --llm oracle` |
| Sandbox attacks blocked (secret theft + phone home, infinite loop, source tampering) | 3/3 | `redtogreen attacks` |
| Unit + integration tests (incl. real Docker isolation tests) | 52 | `pytest` |
| **Real fix rate with your LLM** | run it and write your number here | `redtogreen bench --llm real` |

Honest note: the real fix rate depends on the model you use. Run the benchmark, write the number
here, and keep a "where it failed" list. That list is worth more in an interview than a perfect score.

## Quick start

```bash
git clone https://github.com/its-yashjai/RedToGreen && cd RedToGreen
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # set LLM_MODEL / LLM_API_KEY (Groq free tier, Ollama, or Claude)
redtogreen sandbox-build      # builds the Docker image the tests run in
pytest                        # everything should pass
```

**Level 1, fix a project on your laptop:**
```bash
redtogreen init-demo ../shop-demo
redtogreen break-demo ../shop-demo --bug B01
redtogreen fix-local ../shop-demo             # prints the trace and the diff
```

**Level 2, fix a failed GitHub Actions run and open a PR:**
```bash
redtogreen fix-github your-name/shop-demo 1234567890
```

**Level 3, the full service:**
```bash
docker compose up --build     # Postgres, Redis, migrations, API on :8000, worker
```
Then point a GitHub webhook ("Workflow runs" events) at `/webhooks/github`.

**VS Code:** open the folder and accept the recommended extensions. `.vscode/` has Run/Debug
configurations for every level and the Testing panel is set up for pytest.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | Python 3.12, FastAPI | Webhook, JSON API, dashboard, health check |
| Agent | LangGraph 1.x | The retry loop with state and limits is naturally a graph |
| Tools | MCP Python SDK 2.x + github-mcp-server | One protocol for my tools and GitHub's; tools discovered at runtime |
| LLM | Any OpenAI-compatible API (Groq, Ollama, OpenRouter) or Claude | Free tier for demos, swap with one env var |
| Sandbox | Docker (docker SDK) | Isolation: no network, read-only code, limits, timeout |
| Queue | Redis + RQ | Webhook answers in milliseconds; workers do minutes of work |
| Database | Postgres, SQLAlchemy 2, Alembic | Jobs, attempts, trace steps, webhook dedupe |
| Frontend | Jinja2 + HTMX | Live dashboard without a JavaScript build |
| Tests/CI | pytest, ruff, GitHub Actions | Lint, tests, real sandbox tests, benchmark gate |
| Deploy | Docker Compose on a VM + Caddy (auto HTTPS) | Serverless cannot start Docker containers |

## Project layout

```
src/redtogreen/
  agent/graph.py                  LangGraph state machine (the brain)
  agent/prompts.py                prompts; untrusted text is wrapped and labelled
  mcp_servers/sandbox_server.py   MCP server: list/read/search/edit/run_tests
  mcp_clients/toolbox.py          MCP client: discover tools, call them, allowlist
  workspace.py                    safe file ops (no path escapes, protected files)
  policy.py                       patch rules (no test edits, small diffs)
  sandbox/docker_sandbox.py       the locked-down container
  llm/                            OpenAI-compatible + Anthropic providers, fakes for tests
  github/                         webhook parsing, git clone, GitHub MCP, fixer (Level 2)
  api/                            FastAPI app + dashboard templates (Level 3)
  worker/                         RQ queue + job processing + crash recovery
  db/                             SQLAlchemy models + session
  bench.py                        benchmark + attack runner
benchmark/                        demo repo, 30 bugs, attack set
.vscode/                          recommended extensions, debug configs, test settings
```

## License

MIT
