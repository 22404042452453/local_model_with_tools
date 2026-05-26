"""
core/step_agent.py — StepAgent

Pipeline controls what the model does at each step.
Each step = one LLM call with one expected tool call.

Instead of:
    agent.run("write the whole app")  # model decides everything

Now:
    agent.run_steps([
        Step("Read the plan", expect="read_file", args={"path": "plan.md"}),
        Step("Write main.py", expect="write_file"),
        Step("Verify syntax",  expect="run_command", args={"command": "python -m py_compile main.py"}),
    ])

Benefits for small models:
  - Can't skip steps (pipeline enforces sequence)
  - Each prompt is tiny and focused
  - Validation happens after every step
  - Retry is specific ("write_file failed, try again with this error")
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.events import AgentName, Event
from core.providers import BaseProvider
from core.compressor import ContextCompressor

EventCallback = Callable[[Event], Awaitable[None]]


# ── Step definition ───────────────────────────────────────────────────────────

@dataclass
class Step:
    """
    One atomic step for a StepAgent.

    Fields:
        prompt      : instruction sent to the model (appended to system prompt)
        expect      : tool name the model MUST call (None = free call)
        args        : if set, these args are FORCED (model can't change them)
        required    : if True and step fails, abort the whole agent
        max_retries : how many times to retry this step on failure
        validate    : callable(result) → (ok: bool, error: str)
        on_result   : callable(result, context) → None — store result in context
    """
    prompt:      str
    expect:      str  | None = None
    args:        dict | None = None          # forced args (skip LLM for this step)
    required:    bool        = True
    max_retries: int         = 2
    validate:    Callable[[str], tuple[bool, str]] | None = None
    on_result:   Callable[[str, dict], None]         | None = None


# ── Few-shot example builder ──────────────────────────────────────────────────

def _few_shot(tool_name: str, example_args: dict) -> str:
    """Build a few-shot example string for a tool call."""
    args_str = json.dumps(example_args, ensure_ascii=False, indent=2)
    warning = ""
    if tool_name == "write_file":
        warning = (
            "\n⚠️  IMPORTANT RULES:\n"
            "- path must be RELATIVE (e.g. 'main.py' not '/main.py')\n"
            "- content must be COMPLETE working code (no '...' or 'pass')\n"
        )
    return (
        f"{warning}\n"
        f"Call {tool_name} EXACTLY like this example:\n"
        f"```\n{tool_name}({args_str})\n```"
    )


def _few_shot_write(filename: str, code_example: str) -> str:
    """Rich few-shot for write_file with real code snippet."""
    return (
        f"\n⚠️  RULES: path is RELATIVE ('{filename}' not '/{filename}'), "
        f"content is COMPLETE code.\n\n"
        f"Call write_file now:\n"
        f"write_file(path=\"{filename}\", content=\"{code_example[:80]}...\")"
    )


# ── StepAgent ─────────────────────────────────────────────────────────────────

class StepAgent:
    """
    Executes a predefined sequence of steps.
    Each step = one LLM call with one expected output.
    """

    def __init__(
        self,
        name:          AgentName,
        provider:      BaseProvider,
        tools:         list[dict],
        executor,
        system:        str,
        stream_tokens: bool = True,
        compressor:    ContextCompressor | None = None,
    ):
        self.name          = name
        self.provider      = provider
        self.tools         = tools
        self.executor      = executor
        self.system        = system
        self.stream_tokens = stream_tokens
        self.compressor    = compressor or ContextCompressor()

    async def run_steps(
        self,
        steps:   list[Step],
        context: dict,
        emit:    EventCallback,
    ) -> tuple[bool, dict]:
        """
        Execute steps in sequence.

        context: shared dict passed between steps (for on_result callbacks)
        Returns (success, context)
        """
        for i, step in enumerate(steps):
            ok = await self._run_step(step, i, context, emit)
            if not ok and step.required:
                await emit(Event.error(self.name,
                    f"Required step {i+1} failed: {step.prompt[:60]}"))
                return False, context
        return True, context

    async def _run_step(
        self,
        step:    Step,
        index:   int,
        context: dict,
        emit:    EventCallback,
    ) -> bool:
        """Run one step with retries. Returns True on success."""

        for attempt in range(step.max_retries + 1):
            if attempt > 0:
                await emit(Event("pipeline", "agent_start", {
                    "task":  f"Retry step {index+1}/{attempt}: {step.prompt[:50]}",
                    "stage": "step_retry",
                }))

            result, tool_name = await self._call_step(step, context, emit, attempt)

            if result is None:
                continue  # provider error → retry

            # Validate result
            if step.validate:
                ok, error = step.validate(result)
                if not ok:
                    await emit(Event.error(self.name, f"Step {index+1} validation: {error}"))
                    # Put error in context for next retry
                    context[f"_step_{index}_error"] = error
                    continue

            # Store result via callback
            if step.on_result:
                step.on_result(result, context)

            return True

        return False

    async def _call_step(
        self,
        step:    Step,
        context: dict,
        emit:    EventCallback,
        attempt: int,
    ) -> tuple[str | None, str | None]:
        """
        Call the LLM for one step.
        Returns (result_str, tool_name_called) or (None, None) on error.
        """
        # If args are fully forced — skip LLM, execute directly
        if step.args is not None and step.expect is not None:
            memory = context.get("_memory", {})
            result, _ = self.executor(step.expect, step.args, memory)
            await emit(Event.tool_call(self.name, step.expect, step.args))
            display = result[:600] + ("..." if len(result) > 600 else "")
            await emit(Event.tool_result(self.name, step.expect, display))
            return result, step.expect

        # Build focused prompt for this step
        prompt = self._build_prompt(step, context, attempt)

        # Only expose the expected tool (fewer choices = fewer mistakes)
        tools = self._filter_tools(step.expect)

        messages = [{"role": "user", "content": prompt}]
        resp = await self._call_provider(messages, tools, emit)

        if resp is None:
            return None, None

        # Strip thinking
        text = self._strip_thinking(resp.get("text", ""))
        if text:
            await emit(Event.thought(self.name, text))

        tool_calls = resp.get("tool_calls", [])
        if not tool_calls:
            # ── #3: Forced tool call — model returned text without calling write_file ──
            if step.expect == "write_file" and text:
                extracted = self._extract_code_block(text)
                if extracted:
                    # Infer filename from context or step prompt
                    filename = (context.get("_current_file")
                                or self._infer_filename(step.prompt)
                                or "main.py")
                    await emit(Event.tool_call(self.name, "write_file",
                                               {"path": filename, "content": "[extracted from text]"}))
                    memory = context.get("_memory", {})
                    result, _ = self.executor("write_file",
                                              {"path": filename, "content": extracted}, memory)
                    await emit(Event.tool_result(self.name, "write_file", result))
                    # Run syntax check on extracted code
                    if filename.endswith(".py"):
                        syntax_ok, syntax_err = self._check_syntax_on_disk(
                            filename, context.get("_workspace"))
                        if not syntax_ok:
                            await emit(Event.error(self.name, f"Syntax error in {filename}: {syntax_err}"))
                            return f"Write error: {syntax_err}", "write_file"
                    return result, "write_file"
            return None, None

        # Execute first tool call
        tc = tool_calls[0]
        name, args = tc["name"], tc["arguments"]

        # Normalize path args
        if name in ("read_file", "write_file") and "path" in args:
            args = dict(args)
            args["path"] = args["path"].lstrip("/\\")

        await emit(Event.tool_call(self.name, name, args))
        memory = context.get("_memory", {})
        result, _ = self.executor(name, args, memory)
        compressed = self.compressor.compress_tool_result(name, result)
        display = compressed[:600] + ("..." if len(compressed) > 600 else "")
        await emit(Event.tool_result(self.name, name, display))

        # ── #4: Post-write syntax validation ──────────────────────────────────
        if name == "write_file" and result.startswith("Written"):
            filepath = args.get("path", "")
            if filepath.endswith(".py"):
                syntax_ok, syntax_err = self._check_syntax_on_disk(
                    filepath, context.get("_workspace"))
                if not syntax_ok:
                    await emit(Event.error(self.name,
                        f"Syntax error in {filepath}: {syntax_err}"))
                    # Return error so step retries with specific error message
                    err_key = f"_step_{id(step)}_error"
                    context[err_key] = f"File written but has syntax error: {syntax_err}"
                    return f"Syntax error: {syntax_err}", name

        return compressed, name

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _no_think_prefix(self) -> str:
        """Add /no_think for qwen3 models to disable slow reasoning."""
        # Detect qwen3 from provider model name if available
        model = getattr(getattr(self, 'provider', None), 'model', '') or ''
        if 'qwen3' in model.lower() or 'qwen2.5' in model.lower():
            return "/no_think\n"
        return ""

    def _build_prompt(self, step: Step, context: dict, attempt: int) -> str:
        """Build a focused prompt for this step."""
        prefix = self._no_think_prefix()
        lines = [prefix + step.prompt]

        # Few-shot example for write_file
        if step.expect == "write_file" and not step.args:
            file = context.get("_current_file", "main.py")
            # Infer a good example from context
            plan = context.get("plan_content", "")
            if "fastapi" in plan.lower() or "FastAPI" in plan:
                example_code = "from fastapi import FastAPI\\napp = FastAPI()"
            elif "flask" in plan.lower():
                example_code = "from flask import Flask\\napp = Flask(__name__)"
            else:
                example_code = "# Complete implementation\\ndef main():\\n    pass"
            lines.append(_few_shot_write(file, example_code))

        # Add previous error context on retry — be specific
        err_key = f"_step_{id(step)}_error"
        if attempt > 0:
            err = context.get(err_key, "unknown error")
            lines.append(
                f"\n❌ Previous attempt #{attempt} failed: {err}\n"
                f"Fix the issue and try again. "
                f"Make sure to use RELATIVE paths (e.g. 'main.py' not '/main.py')."
            )

        return "\n".join(lines)

    def _filter_tools(self, expect: str | None) -> list[dict]:
        """
        When a step expects a specific tool, only expose that tool + finish.
        Fewer choices = model more likely to pick the right one.
        """
        if expect is None:
            return self.tools
        focused = [t for t in self.tools if t["name"] in (expect, "finish", "remember", "recall")]
        return focused or self.tools

    def _strip_thinking(self, text: str | None) -> str:
        if not text:
            return ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if text.startswith("Thinking..."):
            text = text[len("Thinking..."):].strip()
        return text

    def _check_syntax_on_disk(self, filepath: str, workspace) -> tuple[bool, str]:
        """Check Python syntax of a file that was just written."""
        import ast
        from pathlib import Path

        if workspace is None:
            return True, ""
        try:
            full_path = Path(workspace) / filepath.lstrip("/\\")
            if not full_path.exists():
                return True, ""  # file doesn't exist yet — skip
            source = full_path.read_text(encoding="utf-8")
            ast.parse(source)
            return True, ""
        except SyntaxError as e:
            return False, f"line {e.lineno}: {e.msg}"
        except Exception as e:
            return True, ""  # non-syntax error — don't block

    def _infer_filename(self, prompt: str) -> str | None:
        """Try to extract a filename from the step prompt."""
        match = re.search(r'\b([\w/]+\.[a-z]{2,4})\b', prompt)
        if match:
            return match.group(1).lstrip("/\\")
        return None

    def _extract_code_block(self, text: str) -> str | None:
        """Extract code from markdown code block if model forgot to call write_file."""
        match = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # No code block — return the whole text if it looks like code
        if any(kw in text for kw in ("def ", "class ", "import ", "from ")):
            return text.strip()
        return None

    async def _call_provider(
        self,
        messages: list[dict],
        tools:    list[dict],
        emit:     EventCallback,
    ) -> dict | None:
        if not self.stream_tokens:
            try:
                return await asyncio.to_thread(
                    self.provider.complete, messages, tools, self.system, None)
            except Exception as e:
                await emit(Event.error(self.name, str(e)))
                return None

        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()

        def on_token(chunk: str):
            loop.call_soon_threadsafe(q.put_nowait, ("token", chunk))

        def run():
            try:
                result = self.provider.complete(messages, tools, self.system, on_token)
                loop.call_soon_threadsafe(q.put_nowait, ("done", result))
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))

        threading.Thread(target=run, daemon=True).start()

        while True:
            kind, payload = await q.get()
            if kind == "token":
                await emit(Event.token(self.name, payload))
            elif kind == "done":
                return payload
            else:
                await emit(Event.error(self.name, payload))
                return None
