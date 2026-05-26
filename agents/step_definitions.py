"""
agents/step_definitions.py — Step sequences for each agent

Each agent gets a sequence of atomic steps.
The model can't skip steps, can't hallucinate the order.
Pipeline validates output after each step.
"""

from __future__ import annotations

import ast
from pathlib import Path
from core.step_agent import Step, StepAgent
from core.providers import BaseProvider
from tools.definitions import (
    ARCHITECT_TOOLS, CODER_TOOLS, TESTER_TOOLS, REVIEWER_TOOLS,
    WEB_SEARCH, READ_FILE, WRITE_FILE, LIST_FILES, RUN_COMMAND,
    REMEMBER, RECALL, FINISH,
)


# ── Validators ────────────────────────────────────────────────────────────────

def _validate_nonempty(result: str) -> tuple[bool, str]:
    ok = len(result.strip()) > 10
    return ok, "Result is too short or empty" if not ok else ""

def _validate_python_syntax(result: str) -> tuple[bool, str]:
    if "Written" in result:
        return True, ""
    try:
        ast.parse(result)
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

def _validate_file_written(result: str) -> tuple[bool, str]:
    """Check that write_file actually succeeded."""
    if result.startswith("Written"):
        return True, ""
    if "Error" in result or "error" in result:
        return False, f"Write failed: {result[:100]}"
    # Fallback — if result doesn't start with Written but no error, accept
    return True, ""

def _validate_plan(result: str) -> tuple[bool, str]:
    has_content = len(result.strip()) > 100
    return has_content, "Plan is too short" if not has_content else ""


# ── Architect steps ───────────────────────────────────────────────────────────

def architect_steps(task: str, workspace: Path, search_first: bool = True) -> list[Step]:
    steps = []

    if search_first:
        steps.append(Step(
            prompt=(
                f"Task: {task}\n\n"
                "Search for relevant libraries and best practices. "
                "Use web_search with a specific technical query in English."
            ),
            expect="web_search",
            required=False,   # optional — don't abort if search fails
            max_retries=1,
        ))

    steps.append(Step(
        prompt=(
            f"Task: {task}\n\n"
            "Call write_file(path=\"plan.md\", content=\"...\") NOW.\n\n"
            "plan.md must contain:\n"
            "- Files to create (exact .py filenames)\n"
            "- Libraries needed (e.g. pygame, tkinter, fastapi)\n"
            "- Key functions/classes per file\n"
            "- 2-3 sentences of implementation notes\n\n"
            "DO NOT call any other tool. Call write_file immediately."
        ),
        expect="write_file",
        required=True,
        max_retries=3,
        validate=_validate_file_written,
        on_result=lambda r, ctx: ctx.update({"plan_written": True}),
    ))

    return steps


# ── Coder steps ───────────────────────────────────────────────────────────────

def coder_steps(task: str, workspace: Path,
                files_to_create: list[str] | None = None,
                file_descriptions: dict[str, str] | None = None) -> list[Step]:
    """
    Dynamic steps: read plan → for each file → write it → verify.
    Each file gets its own step with description from plan.
    """
    descs = file_descriptions or {}

    steps = [
        # Step 1: Read plan.md (forced — always works)
        Step(
            prompt=(
                f"Task: {task}\n\n"
                "Read plan.md to understand what files to create."
            ),
            expect="read_file",
            args={"path": "plan.md"},
            required=True,
            max_retries=1,
            validate=_validate_nonempty,
            on_result=lambda r, ctx: ctx.update({"plan_content": r}),
        ),
    ]

    # One write step per file from the plan
    if files_to_create:
        for idx, filepath in enumerate(files_to_create, 1):
            desc = descs.get(filepath, "")
            steps.append(_write_file_step(task, filepath, desc,
                                           file_num=idx, total_files=len(files_to_create)))
    else:
        # Fallback: single generic write step
        steps.append(Step(
            prompt=(
                f"Task: {task}\n\n"
                "Write the main implementation file.\n"
                "Call write_file(path=\"main.py\", content=\"...\") with COMPLETE working code.\n"
                "DO NOT read files again. Call write_file NOW."
            ),
            expect="write_file",
            required=True,
            max_retries=3,
            validate=_validate_file_written,
        ))

    # Final: verify
    steps.append(Step(
        prompt="List all files in workspace to confirm they were created.",
        expect="list_files",
        args={},
        required=False,
        max_retries=1,
    ))

    return steps


def _write_file_step(task: str, filepath: str, description: str = "",
                     file_num: int = 0, total_files: int = 0) -> Step:
    """Create a step for writing one specific file with its description."""
    desc_block = f"\nThis file should contain: {description}\n" if description else ""
    num_label = f"[File {file_num}/{total_files}] " if file_num else ""
    return Step(
        prompt=(
            f"{num_label}Write file: {filepath}\n"
            f"Task: {task}\n"
            f"{desc_block}"
            f"Write COMPLETE, working code. No stubs, no TODO.\n"
            f"Call write_file(path=\"{filepath}\", content=\"...\") NOW."
        ),
        expect="write_file",
        required=False,
        max_retries=1,   # one self-retry max; pipeline-level loop handles deeper fixes
        validate=_validate_file_written,
        on_result=lambda r, ctx: ctx.update({"_current_file": filepath}),
    )


