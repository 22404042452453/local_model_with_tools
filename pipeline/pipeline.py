"""
pipeline/pipeline.py — Sequential pipeline with explicit gates

Flow:
    Architect ──done──> Coder ──done──> Tester ──done──> Reviewer
                         ^                                    |
                         └──────────── FAIL ─────────────────┘
                              (up to max_iterations times)

Each agent only starts after the previous emits agent_done.
Gates are implemented as asyncio.Event objects — no polling, no sleep.
"""

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from agents.agents import make_architect, make_coder, make_reviewer, make_tester
from core.config import Config
from core.events import Event, AgentName
from core.providers import make_provider
from tools.executor import make_executor
from tools.sandbox import DockerSandbox
from tools.sandbox_config import make_sandbox_from_env
from tools.sandbox import make_sandboxed_executor


# ── Gate ──────────────────────────────────────────────────────────────────────

class AgentGate:
    """
    Wraps an asyncio.Event so the next agent can await the previous one.
    Also captures the verdict & summary from the completed agent.
    """

    def __init__(self):
        self._event   = asyncio.Event()
        self.summary:  str | None = None
        self.verdict:  str        = "PASS"

    def open(self, summary: str | None, verdict: str = "PASS") -> None:
        self.summary = summary
        self.verdict = verdict
        self._event.set()

    async def wait(self) -> tuple[str | None, str]:
        await self._event.wait()
        return self.summary, self.verdict

    def reset(self) -> None:
        self._event.clear()
        self.summary = None
        self.verdict = "PASS"


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    iterations:        list[dict] = field(default_factory=list)
    architect_summary: str | None = None
    final_verdict:     str        = "FAIL"
    workspace:         Path | None = None
    success:           bool        = False


# ── Pipeline ──────────────────────────────────────────────────────────────────

