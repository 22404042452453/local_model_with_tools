"""
tools/sandbox_config.py — Sandbox settings via .env

Add to your .env:
    SANDBOX_ENABLED=true
    SANDBOX_IMAGE=python:3.12-slim
    SANDBOX_MEMORY=512m
    SANDBOX_CPUS=1.0
    SANDBOX_NETWORK=none          # none = no internet; bridge = internet allowed
    SANDBOX_TIMEOUT=120
"""

import os
from pathlib import Path
from tools.sandbox import DockerSandbox


def make_sandbox_from_env(workspace: Path) -> DockerSandbox | None:
    """
    Returns a DockerSandbox if SANDBOX_ENABLED=true (or auto-detected),
    otherwise returns None (→ fallback to direct subprocess).
    """
    enabled = os.getenv("SANDBOX_ENABLED", "auto").lower()

    sandbox = DockerSandbox(
        workspace = workspace,
        image     = os.getenv("SANDBOX_IMAGE",   DockerSandbox.DEFAULT_IMAGE),
        memory    = os.getenv("SANDBOX_MEMORY",  "512m"),
        cpus      = float(os.getenv("SANDBOX_CPUS", "1.0")),
        network   = os.getenv("SANDBOX_NETWORK", "none"),
        timeout   = int(os.getenv("SANDBOX_TIMEOUT", "120")),
    )

    if enabled == "true":
        return sandbox
    elif enabled == "false":
        return None
    else:
        # "auto" — use sandbox only if Docker is actually available
        return sandbox if sandbox.is_available() else None
