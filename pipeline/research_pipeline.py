"""
pipeline/research_pipeline.py — Researcher → Writer → Editor

Sequential with gates (same pattern as CodingPipeline).
On FAIL verdict from Editor: Writer revises up to max_iterations times.
"""

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from agents.research_agents import make_editor, make_researcher, make_writer
from core.config import Config
from core.events import Event
from core.providers import make_provider
from pipeline.pipeline import AgentGate, _clean_dir, _extract_issues
from tools.executor import make_executor


@dataclass
class ResearchResult:
    researcher_summary: str | None = None
    writer_summary:     str | None = None
    editor_summary:     str | None = None
    final_verdict:      str        = "FAIL"
    workspace:          Path | None = None
    success:            bool        = False


class ResearchPipeline:
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

    def _gated(self, gate: AgentGate, agent_name):
        async def emit(event: Event) -> None:
            await self._emit(event)
            if event.type == "agent_done" and event.agent == agent_name:
                gate.open(event.data.get("output"), event.data.get("verdict", "PASS"))
        return emit

    async def run(self, task: str, clean_workspace: bool = False) -> ResearchResult:
        cfg = self.config
        if clean_workspace:
            _clean_dir(cfg.workspace)
        cfg.workspace.mkdir(parents=True, exist_ok=True)

        executor = make_executor(cfg.workspace)

        def _provider(name: str):
            return make_provider(**cfg.provider_kwargs(name))

        def _kw(name: str) -> dict:
            return dict(provider=_provider(name), executor=executor,
                        max_steps=cfg.max_steps, stream=cfg.stream_tokens)

        result = ResearchResult(workspace=cfg.workspace)

        try:
            await self._run_research(task, cfg, executor, _provider, _kw, result)
        except Exception as e:
            result.success = False
            await self._emit(Event.error("pipeline", f"Research pipeline crashed: {e}"))
        finally:
            # Always emit pipeline_done so forward() loop can exit
            try:
                await self._emit(Event.pipeline_done({
                    "verdict": "PASS" if result.success else "FAIL",
                    "workspace": str(cfg.workspace),
                }))
            except Exception:
                pass

        return result

    async def _run_research(self, task, cfg, executor, _provider, _kw, result):
        """Inner research logic — wrapped by run() for crash safety."""

        await self._emit(Event("pipeline", "agent_start",
                               {"task": "Researcher → Writer → Editor", "stage": "research"}))

        # ── Researcher ────────────────────────────────────────────────────────
        r_gate = AgentGate()
        await make_researcher(**_kw("researcher")).run(
            f"Research topic: {task}\nWrite research_notes.md in the workspace.",
            self._gated(r_gate, "researcher"),
        )
        researcher_summary, rv = await r_gate.wait()
        result.researcher_summary = researcher_summary

        if rv == "FAIL" or researcher_summary is None:
            await self._emit(Event.error("pipeline", "Researcher failed."))
            return result

        # Fallback: save researcher output as research_notes.md if not created
        notes_path = cfg.workspace / "research_notes.md"
        if not notes_path.exists() and researcher_summary:
            notes_path.write_text(researcher_summary, encoding="utf-8")

        # ── Writer → Editor loop ──────────────────────────────────────────────
        previous_feedback = ""

        for iteration in range(cfg.max_iterations):
            if iteration > 0:
                await self._emit(Event.iteration(iteration + 1,
                                                  f"Editor requested revision: {previous_feedback[:150]}"))

            # Writer
            w_gate    = AgentGate()
            w_task    = (
                f"Topic: {task}\nRead research_notes.md and write final_document.md."
                + (f"\n\nEditor feedback from previous revision:\n{previous_feedback}"
                   if previous_feedback else "")
            )
            await make_writer(**_kw("writer")).run(
                w_task, self._gated(w_gate, "writer"),
            )
            writer_summary, _ = await w_gate.wait()
            result.writer_summary = writer_summary

            if writer_summary is None:
                await self._emit(Event.error("pipeline", "Writer failed."))
                break

            # Editor
            e_gate = AgentGate()
            await make_editor(**_kw("editor")).run(
                f"Topic: {task}\nReview final_document.md and write editor_notes.md.",
                self._gated(e_gate, "editor"),
            )
            editor_summary, editor_verdict = await e_gate.wait()
            result.editor_summary = editor_summary

            if editor_verdict == "PASS" or iteration == cfg.max_iterations - 1:
                result.final_verdict = editor_verdict or "PASS"
                break

            previous_feedback = _extract_issues(editor_summary or "")

        result.success = result.final_verdict == "PASS"
        return result