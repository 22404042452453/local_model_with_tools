"""
plugins/check_imports.py — Verify Python imports before/after writing code

The #1 failure mode: coder writes `import pygame` but pygame is not installed.
This plugin lets the coder check imports BEFORE writing the file.

Usage by LLM:
    check_imports({"code": "import tkinter\nimport pygame\nfrom pathlib import Path"})
    → "✅ tkinter\n❌ pygame (not installed)\n✅ pathlib"
"""

TOOL_DEFINITION = {
    "name": "check_imports",
    "description": (
        "Check if Python imports are available in the current environment. "
        "Call BEFORE writing code to verify all imports will work. "
        "Pass the import lines or full code — returns ✅/❌ per package."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code or import lines to check, e.g. 'import tkinter\\nimport pygame'",
            },
        },
        "required": ["code"],
    },
}

AGENTS = ["coder", "architect"]


def execute(args: dict) -> str:
    import ast
    import importlib.util

    code = args.get("code", "")
    if not code.strip():
        return "No code provided"

    # Extract import names from code
    packages: list[str] = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    packages.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                packages.append(node.module.split(".")[0])
    except SyntaxError:
        # Fallback: regex extraction
        import re
        for line in code.splitlines():
            line = line.strip()
            m = re.match(r'^(?:from\s+(\w+)|import\s+(\w+))', line)
            if m:
                packages.append(m.group(1) or m.group(2))

    if not packages:
        return "No imports found in code"

    # Deduplicate
    seen = set()
    unique = []
    for p in packages:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    # Check each package
    results = []
    ok_count = 0
    fail_count = 0
    for pkg in unique:
        try:
            spec = importlib.util.find_spec(pkg)
            if spec is not None:
                results.append(f"✅ {pkg}")
                ok_count += 1
            else:
                results.append(f"❌ {pkg} (not installed)")
                fail_count += 1
        except (ModuleNotFoundError, ValueError):
            results.append(f"❌ {pkg} (not installed)")
            fail_count += 1

    summary = f"Checked {len(unique)} packages: {ok_count} OK, {fail_count} FAIL"
    return summary + "\n" + "\n".join(results)
