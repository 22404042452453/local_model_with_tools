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
    skeleton_step, implement_steps,
)
from agents import step_definitions
from agents.agents import (
    ARCHITECT_SYSTEM, CODER_SYSTEM,
    TESTER_SYSTEM, REVIEWER_SYSTEM,
)
from core.config import Config
from core.events import Event
from core.file_builder import (
    extract_functions_from_plan, build_file_steps,
    assemble_from_context, parse_skeleton, FunctionSpec,
)
from core.iteration_memory import IterationMemory, build_memory_from_iteration
from core.providers import make_provider
from core.step_agent import StepAgent, Step
from pipeline.pipeline import AgentGate, PipelineResult, _clean_dir, _auto_generate_tests, _auto_review_code
from tools.definitions import ARCHITECT_TOOLS, CODER_TOOLS, TESTER_TOOLS, REVIEWER_TOOLS
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
        import time as _time
        _t_pipeline_start = _time.perf_counter()
        _timing: dict[str, float] = {}   # agent_name → elapsed_sec

        cfg = self.config
        if clean_workspace:
            _clean_dir(cfg.workspace)
        cfg.workspace.mkdir(parents=True, exist_ok=True)

        # ── Load plugins ──────────────────────────────────────────────────────
        _plugin_registry = None
        try:
            from plugins.loader import get_registry
            _plugin_registry = get_registry()
        except Exception:
            pass

        executor = make_executor(cfg.workspace, plugin_registry=_plugin_registry)

        # ── History: open run record ──────────────────────────────────────────
        _history = None
        _run_id  = None
        try:
            from storage.history import History
            _history = History(str(cfg.workspace.parent / "runs.db"))
            _run_id  = _history.start_run(task, task_type="coding")
        except Exception:
            pass  # history is optional — never block the pipeline

        # Wrap ENTIRE pipeline in try/finally to guarantee finish_run is called.
        # Without this, any exception leaves the run as "running" forever.
        try:
            result = await self._run_pipeline(task, cfg, executor, _timing, _plugin_registry)
        except Exception as e:
            result = PipelineResult(workspace=cfg.workspace)
            result.final_verdict = "FAIL"
            result.success = False
            await self._emit(Event.error("pipeline", f"Pipeline crashed: {e}"))
        finally:
            # ── History: ALWAYS close run record ──────────────────────────────
            if _history and _run_id:
                try:
                    _timing["total"] = round(_time.perf_counter() - _t_pipeline_start, 2)
                    verdict = getattr(result, "final_verdict", "FAIL") or "FAIL"
                    summary = {
                        "iterations":    len(getattr(result, "iterations", [])),
                        "final_verdict": verdict,
                        "timing":        _timing,
                    }
                    _history.finish_run(_run_id, verdict, summary)
                    if verdict == "PASS":
                        _history.save_workspace_snapshot(_run_id, cfg.workspace)
                except Exception:
                    # Last resort: mark as failed so it doesn't stay "running"
                    try:
                        _history.fail_run(_run_id, "finish_run error")
                    except Exception:
                        pass

        return result

    async def _run_pipeline(
        self, task: str, cfg: Config, executor, _timing: dict,
        plugin_registry=None,
    ) -> PipelineResult:
        """Inner pipeline logic — extracted so run() can wrap it in try/finally."""
        import time as _time

        # Store on self for use in _implement_file_parallel
        self._executor = executor
        self._cfg      = cfg

        def _provider(name: str):
            return make_provider(**cfg.provider_kwargs(name))

        # Store provider factory for parallel method
        self._make_provider = _provider

        def _no_think_system(agent_name: str, system: str) -> str:
            """Prepend /no_think for qwen3 models — only for coder and tester."""
            model = cfg.model.lower()
            is_qwen = any(x in model for x in ("qwen3", "qwen2.5", "qwen3.5"))
            needs_no_think = agent_name in ("coder", "tester")
            if is_qwen and needs_no_think:
                return "/no_think\n\n" + system
            return system

        def _merge_plugin_tools(agent_name: str, base_tools: list) -> list:
            """Add plugin tool definitions to agent's tool list."""
            if not plugin_registry:
                return base_tools
            plugin_tools = plugin_registry.get_tools(agent_name)
            if not plugin_tools:
                return base_tools
            return base_tools + plugin_tools

        def _step_agent(agent_name: str, tools, system: str) -> StepAgent:
            merged_tools = _merge_plugin_tools(agent_name, tools)
            return StepAgent(
                name          = agent_name,
                provider      = _provider(agent_name),
                tools         = merged_tools,
                executor      = executor,
                system        = _no_think_system(agent_name, system),
                stream_tokens = cfg.stream_tokens,
            )

        result = PipelineResult(workspace=cfg.workspace)

        await self._emit(Event("pipeline", "agent_start", {
            "task":  "StepPipeline: Architect → Coder → Tester → Reviewer",
            "stage": "start",
        }))

        # ── 0. Pre-flight: environment snapshot ───────────────────────────────
        # Run get_env_info ONCE before any agent. Result is injected into all
        # system prompts so the Architect never plans with unavailable packages.
        env_hint = ""
        try:
            env_raw, _ = executor("get_env_info", {}, {})
            env_hint   = _format_env_hint(env_raw)
            await self._emit(Event("pipeline", "agent_start", {
                "task":  f"Pre-flight env: {env_hint[:80]}...",
                "stage": "preflight",
            }))
        except Exception as e:
            await self._emit(Event("pipeline", "thought", {
                "text": f"Pre-flight skipped: {e}"
            }))

        # ── 1. Architect ──────────────────────────────────────────────────────
        arch_system = ARCHITECT_SYSTEM.format(env_hint=env_hint)
        arch_agent  = _step_agent("architect", ARCHITECT_TOOLS, arch_system)
        arch_context: dict = {"_memory": {}, "_workspace": str(cfg.workspace)}

        await self._emit(Event.start("architect", task))

        steps = architect_steps(task, cfg.workspace, search_first=True)
        _t0 = _time.perf_counter()
        ok, arch_context = await arch_agent.run_steps(steps, arch_context, self._emit)
        _timing["architect"] = round(_time.perf_counter() - _t0, 2)

        # Fallback: if plan.md not created, build structured plan from context
        plan_path = cfg.workspace / "plan.md"
        if not plan_path.exists():
            search_ctx = arch_context.get("_search_result", "")
            fallback_plan = (
                f"# Implementation Plan\n\n"
                f"## Task\n{task}\n\n"
                f"## Technology Stack\n"
                f"- Python 3 (stdlib: math, os, sys, json)\n"
                f"- Only use packages available in the environment\n\n"
                f"## Files\n```\nmain.py    # Main implementation — all core logic\n```\n\n"
                f"## File Details\n### main.py\n"
                f"- Implement the task described above\n"
                f"- Include a `main()` entry point\n"
                f"- Include `if __name__ == '__main__': main()` guard\n\n"
                f"## Implementation Order\n1. main.py — write complete implementation\n\n"
                f"## Testing\n- pytest with tests/test_main.py\n"
            )
            if search_ctx:
                fallback_plan += f"\n## Research Context\n{search_ctx[:800]}\n"
            plan_path.write_text(fallback_plan, encoding="utf-8")
            await self._emit(Event("pipeline", "agent_start",
                {"task": "Auto-generated structured plan.md", "stage": "fallback"}))

        result.architect_summary = plan_path.read_text(encoding="utf-8")[:200]
        await self._emit(Event.done("architect", result.architect_summary))

        # Parse file list from plan.md
        plan_content = plan_path.read_text(encoding="utf-8")
        planned_files = _extract_files_from_plan(plan_content)
        file_descriptions = _extract_file_descriptions(plan_content, planned_files)
        if planned_files:
            await self._emit(Event("pipeline", "agent_start", {
                "task": f"Plan specifies {len(planned_files)} files: {', '.join(planned_files[:5])}",
                "stage": "plan_parsed",
            }))

        # ── 2. Coder → Tester → Reviewer loop ─────────────────────────────────
        from core.iteration_memory import IterationMemory, build_memory_from_iteration
        iter_memory: IterationMemory | None = None

        for iteration in range(cfg.max_iterations):
            if iteration > 0:
                mem_summary = iter_memory.render_for_prompt()[:200] if iter_memory else ""
                await self._emit(Event.iteration(iteration + 1, mem_summary))

            iter_data: dict = {"n": iteration + 1}

            # ── Coder ──────────────────────────────────────────────────────────

            # Build structured revision note from IterationMemory
            revision_note = ""
            if iter_memory and iter_memory.has_issues():
                revision_note = "\n\n" + iter_memory.render_for_prompt()

            coder_system = CODER_SYSTEM.format(
                revision_note=revision_note,
                env_hint=env_hint,
            )
            coder_agent  = _step_agent("coder", CODER_TOOLS, coder_system)
            coder_context: dict = {"_memory": {}, "_workspace": str(cfg.workspace)}

            # ── Build steps: function-level for complex files, whole-file for simple ──

            all_coder_steps = [
                # Always start by reading plan
                step_definitions.Step(
                    prompt=f"Task: {task}\n\nRead plan.md.",
                    expect="read_file",
                    args={"path": "plan.md"},
                    required=True,
                    max_retries=1,
                    on_result=lambda r, ctx: ctx.update({"plan_content": r}),
                ),
            ]

            # For revision iterations: insert targeted edit_file step BEFORE full rewrites.
            # Uses IterationMemory for structured, precise instructions.
            if iteration > 0 and iter_memory and iter_memory.has_issues():
                existing_py = [
                    f.name for f in cfg.workspace.glob("*.py")
                    if "test_" not in f.name and "__init__" not in f.name
                ]
                target_hint = existing_py[0] if existing_py else "main.py"
                memory_block = iter_memory.render_for_prompt()
                all_coder_steps.append(step_definitions.Step(
                    prompt=(
                        f"Apply targeted fixes to {target_hint}.\n\n"
                        f"{memory_block}\n\n"
                        f"Use edit_file(path=\"{target_hint}\", find=\"...\", replace=\"...\") "
                        f"for each broken location. Fix ONLY what is listed as broken. "
                        f"DO NOT touch functions marked as working."
                    ),
                    expect="edit_file",
                    required=False,
                    max_retries=2,
                    validate=lambda r: (True, "") if r.startswith("Edited") else (False, f"Edit failed: {r[:100]}"),
                ))

            files_with_functions: list[tuple[str, list[dict]]] = []
            files_with_skeleton:  list[str] = []   # files built via spec-first

            # ── Fallback: architect didn't list any files ─────────────────────
            # Common when plan.md has no tree-style file listing.
            # Add a single direct write step so coder always produces something.
            if not planned_files:
                await self._emit(Event("pipeline", "thought", {
                    "text": "plan.md has no explicit file list — adding fallback main.py step"
                }))
                all_coder_steps.append(
                    step_definitions._write_file_step(task, "main.py", "Main implementation file")
                )

            for idx, filepath in enumerate(planned_files or [], 1):
                desc  = (file_descriptions or {}).get(filepath, "")
                funcs = extract_functions_from_plan(plan_content, filepath)

                if not filepath.endswith(".py"):
                    # Non-Python files → direct write
                    all_coder_steps.append(
                        step_definitions._write_file_step(
                            task, filepath, desc,
                            file_num=idx, total_files=len(planned_files),
                        )
                    )
                    continue

                # ── Spec-First for all .py files ──────────────────────────────
                # Phase 1: skeleton step (always, for ALL .py files)
                all_coder_steps.append(
                    step_definitions.skeleton_step(
                        task, filepath, desc,
                        file_num=idx, total_files=len(planned_files),
                    )
                )
                files_with_skeleton.append(filepath)

                # Phase 2: implement steps (if plan specifies functions)
                # If plan has no function specs, pipeline will detect after skeleton
                # and add implement steps dynamically in the post-skeleton hook.
                if funcs:
                    await self._emit(Event("pipeline", "thought", {
                        "text": f"File {idx}: {filepath} — spec-first: skeleton + {len(funcs)} implement steps"
                    }))
                    # We can't add implement_steps now because we don't have the
                    # skeleton code yet (it will be written during run_steps).
                    # Instead, store funcs for post-skeleton assembly.
                    files_with_functions.append((filepath, funcs))
                else:
                    await self._emit(Event("pipeline", "thought", {
                        "text": f"File {idx}: {filepath} — spec-first skeleton, implement steps added after"
                    }))

            # ── Phase 1: Run skeleton steps ───────────────────────────────────
            _t0 = _time.perf_counter()
            await coder_agent.run_steps(all_coder_steps, coder_context, self._emit)

            # ── Phase 2: Spec-First — read skeletons, add implement steps ─────
            implement_context: dict = {
                "_memory": {}, "_workspace": str(cfg.workspace)
            }

            for filepath in files_with_skeleton:
                skeleton_path = cfg.workspace / f"_skeleton_{filepath.replace('/', '_')}"

                # Recovery: model may have written to the actual filepath instead of _skeleton_
                # (common with small models that ignore the path in the prompt).
                if not skeleton_path.exists():
                    actual_path = cfg.workspace / filepath
                    if actual_path.exists():
                        # Model wrote to main.py instead of _skeleton_main.py — rescue it
                        import shutil as _sh
                        _sh.copy(actual_path, skeleton_path)
                        await self._emit(Event("pipeline", "thought", {
                            "text": f"Skeleton recovery: {filepath} → {skeleton_path.name}"
                        }))

                if not skeleton_path.exists():
                    await self._emit(Event("pipeline", "thought", {
                        "text": f"No skeleton for {filepath} — falling back to direct write"
                    }))
                    # Fallback: direct write step
                    desc = (file_descriptions or {}).get(filepath, "")
                    fallback_agent = _step_agent("coder", CODER_TOOLS, coder_system)
                    await fallback_agent.run_steps(
                        [step_definitions._write_file_step(task, filepath, desc)],
                        implement_context, self._emit,
                    )
                    continue

                skeleton_code = skeleton_path.read_text(encoding="utf-8")
                specs = parse_skeleton(skeleton_code)

                if not specs:
                    # No functions extracted — treat skeleton as final file
                    import shutil as _sh
                    _sh.copy(skeleton_path, cfg.workspace / filepath)
                    await self._emit(Event("pipeline", "thought", {
                        "text": f"Skeleton for {filepath} has no functions — using as-is"
                    }))
                    continue

                await self._emit(Event("pipeline", "thought", {
                    "text": f"Spec-First: {filepath} skeleton parsed → {len(specs)} specs → implementing..."
                }))

                impl_steps = step_definitions.implement_steps(
                    task=task,
                    filepath=filepath,
                    specs=specs,
                    skeleton_code=skeleton_code,
                    file_num=1,
                    total_files=len(files_with_skeleton),
                )

                if not impl_steps:
                    import shutil as _sh
                    _sh.copy(skeleton_path, cfg.workspace / filepath)
                    continue

                # ── Parallel implementation ───────────────────────────────────
                # Each function is independent → run all concurrently.
                # max_concurrent=3 is safe for local Ollama; set higher for cloud.
                implement_context = await self._implement_file_parallel(
                    task          = task,
                    filepath      = filepath,
                    specs         = specs,
                    skeleton_code = skeleton_code,
                    coder_system  = coder_system,
                    workspace     = cfg.workspace,
                    max_concurrent = getattr(cfg, "parallel_impl_workers", 3),
                )

                # Assemble final file from pieces + skeleton imports
                ok, msg = assemble_from_context(
                    filepath, cfg.workspace, implement_context,
                    docstring=(file_descriptions or {}).get(filepath, ""),
                    skeleton_code=skeleton_code,
                )
                if ok:
                    await self._emit(Event("pipeline", "thought", {
                        "text": f"✅ Assembled {filepath}: {msg}"
                    }))
                else:
                    await self._emit(Event.error("coder",
                        f"Assembly failed for {filepath}: {msg} — falling back to skeleton"))
                    import shutil as _sh
                    _sh.copy(skeleton_path, cfg.workspace / filepath)

            # ── Fallback: if no planned files, run old function-level assembly ─
            for filepath, funcs in files_with_functions:
                if filepath in files_with_skeleton:
                    continue  # already handled above
                desc = (file_descriptions or {}).get(filepath, "")
                ok, msg = assemble_from_context(
                    filepath, cfg.workspace, coder_context, docstring=desc,
                )
                if not ok:
                    await self._emit(Event.error("coder",
                        f"Assembly failed for {filepath}: {msg}"))

            # Clean up skeleton and piece temp files
            for tmp in cfg.workspace.glob("_skeleton_*.py"):
                tmp.unlink(missing_ok=True)
            for tmp in cfg.workspace.glob("_piece_*.py"):
                tmp.unlink(missing_ok=True)

            _timing[f"coder_iter{iteration}"] = round(_time.perf_counter() - _t0, 2)

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

            # ── Loop detection: код не изменился → принудительная смена стратегии ──
            current_hash = _hash_py_files(cfg.workspace)
            if iteration > 0 and current_hash == getattr(result, "_last_code_hash", None):
                await self._emit(Event("pipeline", "thought", {
                    "text": "⚠️  Loop detected: code unchanged since last iteration. "
                            "Forcing full rewrite on next pass."
                }))
                # Tell memory to avoid repeating the same edit approach
                if iter_memory:
                    iter_memory.record_tried_fix("edit_file approach — no change detected")
            result._last_code_hash = current_hash  # type: ignore[attr-defined]

            # ── Pre-check: does code even parse? ──────────────────────────────
            import ast as _ast
            has_syntax_errors = False
            for pf in py_files:
                try:
                    _ast.parse(pf.read_text(encoding="utf-8"))
                except SyntaxError as e:
                    has_syntax_errors = True
                    await self._emit(Event.error("pipeline",
                        f"Syntax error in {pf.name} line {e.lineno}: {e.msg}"))

            # ── Tester (skip if code doesn't parse) ───────────────────────────
            if has_syntax_errors:
                await self._emit(Event("pipeline", "thought", {
                    "text": "Skipping tester — code has syntax errors. Going to reviewer."}))
                tester_verdict = "FAIL"
                iter_data["tester"] = "Skipped — syntax errors in code"
                iter_data["tester_verdict"] = "FAIL"
            else:
    
                tester_agent   = _step_agent("tester", TESTER_TOOLS, TESTER_SYSTEM)
                tester_context: dict = {"_memory": {}, "_workspace": str(cfg.workspace)}
                tester_step_list = tester_steps(task, cfg.workspace)
                _t0_tester = _time.perf_counter()
                await tester_agent.run_steps(tester_step_list, tester_context, self._emit)
                _timing[f"tester_iter{iteration}"] = round(_time.perf_counter() - _t0_tester, 2)

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

            reviewer_agent   = _step_agent("reviewer", REVIEWER_TOOLS, REVIEWER_SYSTEM)
            reviewer_context: dict = {"_memory": {}}
            reviewer_step_list = reviewer_steps(task, cfg.workspace)
            _t0_reviewer = _time.perf_counter()
            await reviewer_agent.run_steps(reviewer_step_list, reviewer_context, self._emit)
            _timing[f"reviewer_iter{iteration}"] = round(_time.perf_counter() - _t0_reviewer, 2)

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

            # ── Build IterationMemory for next revision ────────────────────────
            py_files_for_memory = [
                f for f in cfg.workspace.glob("*.py")
                if "test_" not in f.name and "__init__" not in f.name
            ]
            test_out = iter_data.get("tester", "")
            iter_memory = build_memory_from_iteration(
                review_md   = review_content,
                test_output = test_out,
                py_files    = py_files_for_memory,
                previous    = iter_memory,
            )
            await self._emit(Event("pipeline", "thought", {
                "text": (
                    f"Memory: {len(iter_memory.broken)} broken, "
                    f"{len(iter_memory.failed_imports)} bad imports, "
                    f"{len(iter_memory.working_functions)} working fns"
                )
            }))

        result.success = result.final_verdict == "PASS"
        await self._emit(Event.pipeline_done({
            "iterations":    len(result.iterations),
            "final_verdict": result.final_verdict,
            "workspace":     str(cfg.workspace),
            "timing":        _timing,
        }))

        return result

    async def _implement_file_parallel(
        self,
        task:         str,
        filepath:     str,
        specs:        list,        # list[FunctionSpec]
        skeleton_code: str,
        coder_system: str,
        workspace:    Path,
        max_concurrent: int = 3,
    ) -> dict:
        """
        Implement all functions in a file in PARALLEL.

        Critical fix: each worker gets a WRAPPED executor that intercepts
        write_file calls and forces the path to _piece_*.py — preventing
        the model from writing to the target file directly (race condition).
        """
        from agents.step_definitions import implement_steps as _make_impl_steps

        impl_steps = _make_impl_steps(
            task=task, filepath=filepath, specs=specs,
            skeleton_code=skeleton_code, file_num=1, total_files=1,
        )

        if not impl_steps:
            return {"_workspace": str(workspace), "_pieces": []}

        semaphore = asyncio.Semaphore(max_concurrent)
        total     = len(impl_steps)

        # ── Extract piece_path from each step's prompt ─────────────────────────
        def _extract_piece_path(step) -> str:
            """Get the _piece_*.py path from step prompt."""
            import re
            m = re.search(r'write_file\(path="(_piece_[^"]+)"', step.prompt)
            return m.group(1) if m else ""

        # ── Executor wrapper: force write_file to piece path ──────────────────
        def _make_piece_executor(piece_path: str):
            """
            Wrap the real executor so ALL write_file calls go to piece_path.
            This prevents the model from writing to utils.py/main.py directly
            (which causes race conditions in parallel mode).
            """
            real_executor = self._executor
            def wrapped(tool_name, args, memory):
                if tool_name == "write_file" and piece_path:
                    args = dict(args)  # copy to avoid mutation
                    args["path"] = piece_path
                return real_executor(tool_name, args, memory)
            return wrapped

        # ── Per-function coroutine ─────────────────────────────────────────────
        async def _run_one(step, step_idx: int) -> dict:
            spec_name = step.prompt.split("\n")[0].replace("Implement: ", "").strip()
            piece_path = _extract_piece_path(step)

            ctx: dict = {
                "_memory":       {},
                "_workspace":    str(workspace),
                "_current_file": filepath,
            }

            async with semaphore:
                await self._emit(Event("coder", "agent_start", {
                    "task":  f"[parallel {step_idx+1}/{total}] {spec_name}",
                    "stage": "impl_parallel",
                    "step":  step_idx + 1,
                    "total": total,
                }))

                # Each worker gets its own executor that forces writes to piece_path
                piece_executor = _make_piece_executor(piece_path)

                agent = StepAgent(
                    name          = "coder",
                    provider      = self._make_provider("coder"),
                    tools         = CODER_TOOLS,
                    executor      = piece_executor,
                    system        = coder_system,
                    stream_tokens = self._cfg.stream_tokens,
                )

                ok = await agent._run_step(step, step_idx, ctx, self._emit)

                status = "✅" if ok else "⚠️"
                await self._emit(Event("coder", "thought", {
                    "text": f"{status} {spec_name} {'done' if ok else 'failed'}"
                }))

            # Read piece from disk (now guaranteed to be at piece_path)
            if piece_path:
                full_piece = workspace / piece_path
                if full_piece.exists():
                    code = full_piece.read_text(encoding="utf-8")
                    # Parse function name from spec_name
                    parts = spec_name.split(".")
                    func_name = parts[-1] if parts else spec_name
                    class_name = parts[0] if len(parts) > 1 else ""
                    ctx.setdefault("_pieces", []).append({
                        "kind":  "method" if class_name else "function",
                        "name":  func_name,
                        "class": class_name,
                        "code":  code,
                        "order": step_idx,
                    })

            return ctx

        # ── Fire all in parallel ───────────────────────────────────────────────
        await self._emit(Event("pipeline", "agent_start", {
            "task":  f"Parallel implement: {len(impl_steps)} functions in {filepath}",
            "stage": "impl_parallel_start",
        }))

        contexts = await asyncio.gather(
            *[_run_one(step, i) for i, step in enumerate(impl_steps)],
            return_exceptions=True,
        )

        # ── Merge results ──────────────────────────────────────────────────────
        merged_pieces: list[dict] = []
        errors = 0
        for ctx in contexts:
            if isinstance(ctx, Exception):
                await self._emit(Event.error("coder", f"Parallel step exception: {ctx}"))
                errors += 1
                continue
            pieces = ctx.get("_pieces", [])
            merged_pieces.extend(pieces)

        merged_pieces.sort(key=lambda p: p.get("order", 0))

        await self._emit(Event("pipeline", "thought", {
            "text": (
                f"Parallel impl done: {len(merged_pieces)} pieces"
                + (f", {errors} failed" if errors else "")
            )
        }))

        return {"_workspace": str(workspace), "_pieces": merged_pieces}

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


