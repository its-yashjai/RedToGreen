"""All settings in one place, read from environment variables (or a .env file).

Every limit the agent obeys lives here, so "how do you stop it running forever?"
has a one-line answer: MAX_ATTEMPTS, MAX_STEPS_PER_ATTEMPT and SANDBOX_TIMEOUT_S.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Where benchmark/, sandbox/, migrations/ live (the repo root, or /app inside Docker).
PROJECT_ROOT = Path(os.environ.get("REDTOGREEN_ROOT", Path(__file__).resolve().parents[2]))

# Files the agent may never change. If it could edit tests, the easiest "fix"
# for a failing test would be to delete the test (reward hacking).
DEFAULT_PROTECTED = [
    "tests/*",
    "test/*",
    "**/tests/*",
    "test_*.py",
    "**/test_*.py",
    "*_test.py",
    "**/*_test.py",
    "conftest.py",
    "**/conftest.py",
    ".github/*",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "pyproject.toml",
    "requirements*.txt",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM ---
    llm_provider: Literal["openai_compat", "anthropic", "fake"] = "openai_compat"
    llm_model: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_price_input_per_mtok: float = 0.0
    llm_price_output_per_mtok: float = 0.0
    llm_max_output_tokens: int = 16000
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_fallbacks: bool = True

    # --- Agent limits ---
    max_attempts: int = 3
    max_steps_per_attempt: int = 15
    max_changed_files: int = 3
    max_changed_lines: int = 80
    protected_paths: list[str] = Field(default_factory=lambda: list(DEFAULT_PROTECTED))

    # --- Sandbox ---
    sandbox_backend: Literal["docker", "local"] = "docker"
    sandbox_image: str = "redtogreen-sandbox:latest"
    sandbox_timeout_s: int = 120
    sandbox_install_timeout_s: int = 300
    sandbox_memory: str = "512m"
    sandbox_cpus: float = 1.0
    sandbox_pids_limit: int = 256
    # Optional hardened runtime, e.g. "runsc" if gVisor is installed on the host.
    sandbox_runtime: str = ""
    test_command: str = "python -m pytest -q -p no:cacheprovider"
    workdir: Path = Path("/tmp/redtogreen-work")

    # --- GitHub ---
    github_token: str = ""
    github_mcp_mode: Literal["docker", "binary", "remote"] = "docker"
    github_mcp_image: str = "ghcr.io/github/github-mcp-server"
    github_mcp_binary: str = "github-mcp-server"
    github_mcp_url: str = "https://api.githubcopilot.com/mcp/"
    fix_branch_prefix: str = "redtogreen/"
    allowed_repos: str = ""

    # --- Server ---
    github_webhook_secret: str = ""
    admin_token: str = ""
    public_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./redtogreen.db"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "redtogreen"
    job_timeout_s: int = 1800
    stale_job_minutes: int = 45

    def allowed_repo_set(self) -> set[str]:
        return {r.strip().lower() for r in self.allowed_repos.split(",") if r.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
