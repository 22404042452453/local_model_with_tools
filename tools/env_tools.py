"""tools/env_tools.py — Python environment & .env inspection"""

import os
import platform
import subprocess
import sys
from pathlib import Path


def get_env_info(args: dict) -> str:
    include_packages = args.get("include_packages", True)
    lines = [
        f"Python: {sys.version}",
        f"Platform: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Executable: {sys.executable}",
    ]

    if include_packages:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=columns"],
                capture_output=True, text=True, timeout=15
            )
            lines.append("\n── Installed packages ──")
            lines.append(result.stdout.strip())
        except Exception as e:
            lines.append(f"pip list failed: {e}")

    return "\n".join(lines)


def read_env_file(workspace: Path) -> str:
    candidates = [workspace / ".env", Path(".env")]
    for path in candidates:
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                # Mask values that look like secrets (API keys, passwords, tokens)
                masked_lines = []
                for line in content.splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip()
                        # Mask if key contains secret-ish words
                        secret_words = {"key", "secret", "token", "password", "pwd",
                                        "pass", "credential", "auth", "private"}
                        if any(w in key.lower() for w in secret_words) and len(val) > 4:
                            val = val[:4] + "***"
                        masked_lines.append(f"{key}={val}")
                    else:
                        masked_lines.append(line)
                return f"# {path}\n" + "\n".join(masked_lines)
            except Exception as e:
                return f"Error reading {path}: {e}"
    return "No .env file found in workspace."
