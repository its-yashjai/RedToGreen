"""Where untrusted code (the repo's tests) actually runs.

The agent never depends on Docker directly: it depends on the `Sandbox` interface.
That is why another backend (gVisor, Firecracker, NVIDIA OpenShell...) could be swapped
in later without touching the agent.
"""

from redtogreen.config import Settings
from redtogreen.sandbox.base import RunResult, Sandbox


def get_sandbox(settings: Settings) -> Sandbox:
    if settings.sandbox_backend == "docker":
        from redtogreen.sandbox.docker_sandbox import DockerSandbox

        return DockerSandbox(settings)
    from redtogreen.sandbox.local_sandbox import LocalSandbox

    return LocalSandbox(settings)


__all__ = ["Sandbox", "RunResult", "get_sandbox"]