# ── Plan parser ───────────────────────────────────────────────────────────────

def _extract_files_from_plan(plan_text: str) -> list[str]:
    """
    Extract filenames from plan.md.
    """
    import re

    files = []
    seen  = set()

    # Pattern 1: tree-style  ├── filename.py  or  └── filename.py
    for m in re.finditer(r'[├└│─\s]+\s*([\w/\-\.]+\.(?:py|html|css|js|json|txt|yaml|yml|j2|jinja2|toml))\b', plan_text):
        f = m.group(1).strip()
        if f not in seen:
            files.append(f)
            seen.add(f)

    # Pattern 2: backtick  `filename.py`
    for m in re.finditer(r'`([\w/\-\.]+\.(?:py|html|j2))`', plan_text):
        f = m.group(1).strip()
        if f not in seen:
            files.append(f)
            seen.add(f)

    # Pattern 3: bold  **filename.py**
    for m in re.finditer(r'\*\*([\w/\-\.]+\.(?:py|html|j2))\*\*', plan_text):
        f = m.group(1).strip()
        if f not in seen:
            files.append(f)
            seen.add(f)

    # Filter out non-code files
    skip = {"requirements.txt", "__init__.py", ".gitignore", "README.md"}
    files = [f for f in files if f not in skip]

    # Sort: config first, then modules, main.py last
    def sort_key(f):
        name = f.split("/")[-1]
        if "config" in name: return 0
        if name == "main.py": return 99
        return 1

    files.sort(key=sort_key)
    return files


