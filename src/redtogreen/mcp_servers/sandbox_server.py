"""The sandbox MCP server: the agent's hands inside one job's workspace.

Run as a subprocess (stdio transport), one per job:
    python -m redtogreen.mcp_servers.sandbox_server --workspace /tmp/redtogreen-work/<job>/repo

Because it speaks MCP, any MCP client (my agent, Claude Desktop, Cursor, the MCP Inspector)
can use the same tools. The tools are the safety boundary: every path is checked, protected
files cannot be edited, and tests only run inside the sandbox.

Note: the MCP SDK starts stdio servers with a minimal environment (PATH, HOME, ...),
so API keys and the GitHub token are NOT visible to this process unless passed on purpose.
"""

import argparse
import os
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from redtogreen.config import Settings
from redtogreen.sandbox import get_sandbox
from redtogreen.workspace import Workspace, WorkspaceError

INSTRUCTIONS = (
    "Tools to inspect and edit one repository checkout and run its tests in an isolated sandbox. "
    "Paths are relative to the repository root. Test files and CI config are read-only."
)


def build_server(workspace: Workspace, settings: Settings) -> MCPServer:
    # Refused tool calls are normal (the LLM sees the reason); only log real problems.
    mcp = MCPServer("redtogreen-sandbox", instructions=INSTRUCTIONS, log_level="WARNING")
    sandbox = get_sandbox(settings)

    def guarded(fn, *args):
        try:
            return fn(*args)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def list_files(directory: str = ".") -> str:
        """List files in the repository (or in one directory of it)."""
        return "\n".join(guarded(workspace.list_files, directory)) or "(no files)"

    @mcp.tool()
    def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
        """Read a file with line numbers. end_line=0 means 'to the end' (max 400 lines per call)."""
        return guarded(workspace.read_file, path, start_line, end_line)

    @mcp.tool()
    def search_code(pattern: str, file_glob: str = "") -> str:
        """Search all files for a regular expression. Optional file_glob like '*.py'.
        Returns 'path:line: text' for each match."""
        return "\n".join(guarded(workspace.search, pattern, file_glob)) or "(no matches)"

    @mcp.tool()
    def replace_in_file(path: str, old_text: str, new_text: str) -> str:
        """Replace an exact snippet in a source file. old_text must match exactly once
        (copy it from read_file without the line numbers). Test files cannot be edited."""
        return guarded(workspace.replace_in_file, path, old_text, new_text)

    @mcp.tool()
    def show_diff() -> str:
        """Show every change made so far as a unified diff."""
        return workspace.diff() or "(no changes yet)"

    @mcp.tool()
    def run_tests() -> str:
        """Run the project's tests in the isolated sandbox (no network, no secrets, time limit)."""
        result = sandbox.run_tests(workspace.root, settings.test_command)
        return result.summary()

    @mcp.tool()
    def prepare_sandbox() -> str:
        """Install the project's dependencies into the sandbox (run once before tests)."""
        try:
            return sandbox.prepare(workspace.root)
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    # Read settings from the environment ONLY. Never from a .env file: the current directory is
    # an untrusted repo, and a malicious .env there could switch the sandbox off.
    settings = Settings(_env_file=None)
    if not args.workspace.is_dir():
        raise SystemExit(f"workspace {args.workspace} does not exist")
    server = build_server(Workspace(args.workspace, settings.protected_paths), settings)
    os.chdir(args.workspace)
    server.run("stdio")


if __name__ == "__main__":
    main()
