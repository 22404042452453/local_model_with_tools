"""
plugins/check_packages.py — Verify package availability before planning

Architect often plans with packages that aren't installed (pygame, flask, etc.).
This plugin lets the architect check availability BEFORE writing plan.md.

Usage by LLM:
    check_packages({"packages": ["tkinter", "pygame", "numpy", "flask"]})
    → "✅ tkinter (stdlib)\n❌ pygame\n✅ numpy (1.26.0)\n❌ flask"
"""

TOOL_DEFINITION = {
    "name": "check_packages",
    "description": (
        "Check if Python packages are installed. Call BEFORE writing plan.md "
        "to verify which libraries are available. "
        "ONLY use packages that return ✅ in your plan."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "packages": {
                "type": "string",
                "description": "Comma-separated package names, e.g. 'tkinter,pygame,numpy,flask'",
            },
        },
        "required": ["packages"],
    },
}

AGENTS = ["architect", "coder"]


# Standard library modules (no pip install needed)
_STDLIB = {
    "abc", "argparse", "ast", "asyncio", "base64", "bisect", "calendar",
    "cmath", "codecs", "collections", "contextlib", "copy", "csv",
    "dataclasses", "datetime", "decimal", "difflib", "email", "enum",
    "fileinput", "fnmatch", "fractions", "functools", "getpass", "glob",
    "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib",
    "inspect", "io", "itertools", "json", "keyword", "linecache",
    "locale", "logging", "math", "mimetypes", "multiprocessing",
    "operator", "os", "pathlib", "pickle", "platform", "pprint",
    "queue", "random", "re", "secrets", "shlex", "shutil", "signal",
    "socket", "sqlite3", "ssl", "statistics", "string", "struct",
    "subprocess", "sys", "tempfile", "textwrap", "threading", "time",
    "timeit", "tkinter", "traceback", "typing", "unittest", "urllib",
    "uuid", "warnings", "weakref", "xml", "zipfile", "zlib",
}


def execute(args: dict) -> str:
    import importlib.util
    import importlib.metadata

    raw = args.get("packages", "")
    if not raw.strip():
        return "No packages provided. Pass comma-separated names."

    # Parse package list
    packages = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]

    results = []
    ok = 0
    fail = 0

    for pkg in packages:
        pkg_lower = pkg.lower().replace("-", "_")

        # Check stdlib
        if pkg_lower in _STDLIB:
            results.append(f"✅ {pkg} (stdlib)")
            ok += 1
            continue

        # Check installed via importlib
        try:
            spec = importlib.util.find_spec(pkg_lower)
            if spec is not None:
                # Try to get version
                version = ""
                try:
                    version = importlib.metadata.version(pkg)
                except Exception:
                    pass
                ver_str = f" ({version})" if version else ""
                results.append(f"✅ {pkg}{ver_str}")
                ok += 1
                continue
        except (ModuleNotFoundError, ValueError):
            pass

        # Not found
        results.append(f"❌ {pkg} (not installed)")
        fail += 1

    summary = f"Checked {len(packages)}: {ok} available, {fail} missing"
    if fail > 0:
        summary += "\n⚠️  Use ONLY ✅ packages in your plan!"
    return summary + "\n" + "\n".join(results)