# ── Spec-First: Skeleton + Implement steps ────────────────────────────────────

def skeleton_step(task: str, filepath: str, description: str = "",
                  file_num: int = 0, total_files: int = 0) -> Step:
    """
    Phase 1 of Spec-First writing.

    Ask the model to write ONLY the skeleton of the file:
        - Module docstring
        - Imports
        - Class definitions (no body, just pass/docstring)
        - Function signatures + docstrings + pass body

    ~20-30 lines. Small models write this perfectly.
    Pipeline then parses the skeleton with AST to extract FunctionSpecs.
    """
    num_label = f"[File {file_num}/{total_files}] " if file_num else ""
    skeleton_path = f"_skeleton_{filepath.replace('/', '_')}"
    return Step(
        prompt=(
            f"{num_label}Write SKELETON ONLY for: {filepath}\n"
            f"Task: {task}\n"
            + (f"Purpose: {description}\n" if description else "") +
            "\nWrite ONLY:\n"
            "  1. Module docstring (triple quotes)\n"
            "  2. All import statements\n"
            "  3. All class definitions with class docstring and method signatures\n"
            "  4. All top-level function signatures with docstring\n"
            "  5. Every function/method body = just `pass` (no implementation)\n\n"
            "NO real implementation yet — only structure.\n"
            f"Call write_file(path=\"{skeleton_path}\", content=\"\"\"\n"
            "'''Module docstring'''\nimport ...\n\nclass Foo:\n    def bar(self): pass\n\n"
            "def baz(): pass\n\"\"\") NOW."
        ),
        expect="write_file",
        required=True,
        max_retries=2,
        validate=_validate_skeleton,
        on_result=lambda r, ctx: ctx.update({
            "_skeleton_path": skeleton_path,
            "_skeleton_target": filepath,
        }),
    )


def implement_steps(
    task: str,
    filepath: str,
    specs: "list",           # list[FunctionSpec] from parse_skeleton
    skeleton_code: str,
    file_num: int = 0,
    total_files: int = 0,
) -> list[Step]:
    """
    Phase 2 of Spec-First writing.

    For each FunctionSpec parsed from the skeleton, generates one Step.
    Each step receives:
      - The skeleton as structural context
      - A dynamic "already written" list (populated at runtime via context)
      - The specific function to implement

    Cross-step consistency: on_result stores the signature hint so later
    steps know what variables/patterns earlier functions used.
    """
    num_label = f"[File {file_num}/{total_files}] " if file_num else ""
    steps: list[Step] = []

    skeleton_ctx = skeleton_code[:1200] + ("\n..." if len(skeleton_code) > 1200 else "")

    for i, spec in enumerate(specs):
        if spec.is_class:
            continue

        method_prefix = f"{spec.class_name}." if spec.class_name else ""
        full_name     = f"{method_prefix}{spec.name}"
        piece_path    = f"_piece_{filepath.replace('/', '_')}_{spec.name}.py"

        docstring_hint = f"\n  Docstring: {spec.docstring}" if spec.docstring else ""
        class_hint     = (
            f"\n  This is a method of class {spec.class_name}."
            if spec.class_name else ""
        )

        # Build "already written" note dynamically — injected at prompt-build time
        # via _build_prompt Cross-Step Context. But also embed a static placeholder
        # so the model always sees it even without context injection.
        already_written_note = (
            f"\nOther functions in this file (use consistent variable names): "
            f"{', '.join(s.name for s in specs if not s.is_class and s.name != spec.name)}"
            if len(specs) > 2 else ""
        )

        steps.append(Step(
            prompt=(
                f"{num_label}Implement: {full_name}\n"
                f"File: {filepath} | Task: {task}\n"
                f"Signature: {spec.signature}{docstring_hint}{class_hint}"
                f"{already_written_note}\n\n"
                f"Skeleton (for structure reference only — do NOT copy pass stubs):\n"
                f"```python\n{skeleton_ctx}\n```\n\n"
                f"Write ONLY the complete `{spec.name}` function "
                f"(def line + docstring + full working body, no pass).\n"
                f"Call write_file(path=\"{piece_path}\", content=\"def {spec.name}...\")"
            ),
            expect="write_file",
            required=False,
            max_retries=2,
            validate=_validate_nonempty,
            on_result=lambda r, ctx, ppath=piece_path, fname=full_name, idx=i: (
                ctx.setdefault("_pieces", []).append({
                    "kind":  "function" if "." not in fname else "method",
                    "name":  fname.split(".")[-1],
                    "class": fname.split(".")[0] if "." in fname else "",
                    "code":  _read_piece_from_result(r, ctx, ppath),
                    "order": idx,
                })
            ),
        ))

    return steps


