"""
pipeline/router.py — Task Router

Classifies the incoming task with a single fast LLM call,
then dispatches to the correct pipeline:

  "coding"   → CodingPipeline  (Architect → Coder → Tester → Reviewer)
  "research" → ResearchPipeline (Researcher → Writer → Editor)
  "planner"  → PlannerPipeline  (Planner → N × CodingPipeline)

The Router uses the cheapest/fastest available model — no tools needed,
just a JSON classification response.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from core.config import Config
from core.events import Event
from core.providers import make_provider

ROUTER_PROMPT = """You are a task router. Classify the user task into exactly ONE type.

Types:
  coding   — build software, write code, implement a feature, create an app/API/script,
             fix bugs, refactor code, add tests, write a single file or module
  research — explain a concept, research a topic, write an article/report/document,
             answer "what is X", "how does X work", summarize, analyze text
  planner  — ONLY for very large projects that clearly need 3+ independent modules
             built separately (e.g. "build a full SaaS platform with auth, billing, dashboard")

Rules:
- Default to "coding" for any programming task
- Single file / single module = "coding", NOT "planner"
- "Write a script for X" = "coding"
- "Explain X" or "write a document about X" = "research"
- Only use "planner" for genuinely large multi-component systems

Respond with ONLY valid JSON, no other text:
{"type": "coding"|"research"|"planner", "reason": "one sentence"}"""


@dataclass
class RouterDecision:
    task_type: str   # "coding" | "research" | "planner"
    reason:    str
    raw:       str   # raw LLM response (for debugging)


class Router:
    def __init__(self, config: Config):
        self.config = config

    async def classify(self, task: str) -> RouterDecision:
        """
        Calls the LLM once to classify the task.
        Falls back to "coding" on any error.
        """
        provider = make_provider(**self.config.provider_kwargs("architect"))

        messages = [{"role": "user", "content": f"Task: {task}"}]

        try:
            resp = await asyncio.to_thread(
                provider.complete, messages, [], ROUTER_PROMPT, None
            )
            raw  = resp.get("text", "").strip()
            # Strip markdown fences if model added them
            raw_clean = raw.strip("`").strip()
            if raw_clean.startswith("json"):
                raw_clean = raw_clean[4:].strip()

            data      = json.loads(raw_clean)
            task_type = data.get("type", "coding").lower()
            reason    = data.get("reason", "")

            if task_type not in ("coding", "research", "planner"):
                task_type = "coding"

            return RouterDecision(task_type=task_type, reason=reason, raw=raw)

        except Exception as e:
            return RouterDecision(task_type="coding",
                                  reason=f"Router error ({e}) — defaulting to coding",
                                  raw=str(e))


class RouterPipeline:
    """
    Top-level pipeline that:
    1. Classifies the task (Router)
    2. Delegates to the appropriate pipeline
    3. Forwards all events upstream
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

    async def run(self, task: str, clean_workspace: bool = False):
        # ── Step 1: classify ──────────────────────────────────────────────────
        router   = Router(self.config)
        decision = await router.classify(task)

        await self._emit(Event("pipeline", "agent_start", {
            "task":      f"Router → {decision.task_type.upper()}",
            "stage":     "router",
            "task_type": decision.task_type,
            "reason":    decision.reason,
        }))

        # ── Step 2: dispatch ──────────────────────────────────────────────────
        use_steps = getattr(self.config, "use_step_pipeline", True)

        if decision.task_type == "research":
            from pipeline.research_pipeline import ResearchPipeline
            pipeline = ResearchPipeline(self.config)
        elif decision.task_type == "planner":
            from pipeline.planner_pipeline import PlannerPipeline
            pipeline = PlannerPipeline(self.config)
        elif use_steps:
            from pipeline.step_pipeline import StepPipeline
            pipeline = StepPipeline(self.config)
        else:
            from pipeline.pipeline import Pipeline
            pipeline = Pipeline(self.config)

        # Forward all sub-pipeline events to our subscribers
        queue = pipeline.subscribe()

        async def forward():
            while True:
                ev = await queue.get()
                await self._emit(ev)
                if ev.type in ("pipeline_done", "error") and ev.agent == "pipeline":
                    break

        result, _ = await asyncio.gather(
            pipeline.run(task, clean_workspace=clean_workspace),
            asyncio.create_task(forward()),
        )
        return result
