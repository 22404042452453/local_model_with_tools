"""
pipeline/supervisor.py — Agent Manager (Supervisor)

Wraps any agent run with:
  1. Retry on failure (up to max_retries)
  2. Timeout enforcement (kills hung agents)
  3. Quality gate (checks output meets minimum criteria)
  4. Health reporting (tracks success/fail per agent)

Usage:
    supervisor = Supervisor(config)
    summary, verdict = await supervisor.run_agent(agent, task, emit)
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from core.agent import BaseAgent, EventCallback
from core.events import Event


@dataclass
class AgentHealth:
    """Tracks an agent's health across runs."""
    agent_name:    str
    total_runs:    int   = 0
    successes:     int   = 0
    failures:      int   = 0
    retries:       int   = 0
    total_time:    float = 0.0
    last_error:    str   = ""

    @property
    def success_rate(self) -> float:
        return (self.successes / self.total_runs * 100) if self.total_runs else 0

    @property
    def avg_time(self) -> float:
        return (self.total_time / self.total_runs) if self.total_runs else 0

    def to_dict(self) -> dict:
        return {
            "agent":        self.agent_name,
            "runs":         self.total_runs,
            "successes":    self.successes,
            "failures":     self.failures,
            "retries":      self.retries,
            "success_rate": f"{self.success_rate:.0f}%",
            "avg_time":     f"{self.avg_time:.1f}s",
            "last_error":   self.last_error,
        }


@dataclass
class SupervisorConfig:
    max_retries:     int   = 2      # retries per agent on failure
    agent_timeout:   int   = 300    # seconds before killing an agent (5 min)
    min_output_len:  int   = 10     # minimum chars in output to pass quality gate
    require_verdict: bool  = True   # require explicit PASS/FAIL verdict


class Supervisor:
    """
    Wraps agent execution with retry, timeout, and quality checks.
    """

    def __init__(self, config: SupervisorConfig | None = None):
        self.config = config or SupervisorConfig()
        self._health: dict[str, AgentHealth] = {}

    def _get_health(self, name: str) -> AgentHealth:
        if name not in self._health:
            self._health[name] = AgentHealth(agent_name=name)
        return self._health[name]

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run_agent(
        self,
        agent: BaseAgent,
        task: str,
        emit: EventCallback,
    ) -> tuple[str | None, str]:
        """
        Run an agent with supervision.
        
        Returns (summary, verdict) — same as BaseAgent.run().
        Retries on failure, enforces timeout, checks output quality.
        """
        health  = self._get_health(agent.name)
        retries = 0

        while retries <= self.config.max_retries:
            health.total_runs += 1
            start = time.time()

            if retries > 0:
                await emit(Event("pipeline", "agent_start", {
                    "task":  f"Retry #{retries} for {agent.name}",
                    "stage": "supervisor_retry",
                    "retry": retries,
                }))

            try:
                # Run with timeout
                summary, verdict = await asyncio.wait_for(
                    agent.run(task, emit),
                    timeout=self.config.agent_timeout,
                )
            except asyncio.TimeoutError:
                health.failures += 1
                health.last_error = f"Timeout after {self.config.agent_timeout}s"
                await emit(Event.error(agent.name,
                    f"Agent timed out after {self.config.agent_timeout}s"))
                retries += 1
                health.retries += 1
                continue
            except Exception as e:
                health.failures += 1
                health.last_error = str(e)
                await emit(Event.error(agent.name, f"Agent crashed: {e}"))
                retries += 1
                health.retries += 1
                continue

            elapsed = time.time() - start
            health.total_time += elapsed

            # ── Quality gate ──────────────────────────────────────────────────
            if summary is None:
                health.failures += 1
                health.last_error = "Agent returned None"
                await emit(Event.error(agent.name, "Agent returned no output"))
                retries += 1
                health.retries += 1
                continue

            if len(summary) < self.config.min_output_len:
                health.failures += 1
                health.last_error = f"Output too short ({len(summary)} chars)"
                await emit(Event.error(agent.name,
                    f"Output too short: {len(summary)} chars (min {self.config.min_output_len})"))
                retries += 1
                health.retries += 1
                continue

            # Success
            health.successes += 1
            return summary, verdict

        # All retries exhausted
        await emit(Event.error(agent.name,
            f"All {self.config.max_retries + 1} attempts failed. "
            f"Last error: {health.last_error}"))
        return None, "FAIL"

    # ── Health reporting ──────────────────────────────────────────────────────

    def get_health(self, agent_name: str | None = None) -> dict | list[dict]:
        """Get health report for one or all agents."""
        if agent_name:
            return self._get_health(agent_name).to_dict()
        return [h.to_dict() for h in self._health.values()]

    def reset_health(self) -> None:
        self._health.clear()

    def get_summary(self) -> str:
        """Human-readable health summary."""
        if not self._health:
            return "No agents have run yet."
        lines = ["Agent Health Report:", "─" * 50]
        for h in self._health.values():
            status = "✓" if h.success_rate >= 80 else ("⚠" if h.success_rate >= 50 else "✗")
            lines.append(
                f"  {status} {h.agent_name:12s}  "
                f"{h.successes}/{h.total_runs} runs  "
                f"({h.success_rate:.0f}%)  "
                f"avg {h.avg_time:.1f}s  "
                f"retries: {h.retries}"
            )
            if h.last_error:
                lines.append(f"    └─ last error: {h.last_error[:100]}")
        return "\n".join(lines)