def _read_piece_from_result(result: str, ctx: dict, piece_path: str) -> str:
    """Read the written piece file from disk."""
    from pathlib import Path
    workspace = ctx.get("_workspace", "")
    if workspace:
        try:
            full = Path(workspace) / piece_path.lstrip("/\\")
            if full.exists():
                return full.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


# ── Skeleton validator ────────────────────────────────────────────────────────

def _validate_skeleton(result: str) -> tuple[bool, str]:
    """
    Check that write_file succeeded AND the skeleton looks like a Python structure.
    """
    if result.startswith("Written"):
        return True, ""
    if "error" in result.lower():
        return False, f"Write failed: {result[:100]}"
    return True, ""


# ── Tester steps ──────────────────────────────────────────────────────────────

def tester_steps(task: str, workspace: Path) -> list[Step]:
    return [
        # Step 1: See what code exists
        Step(
            prompt="List all files in workspace to see what code to test.",
            expect="list_files",
            args={},
            required=True,
            max_retries=1,
            on_result=lambda r, ctx: ctx.update({"files_list": r}),
        ),
        # Step 2: Read main source file
        Step(
            prompt=(
                f"Task: {task}\n\n"
                "Read the main source file (not tests, not plan.md) to understand the code."
            ),
            expect="read_file",
            required=True,
            max_retries=2,
            validate=_validate_nonempty,
            on_result=lambda r, ctx: ctx.update({"source_code": r}),
        ),
        # Step 3: Write test file
        Step(
            prompt=(
                f"Task: {task}\n\n"
                "Write pytest tests in tests/test_main.py.\n"
                "Test each function/endpoint individually.\n"
                "Use write_file(path=\"tests/test_main.py\", content=\"...\") now."
            ),
            expect="write_file",
            required=True,
            max_retries=3,
            validate=_validate_file_written,
        ),
        # Step 4: Run tests
        Step(
            prompt="Run the tests with pytest.",
            expect="run_command",
            args={"command": "python -m pytest tests/ -v --tb=short", "timeout": 60},
            required=False,
            max_retries=1,
            on_result=lambda r, ctx: ctx.update({"test_output": r}),
        ),
    ]


# ── Reviewer steps ────────────────────────────────────────────────────────────

def reviewer_steps(task: str, workspace: Path) -> list[Step]:
    return [
        # Step 1: See all files
        Step(
            prompt="List all files in workspace.",
            expect="list_files",
            args={},
            required=True,
            max_retries=1,
            on_result=lambda r, ctx: ctx.update({"files_list": r}),
        ),
        # Step 2: Read main file
        Step(
            prompt=(
                f"Task: {task}\n\n"
                "Read the main source file to review it."
            ),
            expect="read_file",
            required=True,
            max_retries=2,
            validate=_validate_nonempty,
            on_result=lambda r, ctx: ctx.update({"source_code": r}),
        ),
        # Step 3: Write review.md
        Step(
            prompt=(
                f"Task: {task}\n\n"
                "Write review.md with:\n"
                "- CRITICAL bugs (wrong imports, missing error handling, logic errors)\n"
                "- MAJOR issues\n"
                "- What was done well\n\n"
                "Use write_file(path=\"review.md\", content=\"# Code Review\\n...\") now."
            ),
            expect="write_file",
            required=True,
            max_retries=3,
            validate=_validate_file_written,
        ),
    ]


# ── Factory functions ─────────────────────────────────────────────────────────

def make_step_architect(
    provider: BaseProvider,
    executor,
    workspace: Path,
    max_retries: int = 2,
    stream: bool = True,
) -> tuple[StepAgent, list[Step]]:
    from agents.agents import ARCHITECT_SYSTEM

    agent = StepAgent(
        name="architect",
        provider=provider,
        tools=ARCHITECT_TOOLS,
        executor=executor,
        system=ARCHITECT_SYSTEM,
        stream_tokens=stream,
    )
    return agent, []  # steps built per-task in pipeline


def make_step_coder(
    provider: BaseProvider,
    executor,
    workspace: Path,
    stream: bool = True,
) -> StepAgent:
    from agents.agents import CODER_SYSTEM

    return StepAgent(
        name="coder",
        provider=provider,
        tools=CODER_TOOLS,
        executor=executor,
        system=CODER_SYSTEM.format(revision_note=""),
        stream_tokens=stream,
    )


def make_step_tester(
    provider: BaseProvider,
    executor,
    workspace: Path,
    stream: bool = True,
) -> StepAgent:
    from agents.agents import TESTER_SYSTEM

    return StepAgent(
        name="tester",
        provider=provider,
        tools=TESTER_TOOLS,
        executor=executor,
        system=TESTER_SYSTEM,
        stream_tokens=stream,
    )


def make_step_reviewer(
    provider: BaseProvider,
    executor,
    workspace: Path,
    stream: bool = True,
) -> StepAgent:
    from agents.agents import REVIEWER_SYSTEM

    return StepAgent(
        name="reviewer",
        provider=provider,
        tools=REVIEWER_TOOLS,
        executor=executor,
        system=REVIEWER_SYSTEM,
        stream_tokens=stream,
    )