"""core/events.py — event types flowing through the pipeline"""

import time
from dataclasses import dataclass, field
from typing import Any, Literal

AgentName = Literal["architect", "coder", "tester", "reviewer", "planner", "researcher", "writer", "editor", "pipeline"]

EventType = Literal[
    "agent_start",    # agent begins
    "token",          # streaming token (char/word chunk)
    "thought",        # completed text block
    "tool_call",      # agent calls a tool
    "tool_result",    # tool result returned
    "agent_done",     # agent finished (includes verdict for tester/reviewer)
    "iteration",      # pipeline starting next loop (n, reason)
    "pipeline_done",  # all done
    "error",
]


@dataclass
class Event:
    agent: AgentName
    type:  EventType
    data:  dict[str, Any] = field(default_factory=dict)
    ts:    float          = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"agent": self.agent, "type": self.type, "data": self.data, "ts": self.ts}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def start(agent: AgentName, task: str)                    -> "Event": return Event(agent, "agent_start",  {"task": task})
    @staticmethod
    def token(agent: AgentName, chunk: str)                   -> "Event": return Event(agent, "token",        {"chunk": chunk})
    @staticmethod
    def thought(agent: AgentName, text: str)                  -> "Event": return Event(agent, "thought",      {"text": text})
    @staticmethod
    def tool_call(agent: AgentName, tool: str, args: dict)    -> "Event": return Event(agent, "tool_call",    {"tool": tool, "args": args})
    @staticmethod
    def tool_result(agent: AgentName, tool: str, result: str) -> "Event": return Event(agent, "tool_result",  {"tool": tool, "result": result})
    @staticmethod
    def done(agent: AgentName, output: str, verdict: str = "PASS") -> "Event":
        return Event(agent, "agent_done", {"output": output, "verdict": verdict})
    @staticmethod
    def iteration(n: int, reason: str)                        -> "Event": return Event("pipeline", "iteration", {"n": n, "reason": reason})
    @staticmethod
    def pipeline_done(outputs: dict)                          -> "Event": return Event("pipeline", "pipeline_done", {"outputs": outputs})
    @staticmethod
    def error(agent: AgentName, message: str)                 -> "Event": return Event(agent, "error", {"message": message})