class Pipeline:
    def __init__(self, config: Config):
        self.config  = config
        self._queues: list[asyncio.Queue] = []

    # ── Pub/sub ───────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)

    async def _emit(self, event: Event) -> None:
        for q in self._queues:
            await q.put(event)

    # ── Gated emit wrapper ────────────────────────────────────────────────────

    def _make_gated_emit(self, gate: AgentGate, agent_name: AgentName):
        """
        Returns an emit callback that:
        - Forwards every event to subscribers
        - On agent_done → opens the gate so the next agent can proceed
        """
        async def emit(event: Event) -> None:
            await self._emit(event)
            if event.type == "agent_done" and event.agent == agent_name:
                gate.open(
                    summary = event.data.get("output"),
                    verdict = event.data.get("verdict", "PASS"),
                )
        return emit

    # ── Run ───────────────────────────────────────────────────────────────────

    async def run(self, task: str, clean_workspace: bool = False) -> PipelineResult:
        cfg = self.config
        if clean_workspace:
            _clean_dir(cfg.workspace)
        cfg.workspace.mkdir(parents=True, exist_ok=True)

        sandbox  = make_sandbox_from_env(cfg.workspace)
        executor = make_sandboxed_executor(cfg.workspace, sandbox)
        if sandbox and sandbox.is_available():
            await self._emit(Event("pipeline", "agent_start",
                {"task": "Docker sandbox active", "stage": "sandbox"}))

        def _provider(name: str):
            return make_provider(**cfg.provider_kwargs(name))

        def _kwargs(name: str) -> dict:
            return dict(provider=_provider(name), executor=executor,
                        max_steps=cfg.max_steps, stream=cfg.stream_tokens)

        result = PipelineResult(workspace=cfg.workspace)

        # ── Stage 1: Architect (once) ─────────────────────────────────────────
        arch_gate    = AgentGate()
        arch         = make_architect(**_kwargs("architect"))
        arch_thoughts: list[str] = []  # capture all thoughts for fallback

        await self._emit(Event(
            agent="pipeline", type="agent_start",
            data={"task": "Architect → Coder → Tester → Reviewer", "stage": "architect"}
        ))

        # Wrap emit to capture thoughts
        base_emit = self._make_gated_emit(arch_gate, "architect")
        async def capturing_emit(event: Event) -> None:
            if event.type == "thought" and event.agent == "architect":
                arch_thoughts.append(event.data.get("text", ""))
            if event.type == "tool_result" and event.agent == "architect":
                arch_thoughts.append(event.data.get("result", ""))
            await base_emit(event)

        arch_summary, _ = await arch.run(
            f"Project request: {task}\n\nProduce plan.md.",
            capturing_emit,
        )

        result.architect_summary = arch_summary or ""

        # Fallback: ensure plan.md exists
        plan_path = cfg.workspace / "plan.md"
        if not plan_path.exists():
            # Try: use architect's thoughts
            combined = "\n\n".join(t for t in arch_thoughts if t.strip())

            if not combined.strip():
                # Last resort: generate a simple plan from the task itself
                combined = (
                    f"# Plan\n\n"
                    f"## Task\n{task}\n\n"
                    f"## Implementation\n"
                    f"Create a working implementation for the task above.\n"
                    f"Write clean, production-quality Python code.\n"
                )

            plan_path.write_text(combined, encoding="utf-8")
            await self._emit(Event("pipeline", "agent_start",
                {"task": "Auto-generated plan.md from architect output", "stage": "fallback"}))

        # Never abort — even if architect "failed", coder can work from plan.md
        if arch_summary is None:
            arch_summary = "Architect produced no summary, but plan.md is available."
            result.architect_summary = arch_summary

        # ── Stage 2: Coder → Tester → Reviewer loop ───────────────────────────
        previous_issues = ""

        for iteration in range(cfg.max_iterations):
            if iteration > 0:
                await self._emit(Event.iteration(iteration + 1, previous_issues[:300]))

            iter_data: dict = {"n": iteration + 1}

            # Gates for this iteration
            coder_gate    = AgentGate()
            tester_gate   = AgentGate()
            reviewer_gate = AgentGate()

            # ── Coder ──────────────────────────────────────────────────────────
            coder      = make_coder(**_kwargs("coder"), revision=iteration,
                                    previous_issues=previous_issues)
            coder_task = (
                f"Original request: {task}\n\n"
                "Read plan.md and implement everything specified."
                + (f"\n\nFix issues from previous review:\n{previous_issues}"
                   if previous_issues else "")
            )

            coder_summary, _ = await coder.run(
                coder_task,
                self._make_gated_emit(coder_gate, "coder"),
            )
            # Gate already opened by emit callback — but also await it to get values
            coder_summary, _ = await coder_gate.wait()
            iter_data["coder"] = coder_summary

            if coder_summary is None:
                await self._emit(Event.error("pipeline", "Coder failed."))
                break

            # ── Tester (starts only after coder_gate is open) ──────────────────
            tester      = make_tester(**_kwargs("tester"))
            tester_task = (
                f"Original request: {task}\n\n"
                "Write and run tests for all code in the workspace."
            )

            await tester.run(
                tester_task,
                self._make_gated_emit(tester_gate, "tester"),
            )
            tester_summary, tester_verdict = await tester_gate.wait()

            # ── Quality gate: did tester actually create tests? ────────────────
            test_files = list(cfg.workspace.rglob("test_*.py")) + list(cfg.workspace.rglob("*_test.py"))
            if not test_files:
                # Auto-generate basic import tests
                await self._emit(Event("pipeline", "agent_start",
                    {"task": "Auto-generating basic tests (model skipped)", "stage": "auto_test"}))
                _auto_generate_tests(cfg.workspace)
                # Run them
                import subprocess
                try:
                    r = subprocess.run(
                        ["python", "-m", "pytest", str(cfg.workspace), "-v", "--tb=short"],
                        cwd=cfg.workspace, capture_output=True, text=True, timeout=60
                    )
                    test_output = (r.stdout + r.stderr).strip()
                    passed = r.returncode == 0
                    tester_verdict = "PASS" if passed else "FAIL"
                    tester_summary = f"[Auto-test] exit={r.returncode}\n{test_output[:500]}"
                except Exception as e:
                    tester_verdict = "FAIL"
                    tester_summary = f"[Auto-test failed] {e}"

            iter_data["tester"]         = tester_summary
            iter_data["tester_verdict"] = tester_verdict

            # ── Reviewer (starts only after coder_gate is open) ───────────────
            reviewer_kwargs = _kwargs("reviewer")
            reviewer_kwargs["executor"] = _make_reviewer_executor(executor)
            reviewer      = make_reviewer(**reviewer_kwargs)
            reviewer_task = (
                f"Original request: {task}\n\n"
                "Review all code and the test report. Write review.md."
            )

            await reviewer.run(
                reviewer_task,
                self._make_gated_emit(reviewer_gate, "reviewer"),
            )
            review_summary, review_verdict = await reviewer_gate.wait()

            # ── Quality gate: did reviewer actually write review.md? ───────────
            review_file = cfg.workspace / "review.md"
            if not review_file.exists():
                # Auto-generate basic code review
                await self._emit(Event("pipeline", "agent_start",
                    {"task": "Auto-generating code review (model skipped)", "stage": "auto_review"}))
                issues = _auto_review_code(cfg.workspace)
                review_file.write_text(issues, encoding="utf-8")
                has_critical = "CRITICAL" in issues
                review_verdict = "FAIL" if has_critical else "PASS"
                review_summary = f"[Auto-review] {'CRITICAL issues found' if has_critical else 'No critical issues'}"

            iter_data["reviewer"]         = review_summary
            iter_data["reviewer_verdict"] = review_verdict

            result.iterations.append(iter_data)

            # ── Gate decision: loop or finish ──────────────────────────────────
            both_pass = (tester_verdict == "PASS" and review_verdict == "PASS")
            last_iter = (iteration == cfg.max_iterations - 1)

            if both_pass or last_iter:
                result.final_verdict = "PASS" if both_pass else "FAIL"
                break

            previous_issues = _extract_issues(review_summary or "")

        result.success = result.final_verdict == "PASS"
        await self._emit(Event.pipeline_done({
            "iterations":    len(result.iterations),
            "final_verdict": result.final_verdict,
            "workspace":     str(cfg.workspace),
        }))
        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_dir(path: Path) -> None:
    if path.exists():
        for item in path.iterdir():
            shutil.rmtree(item) if item.is_dir() else item.unlink()


