"""tools/executor.py — unified tool executor with plugin support"""

import json
import math
import shlex
import subprocess
from pathlib import Path

from ddgs import DDGS
from tools.env_tools import get_env_info, read_env_file


def make_executor(workspace: Path, plugin_registry=None):
    """
    Returns executor(name, args, memory) -> (result_str, is_finished).
    If plugin_registry is provided, plugin tools are checked first.
    """

    def execute(name: str, args: dict, memory: dict) -> tuple[str, bool]:

        # Check plugins first
        if plugin_registry and plugin_registry.has(name):
            result = plugin_registry.execute(name, args)
            return result, False

        # Built-in tools
        if name == "web_search":
            try:
                results = list(DDGS().text(args["query"], max_results=5))
                if not results: return "No results found.", False
                return "\n\n".join(f"[{r['title']}]\n{r['body']}" for r in results), False
            except Exception as e:
                return f"Search error: {e}", False

        elif name == "calculate":
            try:
                env = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
                env["__builtins__"] = {}
                return str(eval(args["expression"], env)), False
            except Exception as e:
                return f"Error: {e}", False

        # ── File ops ──────────────────────────────────────────────────────────
        elif name == "read_file":
            if "path" not in args or not args["path"]:
                return "Error: 'path' argument is required. Example: read_file({\"path\": \"main.py\"})", False
            # Normalize: strip leading slash/backslash (model sometimes sends /plan.md)
            rel = args["path"].lstrip("/\\")
            path = _safe(rel, workspace)
            if path is None: return "Error: path escapes workspace.", False
            try:    return path.read_text(encoding="utf-8"), False
            except FileNotFoundError: return f"File not found: {rel}", False
            except Exception as e:    return f"Read error: {e}", False

        elif name == "write_file":
            if "path" not in args or not args["path"]:
                return "Error: 'path' argument is required. Example: write_file({\"path\": \"main.py\", \"content\": \"...\"})", False
            if "content" not in args:
                return "Error: 'content' argument is required.", False
            rel  = args["path"].lstrip("/\\")
            path = _safe(rel, workspace)
            if path is None: return "Error: path escapes workspace.", False
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(args["content"], encoding="utf-8")
                return f"Written {len(args['content'])} chars -> {rel}", False
            except Exception as e:
                return f"Write error: {e}", False

        elif name == "list_files":
            files = sorted(f for f in workspace.rglob("*") if f.is_file())
            if not files: return "(workspace is empty)", False
            return "\n".join(
                f"  {f.relative_to(workspace)}  ({f.stat().st_size}B)" for f in files
            ), False

        elif name == "edit_file":
            if "path" not in args or not args["path"]:
                return "Error: 'path' argument is required.", False
            rel  = args["path"].lstrip("/\\")
            path = _safe(rel, workspace)
            if path is None: return "Error: path escapes workspace.", False
            try:
                content = path.read_text(encoding="utf-8")
                find    = args["find"]
                replace = args["replace"]
                if find not in content:
                    return f"Error: string not found in {rel}. Make sure 'find' matches exactly.", False
                count = content.count(find)
                new_content = content.replace(find, replace, 1)
                path.write_text(new_content, encoding="utf-8")
                return f"Edited {rel}: replaced 1 of {count} occurrence(s) ({len(new_content)} chars total)", False
            except FileNotFoundError:
                return f"File not found: {rel}", False
            except Exception as e:
                return f"Edit error: {e}", False

        elif name == "delete_file":
            rel  = args["path"].lstrip("/\\")
            path = _safe(rel, workspace)
            if path is None: return "Error: path escapes workspace.", False
            try:
                if not path.exists():
                    return f"File not found: {rel}", False
                size = path.stat().st_size
                path.unlink()
                return f"Deleted {rel} ({size}B)", False
            except Exception as e:
                return f"Delete error: {e}", False

        elif name == "run_command":
            timeout = min(int(args.get("timeout", 60)), 180)
            try:
                result = subprocess.run(
                    shlex.split(args["command"]), cwd=workspace,
                    capture_output=True, text=True, timeout=timeout
                )
                out = (result.stdout + result.stderr).strip()
                header = f"[exit {result.returncode}]\n"
                return header + (out[:3000] + "..." if len(out) > 3000 else out), False
            except subprocess.TimeoutExpired:
                return f"Timed out after {timeout}s", False
            except Exception as e:
                return f"Command error: {e}", False

        elif name == "get_env_info":
            return get_env_info(args), False

        elif name == "read_env_file":
            return read_env_file(workspace), False

        elif name == "remember":
            memory[args["key"]] = args["value"]
            return f"Stored: {args['key']!r} = {args['value']!r}", False

        elif name == "recall":
            val = memory.get(args["key"])
            return str(val) if val is not None else f"Not found: {args['key']!r}", False

        elif name == "finish":
            payload = {"summary": args.get("summary", ""), "verdict": args.get("verdict", "PASS")}
            return json.dumps(payload), True

        return f"Unknown tool: {name!r}", False

    return execute


def _safe(rel_path: str, workspace: Path) -> Path | None:
    target = (workspace / rel_path).resolve()
    return target if str(target).startswith(str(workspace.resolve())) else None