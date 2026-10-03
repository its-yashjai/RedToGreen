"""MCP client side: connect to an MCP server, discover its tools, call them.

The agent does not hard-code tool definitions. It asks the server "what tools do you have?"
(tools/list) and converts the JSON Schemas into the format the LLM provider expects.
Add a tool to the server and the agent can use it without changing agent code.
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp import Client, StdioServerParameters

from redtogreen.config import Settings
from redtogreen.llm.base import ToolSpec

# Tools the LLM may call. run_tests / prepare_sandbox stay with the graph, so the LLM
# cannot burn time and money by running the test suite in a loop.
LLM_SANDBOX_TOOLS = {"list_files", "read_file", "search_code", "replace_in_file", "show_diff"}

# Non-secret settings forwarded to the sandbox server process.
FORWARDED_ENV = [
    "SANDBOX_BACKEND", "SANDBOX_IMAGE", "SANDBOX_TIMEOUT_S", "SANDBOX_INSTALL_TIMEOUT_S",
    "SANDBOX_MEMORY", "SANDBOX_CPUS", "SANDBOX_PIDS_LIMIT", "SANDBOX_RUNTIME", "TEST_COMMAND",
    "PROTECTED_PATHS", "DOCKER_HOST",
]


@dataclass
class ToolOutput:
    text: str
    is_error: bool


class Toolbox:
    """A connected MCP client plus an allowlist of tools."""

    def __init__(self, client: Client, allowed: set[str] | None = None):
        self.client = client
        self.allowed = allowed

    async def specs(self) -> list[ToolSpec]:
        result = await self.client.list_tools()
        return [
            ToolSpec(name=t.name, description=t.description or "", input_schema=t.input_schema)
            for t in result.tools
            if self.allowed is None or t.name in self.allowed
        ]

    async def call(self, name: str, arguments: dict) -> ToolOutput:
        if self.allowed is not None and name not in self.allowed:
            return ToolOutput(f"Tool '{name}' is not available.", True)
        result = await self.client.call_tool(name, arguments)
        text = "\n".join(getattr(block, "text", "") for block in result.content).strip()
        return ToolOutput(text or "(empty result)", bool(result.is_error))


def sandbox_server_params(workspace: Path, settings: Settings) -> StdioServerParameters:
    env = {k: os.environ[k] for k in FORWARDED_ENV if k in os.environ}
    # Settings may come from .env rather than the process environment; forward the effective values.
    env.update({
        "SANDBOX_BACKEND": settings.sandbox_backend,
        "SANDBOX_IMAGE": settings.sandbox_image,
        "SANDBOX_TIMEOUT_S": str(settings.sandbox_timeout_s),
        "SANDBOX_INSTALL_TIMEOUT_S": str(settings.sandbox_install_timeout_s),
        "SANDBOX_MEMORY": settings.sandbox_memory,
        "SANDBOX_CPUS": str(settings.sandbox_cpus),
        "SANDBOX_PIDS_LIMIT": str(settings.sandbox_pids_limit),
        "SANDBOX_RUNTIME": settings.sandbox_runtime,
        "TEST_COMMAND": settings.test_command,
        "PROTECTED_PATHS": json.dumps(settings.protected_paths),
    })
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "redtogreen.mcp_servers.sandbox_server", "--workspace", str(workspace)],
        env=env,
        cwd=str(workspace),
    )


@asynccontextmanager
async def open_sandbox(workspace: Path, settings: Settings):
    """Start the sandbox MCP server for this workspace and yield a Client connected to it."""
    async with Client(sandbox_server_params(workspace, settings), read_timeout_seconds=600) as client:
        yield client