def _extract_file_descriptions(plan_text: str, files: list[str]) -> dict[str, str]:
    """
    Extract description/purpose for each file from plan.md.
    Looks for patterns like:
        ├── main.py    # Точка входа + CLI интерфейс
        ### `galaxy_generator.py`
        - Класс Star: ...
    Returns {filename: description}
    """
    import re
    descriptions: dict[str, str] = {}

    for filename in files:
        basename = filename.split("/")[-1]
        desc_parts = []

        # Pattern 1: tree comment  "├── main.py  # comment"
        pattern1 = re.escape(basename) + r'\s*#\s*(.+)'
        for m in re.finditer(pattern1, plan_text):
            desc_parts.append(m.group(1).strip())

        # Pattern 2: header section  "### `filename.py`" followed by lines
        escaped = re.escape(basename)
        pattern2 = rf'###?\s*[`\*]*{escaped}[`\*]*\s*\n((?:[-\s*].*\n)*)'
        for m in re.finditer(pattern2, plan_text):
            section = m.group(1).strip()
            # Take first 3 lines
            lines = [l.strip("- *") for l in section.splitlines() if l.strip()][:3]
            desc_parts.extend(lines)

        # Pattern 3: "**Шаг N**: Создать `filename` - description"
        pattern3 = rf'[Шш]аг\s*\d+[:\s]*.*?{escaped}.*?[-–]\s*(.+)'
        for m in re.finditer(pattern3, plan_text):
            desc_parts.append(m.group(1).strip())

        if desc_parts:
            descriptions[filename] = " | ".join(desc_parts[:3])
        else:
            descriptions[filename] = f"Implementation file for the project"

    return descriptions


