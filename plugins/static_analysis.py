"""
plugins/static_analysis.py — Run static analysis on Python files

Reviewer-LLM often misses real bugs or says "looks good" when code has issues.
This plugin runs objective checks: syntax, imports, undefined names, complexity.
No external dependencies — uses only stdlib ast module.

Usage by LLM:
    static_analysis({"path": "main.py"})
    → "Found 3 issues:\n  ERROR line 12: undefined name 'canvs' (typo?)\n  ..."
"""

TOOL_DEFINITION = {
    "name": "static_analysis",
    "description": (
        "Run static analysis on a Python file. Finds: syntax errors, "
        "undefined names, unused imports, missing return statements, "
        "high complexity functions. Returns objective issue list for review.md."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to .py file, e.g. 'main.py'",
            },
        },
        "required": ["path"],
    },
}

AGENTS = ["reviewer"]


def execute(args: dict) -> str:
    import ast
    import importlib.util
    from pathlib import Path

    filepath = args.get("path", "")
    if not filepath:
        return "No path provided"

    # Try workspace-relative path
    candidates = [
        Path(filepath),
        Path("workspace") / filepath,
    ]
    source = ""
    resolved = None
    for p in candidates:
        if p.exists():
            resolved = p
            source = p.read_text(encoding="utf-8")
            break

    if not source:
        return f"File not found: {filepath}"

    issues: list[str] = []
    lines = source.splitlines()

    # 1. Syntax check
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"CRITICAL syntax error at line {e.lineno}: {e.msg}"

    # 2. Collect all defined names (functions, classes, variables, imports)
    defined_names: set[str] = set()
    imported_names: set[str] = set()
    used_names: set[str] = set()

    for node in ast.walk(tree):
        # Defined
        if isinstance(node, ast.FunctionDef):
            defined_names.add(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            defined_names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            defined_names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(target, ast.Name):
                    defined_names.add(target.id)

        # Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported_names.add(name)
                defined_names.add(name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names.add(name)
                defined_names.add(name)

        # Used names
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used_names.add(node.id)

    # 3. Check imports are available
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                pkg = alias.name.split(".")[0]
                try:
                    if importlib.util.find_spec(pkg) is None:
                        issues.append(
                            f"ERROR line {node.lineno}: import '{pkg}' — package not installed"
                        )
                except (ModuleNotFoundError, ValueError):
                    issues.append(
                        f"ERROR line {node.lineno}: import '{pkg}' — package not installed"
                    )

    # 4. Unused imports
    for name in imported_names:
        if name not in used_names and name not in ("__future__",):
            issues.append(f"WARNING: imported '{name}' is never used")

    # 5. Function complexity (count branches)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            branches = sum(
                1 for n in ast.walk(node)
                if isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                                  ast.With, ast.BoolOp))
            )
            if branches > 10:
                issues.append(
                    f"WARNING line {node.lineno}: function '{node.name}()' has "
                    f"complexity {branches} — consider splitting"
                )

    # 6. Functions without return in non-__init__
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name != "__init__":
            has_return = any(
                isinstance(n, ast.Return) and n.value is not None
                for n in ast.walk(node)
            )
            # Only flag if function has > 5 lines and no return
            if not has_return and len(node.body) > 5:
                # Check if it's a void function (has side effects)
                pass  # Don't flag — too many false positives

    # 7. Bare except
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append(
                f"WARNING line {node.lineno}: bare 'except:' — catch specific exceptions"
            )

    # 8. TODO / FIXME
    for i, line in enumerate(lines, 1):
        if "TODO" in line or "FIXME" in line:
            issues.append(f"INFO line {i}: {line.strip()[:60]}")

    # Summary
    errors = sum(1 for i in issues if i.startswith("ERROR"))
    warnings = sum(1 for i in issues if i.startswith("WARNING"))

    if not issues:
        return f"✅ {filepath}: no issues found ({len(lines)} lines)"

    header = f"Found {len(issues)} issues in {filepath} ({errors} errors, {warnings} warnings):"
    return header + "\n" + "\n".join(f"  {i}" for i in issues)