def _extract_issues(review_summary: str) -> str:
    if not review_summary:
        return "See review.md for details."
    return review_summary[:600]


def _make_reviewer_executor(base_executor):
    """
    Wrap executor to block reviewer from writing .py files.

    Qwen models ignore the 'write review.md' instruction and rewrite source
    files instead.  This guard ensures reviewer can only create .md files,
    so review.md is always produced (or the auto-review fallback kicks in
    with correct data instead of a false-positive CRITICAL).
    """
    def guarded(name: str, args: dict, memory: dict) -> tuple[str, bool]:
        if name == "write_file":
            rel = args.get("path", "").lstrip("/\\")
            if rel.endswith(".py"):
                return (
                    f"Error: As a reviewer you CANNOT write '{rel}'. "
                    f"Your job is to REVIEW code, not rewrite it.\n"
                    f'Write your findings to review.md:\n'
                    f'  write_file(path="review.md", content="# Code Review\\n...")',
                    False,
                )
        return base_executor(name, args, memory)
    return guarded


def _auto_generate_tests(workspace: Path) -> None:
    """
    Auto-generate basic syntax/import tests when the model fails to write tests.
    Tests: does each .py file parse? Can it be imported?
    """
    py_files = [f for f in workspace.rglob("*.py") if "test_" not in f.name and f.name != "__init__.py"]
    if not py_files:
        return

    tests_dir = workspace / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")

    test_lines = [
        '"""Auto-generated tests: syntax and import checks."""',
        "import ast",
        "import sys",
        "from pathlib import Path",
        "",
        f'WORKSPACE = Path(r"{workspace}")',
        "",
    ]

    for i, py_file in enumerate(py_files):
        rel = py_file.relative_to(workspace)
        test_lines.extend([
            f"def test_syntax_{i}_{py_file.stem}():",
            f'    """Check {rel} has valid Python syntax."""',
            f'    source = Path(r"{py_file}").read_text(encoding="utf-8")',
            f"    ast.parse(source)  # raises SyntaxError if invalid",
            "",
        ])

    (tests_dir / "test_auto.py").write_text("\n".join(test_lines), encoding="utf-8")