# ── Pre-flight helpers ────────────────────────────────────────────────────────

def _format_env_hint(env_raw: str) -> str:
    """
    Parse get_env_info output and build a compact hint for system prompts.

    Output example:
        AVAILABLE PACKAGES (use only these): tkinter, random, math, sqlite3, json,
        os, sys, re, pathlib, threading, subprocess, requests, numpy
        NOT available (never import): pygame, flask, fastapi, django, arcade
    """
    import re

    if not env_raw or len(env_raw) < 10:
        return ""

    # Extract package names from pip list output
    # Typical line: "Package         Version"  or  "numpy           1.26.0"
    pkg_lines = []
    in_packages = False
    for line in env_raw.splitlines():
        stripped = line.strip()
        if re.match(r'^Package\s+Version', stripped, re.IGNORECASE):
            in_packages = True
            continue
        if re.match(r'^-+', stripped):
            continue
        if in_packages and stripped:
            parts = stripped.split()
            if parts:
                pkg_name = parts[0].lower().replace("-", "_")
                pkg_lines.append(pkg_name)

    # Fallback: look for "import X" style lines or plain package names
    if not pkg_lines:
        for line in env_raw.splitlines():
            m = re.match(r'^\s*(\w[\w\-]+)\s+[\d\.]+', line)
            if m:
                pkg_lines.append(m.group(1).lower())

    if not pkg_lines:
        return ""

    # Key stdlib packages always available (don't bloat the hint)
    always_available = {
        "os", "sys", "re", "json", "math", "random", "time", "datetime",
        "pathlib", "threading", "subprocess", "collections", "itertools",
        "functools", "typing", "dataclasses", "abc", "io", "struct",
        "hashlib", "base64", "copy", "shutil", "tempfile", "glob",
        "argparse", "logging", "unittest", "tkinter", "sqlite3",
        "csv", "xml", "html", "http", "urllib", "socket", "ssl",
        "multiprocessing", "asyncio", "contextlib", "string", "textwrap",
    }

    # Separate installed vs stdlib
    installed = sorted(set(pkg_lines) - always_available)[:25]
    stdlib    = sorted(always_available & set(pkg_lines + list(always_available)))[:20]

    hint_lines = ["── ENVIRONMENT (use ONLY these packages) ──"]
    if stdlib:
        hint_lines.append(f"Built-in stdlib: {', '.join(stdlib)}")
    if installed:
        hint_lines.append(f"Installed: {', '.join(installed)}")
    hint_lines.append(
        "⚠️  Do NOT import anything not listed above — it will cause ImportError."
    )
    hint_lines.append("──────────────────────────────────────────")
    return "\n".join(hint_lines)


# ── Loop detection helper ─────────────────────────────────────────────────────

def _hash_py_files(workspace: Path) -> str:
    """
    Compute a hash of all non-test .py files in workspace.
    Used to detect when coder produced identical code across iterations.
    """
    import hashlib

    h = hashlib.md5()
    py_files = sorted(
        f for f in workspace.glob("*.py")
        if "test_" not in f.name and "__init__" not in f.name
        and not f.name.startswith("_")
    )
    for fpath in py_files:
        try:
            h.update(fpath.name.encode())
            h.update(fpath.read_bytes())
        except Exception:
            pass
    return h.hexdigest()