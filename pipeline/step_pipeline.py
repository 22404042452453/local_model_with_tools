"""
pipeline/step_pipeline.py — StepPipeline

Uses StepAgent instead of BaseAgent.
Pipeline controls every step — no free-roaming.

Flow:
    Architect: search → write plan.md
    Coder:     read plan → write files → verify
    Tester:    list → read → write tests → run
    Reviewer:  list → read → write review.md
    → validate quality gates
    → loop if FAIL
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from agents.step_definitions import (
    architect_steps, coder_steps, tester_steps, reviewer_steps,
    make_step_coder, make_step_tester, make_step_reviewer,
)
from core.config import Config
from core.events import Event
from core.providers import make_provider
from core.step_agent import StepAgent, Step
from pipeline.pipeline import AgentGate, PipelineResult, _clean_dir, _auto_generate_tests, _auto_review_code
from tools.definitions import ARCHITECT_TOOLS
from tools.executor import make_executor


class StepPipeline:
    """
    Full Architect → Coder → Tester → Reviewer pipeline
    using atomic steps instead of free-roaming agents.
    """

    def __init__(self, config: Config):
        self.config  = config
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    async def _emit(self, event: Event) -> None:
        for q in self._queues:
            await q.put(event)

    async def run(self, task: str, clean_workspace: bool = False) -> PipelineResult:
        cfg = self.config
        if clean_workspace:
            _clean_dir(cfg.workspace)
        cfg.workspace.mkdir(parents=True, exist_ok=True)

        executor = make_executor(cfg.workspace)

        def _provider(name: str):
            return make_provider(**cfg.provider_kwargs(name))

        def _no_think_system(system: str) -> str:
            """Prepend /no_think for qwen3 models to disable reasoning."""
            model = cfg.model.lower()
            if any(x in model for x in ("qwen3", "qwen2.5", "qwen3.5")):
                return "/no_think\n\n" + system
            return system

        def _step_agent(agent_name: str, tools, system: str) -> StepAgent:
            return StepAgent(
                name          = agent_name,
                provider      = _provider(agent_name),
                tools         = tools,
                executor      = executor,
                system        = _no_think_system(system),
                stream_tokens = cfg.stream_tokens,
            )

        result = PipelineResult(workspace=cfg.workspace)

        await self._emit(Event("pipeline", "agent_start", {
            "task":  "StepPipeline: Architect → Coder → Tester → Reviewer",
            "stage": "start",
        }))

        # ── 1. Architect ──────────────────────────────────────────────────────
        from agents.agents import ARCHITECT_SYSTEM
        arch_agent = _step_agent("architect", ARCHITECT_TOOLS, ARCHITECT_SYSTEM)
        arch_context: dict = {"_memory": {}, "_workspace": str(cfg.workspace)}

        await self._emit(Event.start("architect", task))

        steps = architect_steps(task, cfg.workspace, search_first=True)
        ok, arch_context = await arch_agent.run_steps(steps, arch_context, self._emit)

        # Fallback: if plan.md not created, build from context
        plan_path = cfg.workspace / "plan.md"
        if not plan_path.exists():
            combined = arch_context.get("_search_result", "") or task
            plan_path.write_text(
                f"# Plan\n\n## Task\n{task}\n\n## Implementation\n"
                f"Implement the task described above with clean Python code.\n"
                f"\n## Context\n{combined[:1000]}",
                encoding="utf-8"
            )
            await self._emit(Event("pipeline", "agent_start",
                {"task": "Auto-generated plan.md", "stage": "fallback"}))

        result.architect_summary = plan_path.read_text(encoding="utf-8")[:200]
        await self._emit(Event.done("architect", result.architect_summary))

        # ── 2. Coder → Tester → Reviewer loop ─────────────────────────────────
        previous_issues = ""

        for iteration in range(cfg.max_iterations):
            if iteration > 0:
                await self._emit(Event.iteration(iteration + 1, previous_issues[:200]))

            iter_data: dict = {"n": iteration + 1}

            # ── Coder ──────────────────────────────────────────────────────────
            from agents.agents import CODER_SYSTEM
            from tools.definitions import CODER_TOOLS

            coder_system = CODER_SYSTEM.format(
                revision_note=(
                    f"\n\nFix these issues from previous review:\n{previous_issues}"
                    if previous_issues else ""
                )
            )
            coder_agent  = _step_agent("coder", CODER_TOOLS, coder_system)
            coder_context: dict = {"_memory": {}}

            coder_step_list = coder_steps(task, cfg.workspace)
            await coder_agent.run_steps(coder_step_list, coder_context, self._emit)

            # Verify at least one .py file was created
            py_files = list(cfg.workspace.glob("*.py")) + list(cfg.workspace.glob("**/*.py"))
            py_files = [f for f in py_files if "test_" not in f.name and "__init__" not in f.name]

            if not py_files:
                await self._emit(Event.error("coder", "No Python files created — skipping iteration."))
                iter_data["coder"] = "No files created"
                result.iterations.append(iter_data)
                continue

            iter_data["coder"] = f"Created {len(py_files)} file(s)"
            await self._emit(Event.done("coder", iter_data["coder"]))

            # ── Tester ─────────────────────────────────────────────────────────
            from agents.agents import TESTER_SYSTEM
            from tools.definitions import TESTER_TOOLS

            tester_agent   = _step_agent("tester", TESTER_TOOLS, TESTER_SYSTEM)
            tester_context: dict = {"_memory": {}}
            tester_step_list = tester_steps(task, cfg.workspace)
            await tester_agent.run_steps(tester_step_list, tester_context, self._emit)

            # Quality gate: tests created?
            test_files = (list(cfg.workspace.rglob("test_*.py"))
                         + list(cfg.workspace.rglob("*_test.py")))
            if not test_files:
                await self._emit(Event("pipeline", "agent_start",
                    {"task": "Auto-generating tests", "stage": "auto_test"}))
                _auto_generate_tests(cfg.workspace)

            # Run tests
            tester_verdict, test_output = self._run_tests(cfg.workspace)
            iter_data["tester"]         = test_output[:300]
            iter_data["tester_verdict"] = tester_verdict
            await self._emit(Event.done("tester", test_output[:200], tester_verdict))

            # ── Reviewer ───────────────────────────────────────────────────────
            from agents.agents import REVIEWER_SYSTEM
            from tools.definitions import REVIEWER_TOOLS

            reviewer_agent   = _step_agent("reviewer", REVIEWER_TOOLS, REVIEWER_SYSTEM)
            reviewer_context: dict = {"_memory": {}}
            reviewer_step_list = reviewer_steps(task, cfg.workspace)
            await reviewer_agent.run_steps(reviewer_step_list, reviewer_context, self._emit)

            # Quality gate: review.md created?
            review_file = cfg.workspace / "review.md"
            if not review_file.exists():
                issues = _auto_review_code(cfg.workspace)
                review_file.write_text(issues, encoding="utf-8")

            review_content = review_file.read_text(encoding="utf-8")
            has_critical   = "CRITICAL" in review_content and "FAIL" in review_content
            review_verdict = "FAIL" if has_critical else "PASS"
            review_summary = review_content[:300]

            iter_data["reviewer"]         = review_summary
            iter_data["reviewer_verdict"] = review_verdict
            await self._emit(Event.done("reviewer", review_summary, review_verdict))

            result.iterations.append(iter_data)

            # Gate decision
            both_pass = (tester_verdict == "PASS" and review_verdict == "PASS")
            last_iter = (iteration == cfg.max_iterations - 1)

            if both_pass or last_iter:
                result.final_verdict = "PASS" if both_pass else "FAIL"
                break

            # Feed issues to next coder iteration
            previous_issues = review_content[:600]

        result.success = result.final_verdict == "PASS"
        await self._emit(Event.pipeline_done({
            "iterations":    len(result.iterations),
            "final_verdict": result.final_verdict,
            "workspace":     str(cfg.workspace),
        }))
        return result

    def _run_tests(self, workspace: Path) -> tuple[str, str]:
        """Run pytest and return (verdict, output)."""
        try:
            r = subprocess.run(
                ["python", "-m", "pytest", str(workspace), "-v", "--tb=short", "-q"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=60,
            )
            out = (r.stdout + r.stderr).strip()
            verdict = "PASS" if r.returncode == 0 else "FAIL"
            return verdict, out
        except subprocess.TimeoutExpired:
            return "FAIL", "Tests timed out after 60s"
        except Exception as e:
            return "FAIL", f"Test run error: {e}"
