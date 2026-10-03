"""Talks to GitHub through GitHub's official MCP server (github/github-mcp-server).

Why MCP instead of hand-written REST calls: GitHub maintains this server (auth, pagination,
API changes), and it speaks the same protocol as our sandbox server, so the agent has one
way of using tools. We enable ONLY the tools we need (least privilege).
"""

import json
import os
import re

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from redtogreen.config import Settings
from redtogreen.sandbox.base import clip

# The complete list of GitHub actions RedToGreen can perform.
GITHUB_TOOLS = [
    "get_job_logs",         # read why CI failed
    "actions_get",          # read workflow run details (CLI mode)
    "create_branch",        # make redtogreen/run-<id>
    "push_files",           # commit the fixed files to that branch
    "create_pull_request",  # ask a human to review
    "add_issue_comment",    # report back on the original PR
]


class GitHubError(Exception):
    pass


def github_client(settings: Settings) -> Client:
    if not settings.github_token:
        raise GitHubError("GITHUB_TOKEN is not set.")
    tools = ",".join(GITHUB_TOOLS)
    if settings.github_mcp_mode == "remote":
        http = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {settings.github_token}", "X-MCP-Tools": tools},
            timeout=httpx2.Timeout(60.0, read=300.0),
        )
        return Client(streamable_http_client(settings.github_mcp_url, http_client=http), read_timeout_seconds=300)

    env = {"GITHUB_PERSONAL_ACCESS_TOKEN": settings.github_token, "GITHUB_TOOLS": tools}
    if settings.github_mcp_mode == "binary":
        params = StdioServerParameters(command=settings.github_mcp_binary, args=["stdio"], env=env)
    else:
        if "DOCKER_HOST" in os.environ:
            env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
        params = StdioServerParameters(
            command="docker",
            # `-e NAME` (no value) copies the value from this process, so the token is not on the command line.
            args=["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "-e", "GITHUB_TOOLS",
                  settings.github_mcp_image, "stdio"],
            env=env,
        )
    return Client(params, read_timeout_seconds=300)


def _json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


class GitHubOps:
    def __init__(self, client: Client):
        self.client = client

    async def _call(self, name: str, args: dict) -> str:
        result = await self.client.call_tool(name, args)
        text = "\n".join(getattr(b, "text", "") for b in result.content).strip()
        if result.is_error:
            raise GitHubError(f"{name} failed: {text[:500]}")
        return text

    async def failed_logs(self, owner: str, repo: str, run_id: int, tail_lines: int = 150) -> str:
        text = await self._call("get_job_logs", {
            "owner": owner, "repo": repo, "run_id": run_id,
            "failed_only": True, "return_content": True, "tail_lines": tail_lines,
        })
        return clip(text, 8000)

    async def workflow_run(self, owner: str, repo: str, run_id: int) -> dict:
        text = await self._call("actions_get", {
            "method": "get_workflow_run", "owner": owner, "repo": repo, "resource_id": str(run_id),
        })
        data = _json(text)
        if not isinstance(data, dict):
            raise GitHubError(f"unexpected workflow run response: {text[:300]}")
        return data

    async def create_branch(self, owner: str, repo: str, branch: str, from_branch: str) -> None:
        await self._call("create_branch", {
            "owner": owner, "repo": repo, "branch": branch, "from_branch": from_branch,
        })

    async def push_files(self, owner: str, repo: str, branch: str, files: dict[str, str], message: str) -> None:
        await self._call("push_files", {
            "owner": owner, "repo": repo, "branch": branch, "message": message,
            "files": [{"path": p, "content": c} for p, c in files.items()],
        })

    async def open_pull_request(self, owner: str, repo: str, title: str, body: str, head: str,
                                base: str) -> str:
        text = await self._call("create_pull_request", {
            "owner": owner, "repo": repo, "title": title, "body": body, "head": head, "base": base,
        })
        data = _json(text)
        if isinstance(data, dict):
            for key in ("html_url", "url"):
                if isinstance(data.get(key), str) and "/pull/" in data[key]:
                    return data[key]
        match = re.search(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+", text)
        return match.group(0) if match else text[:200]

    async def comment(self, owner: str, repo: str, number: int, body: str) -> None:
        await self._call("add_issue_comment", {"owner": owner, "repo": repo, "issue_number": number,
                                               "body": body})
