"""
core/file_builder.py — Build files skeleton-first, function-by-function

Spec-First approach (Self-Spec paper, 2025):
  Instead of writing the whole file in one LLM call, we split into two phases:

  Phase 1 — Skeleton (one LLM call, ~20 lines):
      Write ONLY: module docstring + imports + class/function signatures + docstrings + pass
      Small model writes this perfectly. Pipeline parses it with AST → extracts signatures.

  Phase 2 — Implement (one LLM call per function, ~10-15 lines each):
      "Here is the skeleton. Implement ONLY function X — write its body."
      Each function validated independently. Errors caught at function level.

  Assembly: FileBuilder.assemble() combines all pieces into the final file.

Usage in step_pipeline:
    # Phase 1: coder writes skeleton
    skeleton_code = read "_skeleton_main.py"
    specs = parse_skeleton(skeleton_code)   # → list[FunctionSpec]

    # Phase 2: coder implements each function
    for spec in specs:
        implement_step(spec) → writes body to context

    # Assembly
    assemble_from_context("main.py", workspace, context)
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.step_agent import Step


# ── Skeleton parser ───────────────────────────────────────────────────────────

@dataclass
class FunctionSpec:
    """A function/method extracted from a skeleton file."""
    name:       str
    signature:  str          # full "def func(args) -> ret:" line
    docstring:  str          # extracted docstring if present
    class_name: str = ""     # set if this is a method
    is_class:   bool = False # True if this is a class definition
    order:      int  = 0


def parse_skeleton(skeleton_code: str) -> list[FunctionSpec]:
    """
    Parse a skeleton .py file (stubs with pass/docstrings) and extract
    FunctionSpec for every function and class.

    Designed to be robust — falls back gracefully if AST parsing fails.
    """
    specs: list[FunctionSpec] = []
    skeleton_code = _strip_fences(skeleton_code)

    try:
        tree = ast.parse(skeleton_code)
    except SyntaxError:
        # Skeleton has syntax errors — fall back to regex extraction
        return _regex_parse_skeleton(skeleton_code)

    lines = skeleton_code.splitlines()

    def _src_line(node) -> str:
        """Get the source line for a function/class def."""
        if hasattr(node, "lineno") and node.lineno <= len(lines):
            return lines[node.lineno - 1].strip()
        return ""

    def _get_docstring(node) -> str:
        """Extract docstring from a function/class body."""
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            return node.body[0].value.value.strip()
        return ""

    order = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            specs.append(FunctionSpec(
                name=node.name,
                signature=f"class {node.name}:",
                docstring=_get_docstring(node),
                is_class=True,
                order=order,
            ))
            order += 1
            # Extract methods
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = _src_line(item)
                    specs.append(FunctionSpec(
                        name=item.name,
                        signature=sig,
                        docstring=_get_docstring(item),
                        class_name=node.name,
                        order=order,
                    ))
                    order += 1

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Top-level functions only (not methods — handled above)
            parent_is_class = any(
                isinstance(p, ast.ClassDef) and node in ast.walk(p)
                for p in ast.walk(tree)
                if p is not node
            )
            if not parent_is_class:
                sig = _src_line(node)
                specs.append(FunctionSpec(
                    name=node.name,
                    signature=sig,
                    docstring=_get_docstring(node),
                    order=order,
                ))
                order += 1

    # Deduplicate by name (ast.walk visits nested nodes multiple times)
    seen: set[str] = set()
    unique: list[FunctionSpec] = []
    for s in sorted(specs, key=lambda x: x.order):
        key = f"{s.class_name}.{s.name}" if s.class_name else s.name
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique


def _regex_parse_skeleton(code: str) -> list[FunctionSpec]:
    """Fallback regex parser when AST fails."""
    specs = []
    order = 0
    current_class = ""

    for line in code.splitlines():
        stripped = line.strip()
        class_match = re.match(r'class\s+(\w+)', stripped)
        if class_match:
            current_class = class_match.group(1)
            specs.append(FunctionSpec(
                name=current_class, signature=stripped,
                docstring="", is_class=True, order=order,
            ))
            order += 1
            continue

        func_match = re.match(r'(?:async\s+)?def\s+(\w+)\s*\(', stripped)
        if func_match:
            fname = func_match.group(1)
            specs.append(FunctionSpec(
                name=fname, signature=stripped,
                docstring="", class_name=current_class, order=order,
            ))
            order += 1

    return specs


@dataclass
class FilePiece:
    """One piece of a file: imports, class, function, or raw block."""
    kind:    str   # "imports", "class", "function", "block", "main_guard"
    name:    str   # e.g. "generate_stars", "Star", "imports"
    code:    str
    order:   int = 0  # for sorting


class FileBuilder:
    """
    Assembles a Python file from individual pieces.
    Each piece is generated by a separate LLM call.
    """

    def __init__(self, filepath: str, workspace: Path):
        self.filepath  = filepath
        self.workspace = workspace
        self.pieces:    list[FilePiece] = []
        self.docstring: str = ""

    def add_piece(self, kind: str, name: str, code: str, order: int = 0) -> None:
        # Clean up code — strip markdown fences if model added them
        code = _strip_fences(code)
        self.pieces.append(FilePiece(kind=kind, name=name, code=code, order=order))

    def set_docstring(self, doc: str) -> None:
        self.docstring = doc

    def assemble(self) -> str:
        """
        Combine all pieces into a valid Python file.
        Order: docstring → imports → classes → functions → main guard
        """
        sections: list[str] = []

        # Module docstring
        if self.docstring:
            sections.append(f'"""\n{self.docstring}\n"""')

        # Sort pieces by kind priority, then by order
        kind_priority = {"imports": 0, "class": 1, "function": 2, "block": 3, "main_guard": 99}
        sorted_pieces = sorted(self.pieces,
                                key=lambda p: (kind_priority.get(p.kind, 50), p.order))

        # Merge imports into one block
        import_lines: list[str] = []
        for p in sorted_pieces:
            if p.kind == "imports":
                import_lines.extend(p.code.strip().splitlines())

        if import_lines:
            # Deduplicate imports
            seen = set()
            unique = []
            for line in import_lines:
                stripped = line.strip()
                if stripped and stripped not in seen:
                    seen.add(stripped)
                    unique.append(stripped)
            sections.append("\n".join(unique))

        # Non-import pieces
        for p in sorted_pieces:
            if p.kind != "imports":
                sections.append(p.code.strip())

        content = "\n\n\n".join(sections) + "\n"

        # Write to disk
        target = self.workspace / self.filepath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        return content

    def validate(self) -> tuple[bool, str]:
        """Check assembled file for syntax errors."""
        target = self.workspace / self.filepath
        if not target.exists():
            return False, "File not assembled yet"
        try:
            source = target.read_text(encoding="utf-8")
            ast.parse(source)
            return True, f"OK: {len(source)} chars, {len(source.splitlines())} lines"
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"


# ── Step generators for function-level building ───────────────────────────────

def build_file_steps(
    task: str,
    filepath: str,
    description: str,
    functions: list[dict],
    file_num: int = 0,
    total_files: int = 0,
) -> list[Step]:
    """
    Generate steps to build a file function-by-function.

    functions: [
        {"name": "generate_stars", "desc": "Returns list of Star dicts with x,y,brightness"},
        {"name": "create_app",    "desc": "Sets up FastAPI app with routes"},
    ]
    """
    num_label = f"[File {file_num}/{total_files}] " if file_num else ""
    steps = []

    # Step 1: Write imports
    steps.append(Step(
        prompt=(
            f"{num_label}Write ONLY the import statements for {filepath}\n"
            f"File purpose: {description}\n"
            f"Functions that will be in this file: {', '.join(f['name'] for f in functions)}\n\n"
            f"Write ONLY imports, nothing else.\n"
            f"Call write_file(path=\"_piece_imports.py\", content=\"import ...\")"
        ),
        expect="write_file",
        required=False,
        max_retries=1,
        on_result=lambda r, ctx: ctx.setdefault("_pieces", []).append(
            {"kind": "imports", "name": "imports", "code": _extract_written_content(r, ctx), "order": 0}
        ),
    ))

    # Step per function
    for i, func in enumerate(functions):
        fname = func["name"]
        fdesc = func.get("desc", "")
        steps.append(Step(
            prompt=(
                f"{num_label}Write ONLY the function `{fname}` for {filepath}\n"
                f"Function purpose: {fdesc}\n"
                f"Write the complete function with docstring. No imports, no other code.\n"
                f"Call write_file(path=\"_piece_{fname}.py\", content=\"def {fname}(...):\")"
            ),
            expect="write_file",
            required=False,
            max_retries=2,
            on_result=lambda r, ctx, fn=fname, idx=i: ctx.setdefault("_pieces", []).append(
                {"kind": "function", "name": fn, "code": _extract_written_content(r, ctx), "order": idx+1}
            ),
        ))

    # No assembly step here — pipeline does it after all steps complete

    return steps


def assemble_from_context(
    filepath:      str,
    workspace:     Path,
    context:       dict,
    docstring:     str = "",
    skeleton_code: str = "",
) -> tuple[bool, str]:
    """
    Assemble file from pieces stored in context by implement_steps.
    Optionally takes skeleton_code to extract imports from it.
    Returns (success, message).
    """
    pieces = context.get("_pieces", [])

    builder = FileBuilder(filepath, workspace)
    if docstring:
        builder.set_docstring(docstring)

    # Extract imports from skeleton (they won't be in _pieces)
    if skeleton_code:
        import_lines = _extract_imports_from_skeleton(skeleton_code)
        if import_lines:
            builder.add_piece("imports", "imports", "\n".join(import_lines), order=0)

    if not pieces and not skeleton_code:
        return False, "No pieces generated"

    for p in pieces:
        kind  = p.get("kind", "function")
        name  = p.get("name", "unknown")
        code  = p.get("code", "")
        order = p.get("order", 0)
        if code.strip():
            builder.add_piece(kind, name, code, order)

    if not builder.pieces:
        return False, "All pieces were empty"

    content = builder.assemble()
    ok, msg = builder.validate()

    if not ok:
        content = _auto_fix_common(content)
        target = workspace / filepath
        target.write_text(content, encoding="utf-8")
        ok, msg = builder.validate()

    return ok, msg


def _extract_imports_from_skeleton(skeleton_code: str) -> list[str]:
    """Pull import lines from skeleton code."""
    import_lines = []
    for line in skeleton_code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            import_lines.append(stripped)
    return import_lines


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_fences(code: str) -> str:
    """Remove markdown code fences."""
    code = re.sub(r'^```\w*\n', '', code)
    code = re.sub(r'\n```$', '', code)
    return code.strip()


def _extract_written_content(result: str, context: dict) -> str:
    """
    Extract the actual code from a write_file result.
    The result is "Written N chars -> path" — we need to read the file.
    """
    # The code was written to a _piece_*.py file — read it back
    match = re.search(r'-> (.+)$', result)
    if match:
        piece_path = match.group(1).strip()
        workspace = context.get("_workspace")
        if workspace:
            try:
                full = Path(workspace) / piece_path.lstrip("/\\")
                if full.exists():
                    return full.read_text(encoding="utf-8")
            except Exception:
                pass
    return ""


def _auto_fix_common(content: str) -> str:
    """Fix common assembly issues."""
    lines = content.splitlines()
    fixed = []
    for line in lines:
        # Remove duplicate blank lines (more than 2)
        if not line.strip() and fixed and not fixed[-1].strip():
            if len(fixed) >= 2 and not fixed[-2].strip():
                continue
        fixed.append(line)
    return "\n".join(fixed)


# ── Plan parser for function extraction ───────────────────────────────────────

def extract_functions_from_plan(plan_text: str, filename: str) -> list[dict]:
    """
    Extract function/class names and descriptions for a file from plan.md.

    Looks for patterns like:
        ### `main.py`
        - Function `generate_stars(count)`: creates N stars
        - Class `StarField`: manages star collection
        - `create_app()`: sets up FastAPI

    Returns [{"name": "generate_stars", "desc": "creates N stars"}, ...]
    """
    functions = []
    basename = filename.split("/")[-1]

    # Find the section for this file
    escaped = re.escape(basename)
    pattern = rf'###?\s*[`\*]*{escaped}[`\*]*\s*\n((?:[-\s*].*\n)*)'

    for m in re.finditer(pattern, plan_text):
        section = m.group(1)
        for line in section.splitlines():
            line = line.strip().lstrip("- *")
            if not line:
                continue

            # Pattern: Function `name(args)`: description
            func_match = re.match(
                r'(?:Function|Func|Method|Метод|Функция)?\s*`?(\w+)\([^)]*\)`?\s*[:\-–]\s*(.*)',
                line, re.IGNORECASE
            )
            if func_match:
                functions.append({
                    "name": func_match.group(1),
                    "desc": func_match.group(2).strip(),
                })
                continue

            # Pattern: Class `Name`: description
            class_match = re.match(
                r'(?:Class|Класс)\s*`?(\w+)`?\s*[:\-–]\s*(.*)',
                line, re.IGNORECASE
            )
            if class_match:
                functions.append({
                    "name": class_match.group(1),
                    "desc": class_match.group(2).strip(),
                })

    return functions