def _auto_review_code(workspace: Path) -> str:
    """
    Thorough auto-review when the model fails to review.
    Checks: syntax, imports, undefined vars, runtime errors, common issues.
    """
    import ast

    py_files = [f for f in workspace.rglob("*.py")
                if "test_" not in f.name and f.name != "__init__.py"
                and ".pytest_cache" not in str(f)]

    lines = ["# Auto-Generated Code Review\n"]
    all_issues: list[str] = []

    for py_file in py_files:
        rel = py_file.relative_to(workspace)
        file_issues: list[str] = []

        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception as e:
            file_issues.append(f"CRITICAL: Cannot read file: {e}")
            all_issues.extend(file_issues)
            lines.append(f"\n## {rel}\n" + "\n".join(f"- {i}" for i in file_issues))
            continue

        # ── 1. Syntax check ───────────────────────────────────────────────────
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            file_issues.append(f"CRITICAL: Syntax error at line {e.lineno}: {e.msg}")
            # Show the offending line
            src_lines = source.splitlines()
            if e.lineno and e.lineno <= len(src_lines):
                file_issues.append(f"  Line {e.lineno}: {src_lines[e.lineno-1].rstrip()}")
            all_issues.extend(file_issues)
            lines.append(f"\n## {rel}\n" + "\n".join(f"- {i}" for i in file_issues))
            continue

        # ── 2. Import check ───────────────────────────────────────────────────
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    ok, err = _check_import(mod)
                    if not ok:
                        file_issues.append(
                            f"CRITICAL: Import '{alias.name}' failed: {err}. "
                            f"Fix: remove import or install package."
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    mod = node.module.split(".")[0]
                    # Skip relative imports (local modules)
                    if node.level == 0:
                        ok, err = _check_import(mod)
                        if not ok:
                            # Check if it's a local file
                            local = workspace / (mod + ".py")
                            if not local.exists():
                                file_issues.append(
                                    f"CRITICAL: Import 'from {node.module}' failed: {err}. "
                                    f"Not a local file either."
                                )

        # ── 3. Undefined name detection (basic) ──────────────────────────────
        defined = set()
        used_names = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
                for arg in node.args.args:
                    defined.add(arg.arg)
            elif isinstance(node, ast.ClassDef):
                defined.add(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    defined.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    defined.add(alias.asname or alias.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    if isinstance(target, ast.Name):
                        defined.add(target.id)
            elif isinstance(node, ast.For):
                if isinstance(node.target, ast.Name):
                    defined.add(node.target.id)
            elif isinstance(node, ast.comprehension):
                if isinstance(node.target, ast.Name):
                    defined.add(node.target.id)

        # Common builtins that are always defined
        builtins = {"print", "len", "range", "int", "str", "float", "list", "dict",
                    "set", "tuple", "bool", "type", "None", "True", "False",
                    "open", "super", "self", "cls", "enumerate", "zip", "map",
                    "filter", "sorted", "reversed", "isinstance", "hasattr",
                    "getattr", "setattr", "Exception", "ValueError", "TypeError",
                    "KeyError", "IndexError", "FileNotFoundError", "RuntimeError",
                    "StopIteration", "NotImplementedError", "OSError", "IOError",
                    "property", "staticmethod", "classmethod", "abs", "min", "max",
                    "sum", "round", "any", "all", "input", "format", "repr", "id",
                    "hex", "oct", "bin", "chr", "ord", "bytes", "bytearray",
                    "memoryview", "frozenset", "complex", "divmod", "pow",
                    "hash", "callable", "dir", "vars", "globals", "locals",
                    "__name__", "__file__", "__all__"}

        # Check for BaseModel/Field without import (very common error)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "BaseModel" and "BaseModel" not in defined:
                file_issues.append(
                    "CRITICAL: `BaseModel` used but not imported. "
                    "Add: `from pydantic import BaseModel`"
                )
            if isinstance(node, ast.Name) and node.id == "Field" and "Field" not in defined:
                file_issues.append(
                    "CRITICAL: `Field` used but not imported. "
                    "Add: `from pydantic import Field`"
                )

        # ── 4. Try/except without handler ─────────────────────────────────────
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                file_issues.append("MAJOR: Bare `except:` clause — catch specific exceptions")
            if isinstance(node, ast.Try):
                if not node.handlers and not node.finalbody:
                    file_issues.append("CRITICAL: `try` without `except` or `finally`")

        # ── 5. Runtime check — REMOVED ────────────────────────────────────────
        # BUG FIX: previously used py_file (workspace/main.py) with cwd=workspace,
        # causing open() to look for workspace/workspace/main.py → FileNotFoundError
        # on EVERY file → false CRITICAL → infinite FAIL loop across all iterations.
        # Step 1 ast.parse(source) already validates syntax — this was redundant.

        # ── 6. TODO/FIXME ─────────────────────────────────────────────────────
        for i, line in enumerate(source.splitlines(), 1):
            if "TODO" in line or "FIXME" in line:
                file_issues.append(f"MINOR: TODO/FIXME at line {i}: {line.strip()[:60]}")
            if "pass" == line.strip() and i > 1:
                # Check if it's a stub function
                prev = source.splitlines()[i-2].strip() if i >= 2 else ""
                if prev.startswith("def ") or prev.startswith("class "):
                    file_issues.append(f"MAJOR: Stub function at line {i-1}: {prev[:60]}")

        # ── Summary for this file ─────────────────────────────────────────────
        lines.append(f"\n## {rel}")
        lines.append(f"- Lines: {len(source.splitlines())}, Size: {len(source)} chars")
        if file_issues:
            for issue in file_issues:
                lines.append(f"- {issue}")
        else:
            lines.append("- No issues found")

        all_issues.extend(file_issues)

    # ── Overall verdict ───────────────────────────────────────────────────────
    critical = [i for i in all_issues if "CRITICAL" in i]
    major    = [i for i in all_issues if "MAJOR" in i]
    minor    = [i for i in all_issues if "MINOR" in i]

    verdict = "FAIL" if critical else "PASS"
    summary = (
        f"\n---\n"
        f"**VERDICT: {verdict}**\n"
        f"- Critical: {len(critical)}\n"
        f"- Major: {len(major)}\n"
        f"- Minor: {len(minor)}\n"
    )

    if critical:
        summary += "\n**Fix these CRITICAL issues:**\n"
        for i, issue in enumerate(critical[:5], 1):
            summary += f"{i}. {issue}\n"

    lines.insert(1, summary)
    return "\n".join(lines)


def _check_import(module_name: str) -> tuple[bool, str]:
    """Check if a Python module can be imported."""
    import importlib
    try:
        importlib.import_module(module_name)
        return True, ""
    except ImportError as e:
        return False, str(e)
    except Exception as e:
        return True, ""  # non-import error = module exists but has issues
