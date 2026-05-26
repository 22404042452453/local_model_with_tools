"""ui/cli.py — Terminal UI with Rich Live"""

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import asyncio
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from core.config import Config
from core.events import Event
from pipeline.pipeline import Pipeline

console = Console()

COLORS = {
    "architect": "medium_purple1",
    "coder":     "medium_spring_green",
    "tester":    "steel_blue1",
    "reviewer":  "gold1",
    "pipeline":  "grey62",
}
ICONS = {
    "agent_start":"◆", "token":"", "thought":"💭", "tool_call":"⚡",
    "tool_result":"↩", "agent_done":"✓", "iteration":"↻",
    "pipeline_done":"🎉", "error":"✗",
}


class AgentStatus:
    STATES = {"idle":("dim","●"), "running":("green","●"),
              "done":("medium_spring_green","✓"), "error":("red","✗")}

    def __init__(self):
        self._s = {a:"idle" for a in ["architect","coder","tester","reviewer"]}

    def set(self, agent: str, state: str):
        self._s[agent] = state

    def render(self) -> Columns:
        cells = []
        for agent, state in self._s.items():
            style, sym = self.STATES.get(state, ("dim","●"))
            t = Text()
            t.append(f"{sym} ", style=style)
            t.append(agent.capitalize(), style=f"bold {COLORS[agent]}")
            t.append(f" [{state}]", style="dim")
            cells.append(Panel(t, expand=True, border_style="dim"))
        return Columns(cells, equal=True, expand=True)


class EventLog:
    MAX = 300

    def __init__(self):
        self._lines: list[Text] = []
        self._stream_line: Text | None = None

    def append(self, event: Event):
        color = COLORS.get(event.agent, "white")
        d     = event.data

        if event.type == "token":
            if self._stream_line is None:
                self._stream_line = Text()
                self._stream_line.append(f"💭 [{event.agent}] ", style=f"bold {color}")
                self._lines.append(self._stream_line)
            self._stream_line.append(d.get("chunk",""))
            return

        self._stream_line = None  # flush on non-token event
        icon  = ICONS.get(event.type, "·")
        line  = Text()
        line.append(f"{icon} " if icon else "  ", style="dim")
        line.append(f"[{event.agent}] ", style=f"bold {color}")

        if event.type == "agent_start":   body = (d.get("task",""))[:100]
        elif event.type == "thought":     body = d.get("text","")[:300]
        elif event.type == "tool_call":
            args = str(d.get("args",{})); body = f"{d.get('tool')}({args[:120]}{'…' if len(args)>120 else ''})"
        elif event.type == "tool_result":
            r = d.get("result",""); body = r[:200]+("…" if len(r)>200 else "")
        elif event.type == "agent_done":
            body = (d.get("output",""))[:160] + (f" · {d['verdict']}" if d.get("verdict") else "")
        elif event.type == "iteration":   body = f"Revision {d.get('n')} — {d.get('reason','')}"
        elif event.type == "pipeline_done": body = f"Done · {d.get('final_verdict','')} · {d.get('iterations',0)} iterations"
        elif event.type == "error":       body = d.get("message","")
        else: body = str(d)[:150]

        style = "white" if event.type == "thought" else (
                "gold1" if event.type == "tool_call" else
                "green" if event.type in ("agent_done","pipeline_done") else
                "red"   if event.type == "error" else "grey62")
        line.append(body, style=style)
        self._lines.append(line)
        if len(self._lines) > self.MAX:
            self._lines.pop(0)

    def render(self, height: int = 30) -> Panel:
        visible = self._lines[-height:]
        t = Text()
        for i, l in enumerate(visible):
            t.append_text(l)
            if i < len(visible)-1: t.append("\n")
        return Panel(t, title="[dim]feed[/dim]", border_style="dim", expand=True)


async def run_terminal(task: str, config: Config, clean: bool = False):
    pipeline = Pipeline(config)
    queue    = pipeline.subscribe()
    status   = AgentStatus()
    log      = EventLog()

    def layout():
        from rich.table import Table
        g = Table.grid(expand=True)
        g.add_row(status.render())
        g.add_row(log.render(height=console.height - 12))
        return g

    with Live(layout(), console=console, refresh_per_second=15, screen=False) as live:
        async def consume():
            while True:
                ev: Event = await queue.get()
                log.append(ev)
                if ev.type == "agent_start": status.set(ev.agent, "running")
                elif ev.type == "agent_done": status.set(ev.agent, "done")
                elif ev.type == "error" and ev.agent != "pipeline": status.set(ev.agent, "error")
                elif ev.type == "iteration":
                    for a in ["coder","tester","reviewer"]: status.set(a, "idle")
                live.update(layout())
                if ev.type in ("pipeline_done","error") and ev.agent == "pipeline":
                    break

        await asyncio.gather(
            asyncio.create_task(pipeline.run(task, clean_workspace=clean)),
            asyncio.create_task(consume()),
        )

    ws = config.workspace
    if ws.exists():
        files = [f for f in sorted(ws.rglob("*")) if f.is_file()]
        if files:
            console.print()
            console.print(Panel(
                "\n".join(f"  {f.relative_to(ws)}" for f in files),
                title="[bold green]Workspace[/bold green]", border_style="green"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Agent Terminal v2")
    parser.add_argument("task",        nargs="?")
    parser.add_argument("--backend",   default="anthropic")
    parser.add_argument("--model",     default=None)
    parser.add_argument("--url",       default=None)
    parser.add_argument("--steps",     type=int, default=25)
    parser.add_argument("--iters",     type=int, default=3)
    parser.add_argument("--workspace", default="./workspace")
    parser.add_argument("--clean",     action="store_true")
    parser.add_argument("--no-stream", action="store_true")
    args = parser.parse_args()

    cfg = Config.from_env()
    cfg.backend           = args.backend
    cfg.workspace         = Path(args.workspace)
    cfg.max_steps         = args.steps
    cfg.max_iterations    = args.iters
    cfg.stream_tokens     = not args.no_stream
    if args.model: cfg.model    = args.model
    if args.url:   cfg.base_url = args.url

    task = args.task or console.input("[bold]> Task:[/bold] ").strip()
    if task:
        asyncio.run(run_terminal(task, cfg, clean=args.clean))
