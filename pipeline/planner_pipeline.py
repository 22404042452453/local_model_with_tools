"""
pipeline/planner_pipeline.py — PlannerPipeline

Flow:
    Planner ──> reads tasks.json
                    │
                    ├─> [task_1] Architect→Coder→Tester→Reviewer  (sequential)
                    ├─> [task_2] Architect→Coder→Tester→Reviewer  (sequential, waits for deps)
                    └─> [task_N] Architect→Coder→Tester→Reviewer

Tasks without dependencies run concurrently.
Tasks with depends_on wait for all dependencies to finish first.
"""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from agents.planner import make_planner
from core.config import Config
from core.events import Event
from core.providers import make_provider
from pipeline.pipeline import Pipeline, PipelineResult
from tools.executor import make_executor


@dataclass
class PlannerResult:
    tasks:        list[dict]             = field(default_factory=list)
    results:      dict[str, PipelineResult] = field(default_factory=dict)
    failed_tasks: list[str]              = field(default_factory=list)
    success:      bool                   = False


class PlannerPipeline:
    def __init__(self, config: Config):
        self.config  = config
        self._queues: list[asyncio.Queue] = []

    # ── Pub/sub ───────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    async def _emit(self, event: Event) -> None:
        for q in self._queues:
            await q.put(event)

    # ── Run ───────────────────────────────────────────────────────────────────

    async def run(self, task: str, clean_workspace: bool = False) -> PlannerResult:
        import time as _time
        _t_start = _time.perf_counter()

        cfg = self.config
        cfg.workspace.mkdir(parents=True, exist_ok=True)

        result = PlannerResult()

        # ── Step 1: Planner decomposes the task ───────────────────────────────
        provider = make_provider(**cfg.provider_kwargs("architect"))
        executor = make_executor(cfg.workspace)

        planner = make_planner(
            provider   = provider,
            executor   = executor,
            max_steps  = cfg.max_steps,
            stream     = cfg.stream_tokens,
        )

        await self._emit(Event(
            agent="pipeline", type="agent_start",
            data={"task": task, "stage": "planner"}
        ))

        _t0 = _time.perf_counter()
        planner_summary, verdict = await planner.run(
            f"Break this into subtasks: {task}", self._emit
        )
        _planner_time = round(_time.perf_counter() - _t0, 2)

        if verdict == "FAIL" or planner_summary is None:
            await self._emit(Event.error("pipeline", "Planner failed."))

        # ── Step 2: Read tasks.json (with robust fallback) ────────────────────
        tasks_file = cfg.workspace / "tasks.json"

        # Fallback: if planner didn't create tasks.json — ALWAYS create one.
        # Previous bug: fallback only triggered if planner_summary was truthy.
        # Now we create a single-task fallback regardless.
        if not tasks_file.exists():
            desc = planner_summary or task
            # Try to extract useful context from planner's search results
            search_ctx = ""
            for f in cfg.workspace.glob("*.md"):
                try:
                    search_ctx = f.read_text(encoding="utf-8")[:500]
                    break
                except Exception:
                    pass

            fallback_tasks = [{
                "id": "task_1",
                "title": task[:60],
                "description": (
                    f"{desc}\n\n"
                    f"Original request: {task}\n"
                    + (f"Research context:\n{search_ctx}" if search_ctx else "")
                ),
                "workspace": str(cfg.workspace / "task_1"),
                "depends_on": []
            }]
            tasks_file.write_text(
                json.dumps(fallback_tasks, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            await self._emit(Event("pipeline", "agent_start", {
                "task": "Auto-created tasks.json (planner didn't write it)",
                "stage": "fallback",
            }))

        if not tasks_file.exists():
            # Should never happen after fallback above — safety net
            await self._emit(Event.error("pipeline", "Planner did not produce tasks.json"))
            return result

        try:
            tasks: list[dict] = json.loads(tasks_file.read_text(encoding="utf-8"))
        except Exception as e:
            await self._emit(Event.error("pipeline", f"tasks.json parse error: {e}"))
            return result

        result.tasks = tasks

        await self._emit(Event(
            agent="pipeline", type="iteration",
            data={"n": 0, "reason": f"Planner created {len(tasks)} subtasks"}
        ))

        # ── Step 3: Execute tasks respecting depends_on ────────────────────────
        completed: dict[str, asyncio.Event] = {t["id"]: asyncio.Event() for t in tasks}
        task_map:  dict[str, dict]          = {t["id"]: t for t in tasks}

        async def run_task(task_def: dict) -> None:
            task_id    = task_def["id"]
            task_title = task_def.get("title", task_id)
            task_desc  = task_def.get("description", "")
            depends_on = task_def.get("depends_on", [])

            # Wait for all dependencies
            if depends_on:
                await self._emit(Event(
                    agent="pipeline", type="agent_start",
                    data={"task": f"[{task_id}] waiting for: {depends_on}",
                          "stage": "waiting"}
                ))
                await asyncio.gather(*[completed[dep].wait() for dep in depends_on
                                       if dep in completed])

            await self._emit(Event(
                agent="pipeline", type="agent_start",
                data={"task": f"Starting [{task_id}]: {task_title}", "stage": task_id}
            ))

            # Each subtask gets its own workspace + config
            sub_workspace = Path(task_def.get("workspace", f"workspace/{task_id}"))
            sub_workspace.mkdir(parents=True, exist_ok=True)

            sub_cfg           = Config.from_env()
            sub_cfg.backend   = cfg.backend
            sub_cfg.model     = cfg.model
            sub_cfg.api_key   = cfg.api_key
            sub_cfg.base_url  = cfg.base_url
            sub_cfg.workspace = sub_workspace
            sub_cfg.max_steps = cfg.max_steps
            sub_cfg.max_iterations = cfg.max_iterations
            sub_cfg.stream_tokens  = cfg.stream_tokens
            # Copy per-agent configs
            sub_cfg.architect_cfg = cfg.architect_cfg
            sub_cfg.coder_cfg     = cfg.coder_cfg
            sub_cfg.tester_cfg    = cfg.tester_cfg
            sub_cfg.reviewer_cfg  = cfg.reviewer_cfg

            # Build a sub-pipeline and forward all its events upstream
            sub_pipeline = Pipeline(sub_cfg)
            sub_queue    = sub_pipeline.subscribe()

            async def forward():
                while True:
                    ev = await sub_queue.get()
                    # Tag events with subtask id so UI can distinguish them
                    ev.data["subtask_id"] = task_id
                    await self._emit(ev)
                    if ev.type in ("pipeline_done", "error") and ev.agent == "pipeline":
                        break

            sub_result, _ = await asyncio.gather(
                sub_pipeline.run(
                    f"[Subtask: {task_title}]\n\n{task_desc}",
                    clean_workspace=False,
                ),
                asyncio.create_task(forward()),
            )

            result.results[task_id] = sub_result
            if not sub_result.success:
                result.failed_tasks.append(task_id)

            # Signal completion so dependents can proceed
            completed[task_id].set()

        # ── Dependency-aware scheduling ────────────────────────────────────────
        # Build dependency layers: tasks in the same layer have no inter-dependencies
        # and can run concurrently. Tasks in later layers wait for earlier ones.

        scheduled: set[str] = set()
        all_tasks            = list(tasks)

        while len(scheduled) < len(all_tasks):
            # Find tasks whose dependencies are all scheduled
            ready = [
                t for t in all_tasks
                if t["id"] not in scheduled
                and all(dep in scheduled for dep in t.get("depends_on", []))
            ]
            if not ready:
                # Circular dependency guard
                remaining = [t["id"] for t in all_tasks if t["id"] not in scheduled]
                await self._emit(Event.error(
                    "pipeline", f"Circular dependency or unresolvable deps: {remaining}"
                ))
                break

            # Run this layer concurrently
            await asyncio.gather(*[run_task(t) for t in ready])
            for t in ready:
                scheduled.add(t["id"])

        result.success = len(result.failed_tasks) == 0

        _total_time = round(_time.perf_counter() - _t_start, 2)
        await self._emit(Event.pipeline_done({
            "tasks":         len(result.tasks),
            "failed":        result.failed_tasks,
            "final_verdict": "PASS" if result.success else "FAIL",
            "timing": {
                "planner": _planner_time,
                "total":   _total_time,
            },
        }))
        return result