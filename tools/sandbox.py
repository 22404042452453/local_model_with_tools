"""
tools/sandbox.py — Docker sandbox for safe command execution

Instead of running shell commands directly on the host,
each run_command call spawns a fresh Docker container with:
  - workspace mounted as /workspace (read-write)
  - no network access
  - memory + CPU limits
  - killed after timeout

Requires: Docker installed and running on the host.

Usage in executor.py:
    from tools.sandbox import DockerSandbox, SandboxUnavailable
    sandbox = DockerSandbox(workspace)
    result  = sandbox.run("python -m pytest tests/ -v")

Falls back to direct subprocess if Docker is unavailable.
"""

import shlex
import subprocess
import uuid
from pathlib import Path


class SandboxUnavailable(Exception):
    pass


class DockerSandbox:
    """
    Runs shell commands inside a fresh Docker container per call.

    Parameters
    ----------
    workspace   : host path that will be mounted as /workspace inside container
    image       : Docker image to use (must have python, pip, pytest available)
    memory      : memory limit (Docker format: "512m", "1g")
    cpus        : CPU quota (float: 1.0 = one core)
    network     : "none" disables internet; "bridge" allows it
    timeout     : hard kill timeout in seconds
    """

    DEFAULT_IMAGE = "python:3.12-slim"

    def __init__(
        self,
        workspace:  Path,
        image:      str   = DEFAULT_IMAGE,
        memory:     str   = "512m",
        cpus:       float = 1.0,
        network:    str   = "none",
        timeout:    int   = 120,
    ):
        self.workspace = Path(workspace).resolve()
        self.image     = image
        self.memory    = memory
        self.cpus      = str(cpus)
        self.network   = network
        self.timeout   = timeout
        self._available: bool | None = None

    # ── Availability check ────────────────────────────────────────────────────

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
            self._available = True
        except Exception:
            self._available = False
        return self._available

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, command: str, extra_timeout: int | None = None) -> str:
        """
        Execute `command` inside a sandboxed container.

        Returns a string with [exit N] prefix + stdout/stderr.
        Raises SandboxUnavailable if Docker is not running.
        """
        if not self.is_available():
            raise SandboxUnavailable("Docker is not available on this host.")

        timeout    = extra_timeout or self.timeout
        container  = f"agent-sandbox-{uuid.uuid4().hex[:8]}"

        docker_cmd = [
            "docker", "run",
            "--rm",                              # auto-remove after exit
            "--name", container,
            "--network", self.network,           # default: no internet
            "--memory", self.memory,
            "--cpus", self.cpus,
            "--workdir", "/workspace",
            "-v", f"{self.workspace}:/workspace", # mount workspace
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",                 # drop all Linux capabilities
            self.image,
            "bash", "-c", command,
        ]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (result.stdout + result.stderr).strip()
            header = f"[exit {result.returncode}] [sandbox]\n"
            return header + (out[:3000] + "…" if len(out) > 3000 else out)

        except subprocess.TimeoutExpired:
            # Force-kill the container
            subprocess.run(["docker", "kill", container],
                           capture_output=True, timeout=5)
            return f"[timeout after {timeout}s] [sandbox]"

        except Exception as e:
            return f"[sandbox error] {e}"

    # ── Pre-warm: pull image if not present ───────────────────────────────────

    def ensure_image(self) -> str:
        """Pull the image if not cached locally. Returns pull output."""
        try:
            result = subprocess.run(
                ["docker", "pull", self.image],
                capture_output=True, text=True, timeout=120
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"Pull failed: {e}"


# ── Sandbox-aware executor ────────────────────────────────────────────────────

def make_sandboxed_executor(workspace: Path, sandbox: DockerSandbox | None = None):
    """
    Like make_executor() but run_command goes through Docker sandbox.
    Falls back to direct subprocess if sandbox is None or unavailable.
    """
    from tools.executor import make_executor
    from ddgs import DDGS
    import math, json

    base_execute = make_executor(workspace)

    def execute(name: str, args: dict, memory: dict) -> tuple[str, bool]:
        if name != "run_command":
            return base_execute(name, args, memory)

        # ── Sandboxed run_command ──────────────────────────────────────────────
        command = args.get("command", "")
        timeout = min(int(args.get("timeout", 60)), 180)

        if sandbox and sandbox.is_available():
            return sandbox.run(command, extra_timeout=timeout), False
        else:
            # Fallback to direct subprocess (with workspace isolation only)
            import subprocess, shlex
            try:
                result = subprocess.run(
                    shlex.split(command),
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                out = (result.stdout + result.stderr).strip()
                return f"[exit {result.returncode}] [no-sandbox]\n" + out[:3000], False
            except subprocess.TimeoutExpired:
                return f"Timed out after {timeout}s", False
            except Exception as e:
                return f"Command error: {e}", False

    return execute
