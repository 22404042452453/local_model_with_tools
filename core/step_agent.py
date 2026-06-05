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
        Builds a progress tracker so each step knows what's done and what's ahead.
        """
        total = len(steps)

        # ── Build progress list: short description per step ───────────────────
        progress: list[dict] = []
        for idx, s in enumerate(steps):
            short = s.prompt.split("\n")[0][:60]
            if s.expect:
                short = f"{s.expect}: {short}"
            progress.append({
                "idx":    idx + 1,
                "desc":   short,
                "status": "pending",   # pending → running → done / failed
                "result": "",          # brief outcome after completion
            })
        context["_progress"] = progress
        context["_progress_total"] = total

        for i, step in enumerate(steps):
            # Mark current step as running
            progress[i]["status"] = "running"

            short_desc = progress[i]["desc"]
            await emit(Event(self.name, "agent_start", {
                "task": f"Step {i+1}/{total}: {short_desc}",
                "stage": "step_progress",
                "step": i+1,
                "total": total,
            }))

            ok = await self._run_step(step, i, context, emit)

            # Update progress with outcome
            if ok:
                progress[i]["status"] = "done"
                # Capture brief result from context if available
                result_hint = self._get_step_result_hint(step, context)
                progress[i]["result"] = result_hint
            else:
                progress[i]["status"] = "failed"
                progress[i]["result"] = "FAILED"

            if not ok and step.required:
                await emit(Event.error(self.name,
                    f"Required step {i+1}/{total} failed: {short_desc}"))
                return False, context

        return True, context

    @staticmethod
    def _get_step_result_hint(step: Step, context: dict) -> str:
        """Extract a brief result description from the step's outcome."""
        if step.expect == "read_file":
            # How many chars were read
            for key in ("plan_content", "source_code"):
                if key in context:
                    val = context[key]
                    return f"{len(val)} chars" if isinstance(val, str) else "OK"
            return "OK"
        if step.expect == "write_file":
            current = context.get("_current_file", "")
            return f"→ {current}" if current else "written"
        if step.expect == "web_search":
            return "searched"
        if step.expect == "run_command":
            return "executed"
        return "OK"

    async def _run_step(
        self,
        step:    Step,
        index:   int,
        context: dict,
        emit:    EventCallback,
    ) -> bool:
        """Run one step with retries. Returns True on success."""
        import time as _time

        for attempt in range(step.max_retries + 1):
            if attempt > 0:
                short = step.prompt.split("\n")[0][:60]
                await emit(Event(self.name, "thought", {
                    "text": f"Retry {attempt}/{step.max_retries}: {short}",
                }))

            t0 = _time.perf_counter()
            result, tool_name = await self._call_step(step, context, emit, attempt)
            elapsed = _time.perf_counter() - t0

            if result is None:
                await emit(Event.step_done(
                    self.name, index, step.expect or "?",
                    elapsed_sec=elapsed, ok=False,
                ))
                continue  # provider error → retry

            # Validate result
            if step.validate:
                ok, error = step.validate(result)
                if not ok:
                    await emit(Event.error(self.name, f"Step {index+1} validation: {error}"))
                    context[f"_step_{index}_error"] = error
                    await emit(Event.step_done(
                        self.name, index, tool_name or step.expect or "?",
                        elapsed_sec=elapsed, ok=False,
                    ))
                    continue

            # ── Emit step_done with timing ────────────────────────────────────
            await emit(Event.step_done(
                self.name, index, tool_name or step.expect or "?",
                elapsed_sec=elapsed, ok=True,
            ))

            # ── Emit file_changed for write_file / edit_file ──────────────────
            if tool_name in ("write_file", "edit_file"):
                filepath = self._extract_filepath_from_result(result, step, context)
                size = len(result.encode("utf-8")) if result else 0
                preview = result[:300] if result else ""
                action = "write" if tool_name == "write_file" else "edit"
                await emit(Event.file_changed(
                    self.name, filepath, action=action,
                    size=size, preview=preview,
                ))

            # Store result via callback
            if step.on_result:
                step.on_result(result, context)

            return True

        return False

    def _extract_filepath_from_result(self, result: str, step: Step, context: dict) -> str:
        """Extract filepath from write_file result or context."""
        # Result usually starts with "Written 1234 chars -> main.py"
        if "->" in result:
            return result.split("->")[-1].strip()
        # Fallback to context
        return context.get("_current_file", step.expect or "unknown")

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

        # ── Pre-write quality gate: reject garbage content before disk write ──
        if name == "write_file" and "content" in args:
            filepath = args.get("path", "")
            content = args["content"]
            if filepath.endswith(".py") and isinstance(content, str):
                if not self._validate_code_quality(content):
                    err = "Content rejected by quality gate (repetitive, garbage, or no meaningful code)"
                    await emit(Event.tool_call(self.name, name, {"path": filepath, "content": "[REJECTED]"}))
                    await emit(Event.error(self.name, err))
                    err_key = f"_step_{id(step)}_error"
                    context[err_key] = err
                    return err, name

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

    @property
    def _is_simple_model(self) -> bool:
        """Check if provider is a small model without tool support.
        Simple models get dramatically shorter prompts."""
        return getattr(self.provider, '_supports_tools', None) is False

    def _no_think_prefix(self) -> str:
        """Add /no_think for qwen3 models to disable slow reasoning."""
        # Detect qwen3 from provider model name if available
        model = getattr(getattr(self, 'provider', None), 'model', '') or ''
        if 'qwen3' in model.lower() or 'qwen2.5' in model.lower():
            return "/no_think\n"
        return ""

    def _build_prompt(self, step: Step, context: dict, attempt: int) -> str:
        """Build a focused prompt for this step."""
        # ── Simple model: ultra-short prompts for 1-3B parameter models ───────
        if self._is_simple_model:
            return self._build_simple_prompt(step, context, attempt)

        prefix = self._no_think_prefix()
        lines = [prefix]

        # ── Progress tracker: what's done, current, remaining ─────────────────
        progress = context.get("_progress", [])
        if progress and len(progress) > 1:
            total = context.get("_progress_total", len(progress))
            current_idx = None
            for p in progress:
                if p["status"] == "running":
                    current_idx = p["idx"]
                    break

            if current_idx is not None:
                prog_lines = [f"── PROGRESS {current_idx}/{total} ──"]
                for p in progress:
                    idx = p["idx"]
                    desc = p["desc"][:50]
                    if p["status"] == "done":
                        hint = f" ({p['result']})" if p["result"] else ""
                        prog_lines.append(f"  ✅ {idx}. {desc}{hint}")
                    elif p["status"] == "running":
                        prog_lines.append(f"  ▸  {idx}. {desc}  ← YOU ARE HERE")
                    elif p["status"] == "failed":
                        prog_lines.append(f"  ❌ {idx}. {desc} (FAILED)")
                    else:
                        prog_lines.append(f"  ○  {idx}. {desc}")
                prog_lines.append("────────────────────────")
                lines.append("\n".join(prog_lines))

        # ── Step prompt ───────────────────────────────────────────────────────
        lines.append(step.prompt)

        # ── Fix 1: Cross-Step Context ─────────────────────────────────────────
        # inject already-written functions so implement steps are consistent.
        # Without this, Star.draw() doesn't know what instance vars __init__ set.
        if step.expect == "write_file" and not step.args:
            pieces = context.get("_pieces", [])
            if pieces:
                summary_lines = []
                for p in pieces[-6:]:          # last 6 to avoid context bloat
                    name  = p.get("name", "?")
                    cls   = p.get("class", "")
                    code  = p.get("code", "")
                    # Extract first non-empty, non-pass line as a hint
                    hint  = _extract_signature_hint(code)
                    label = f"{cls}.{name}" if cls else name
                    summary_lines.append(f"  • {label}: {hint}")
                if summary_lines:
                    lines.append(
                        "\n── Already written in this file ──\n"
                        + "\n".join(summary_lines)
                        + "\nUse consistent variable names and call signatures with the above."
                    )

        # ── read_file: inject files_list so model knows which file to read ────
        if step.expect == "read_file" and not step.args and "files_list" in context:
            files_raw = str(context["files_list"])
            skip = {"test_", "__init__", "plan.md", "review.md"}
            py_candidates = []
            for ln in files_raw.splitlines():
                name = ln.strip().split()[0] if ln.strip() else ""
                if name.endswith(".py") and not any(s in name for s in skip):
                    py_candidates.append(name)
            if py_candidates:
                target = py_candidates[0]
                lines.append(
                    f"\nWorkspace files:\n{files_raw[:400]}\n"
                    f"Call read_file(path=\"{target}\") now."
                )

        # ── write_file few-shot example ───────────────────────────────────────
        if step.expect == "write_file" and not step.args:
            file = context.get("_current_file", "main.py")
            plan = context.get("plan_content", "")
            if "fastapi" in plan.lower() or "FastAPI" in plan:
                example_code = "from fastapi import FastAPI\\napp = FastAPI()"
            elif "flask" in plan.lower():
                example_code = "from flask import Flask\\napp = Flask(__name__)"
            else:
                example_code = "# Complete implementation\\ndef main():\\n    pass"
            lines.append(_few_shot_write(file, example_code))

        # ── Fix 2: Self-Debug on retry ────────────────────────────────────────
        # Research: Self-Debugging (Chen et al., ICLR 2024) — making the model
        # explain the error before rewriting gives +2-9% accuracy.
        # On attempt > 0: inject the error + ask for explanation first.
        err_key = f"_step_{id(step)}_error"
        if attempt > 0:
            err = context.get(err_key, "unknown error")
            if attempt == 1:
                # First retry: ask model to explain the error, then fix
                lines.append(
                    f"\n❌ Previous attempt failed: {err}\n"
                    f"Before rewriting, explain in ONE sentence what caused this error "
                    f"and what you will change. Then call write_file with the fix."
                )
            else:
                # Second retry: direct fix instruction with no extra thinking
                lines.append(
                    f"\n❌ Attempt {attempt} failed: {err}\n"
                    f"Fix ONLY the specific error above. "
                    f"Use RELATIVE paths (e.g. 'main.py' not '/main.py')."
                )

        return "\n".join(lines)

    def _build_simple_prompt(self, step: Step, context: dict, attempt: int) -> str:
        """Ultra-short prompt for small models (1-3B params) that can't handle complex instructions.
        No progress tracker, no cross-step context, no tool examples — just the task."""
        lines = []

        if step.expect == "write_file" and not step.args:
            filename = context.get("_current_file", self._infer_filename(step.prompt) or "main.py")
            # Extract function/class name from step prompt if available
            func_hint = ""
            import re as _re
            fn_match = _re.search(r'(?:function|def|class|implement)\s+[`\'"]*(\w+)', step.prompt, _re.IGNORECASE)
            if fn_match:
                func_hint = f" for function `{fn_match.group(1)}`"

            # Include plan context if available (but keep it short)
            plan = context.get("plan_content", "")
            plan_hint = ""
            if plan:
                # Extract just the relevant section (first 400 chars)
                plan_hint = f"\nProject plan:\n{plan[:400]}\n"

            if attempt > 0:
                err_key = f"_step_{id(step)}_error"
                err = context.get(err_key, "syntax error")
                lines.append(
                    f"Previous code had error: {err}\n"
                    f"Write corrected Python code for {filename}{func_hint}.\n"
                    f"Output ONLY valid Python code. No explanations."
                )
            else:
                lines.append(
                    f"Write Python code for {filename}{func_hint}.{plan_hint}\n"
                    f"Output ONLY valid Python code. No explanations, no markdown."
                )

            # Add already-written pieces as minimal context
            pieces = context.get("_pieces", [])
            if pieces:
                sig_lines = []
                for p in pieces[-3:]:
                    name = p.get("name", "")
                    code = p.get("code", "")
                    # Just show the def line
                    for cl in code.splitlines():
                        if cl.strip().startswith("def ") or cl.strip().startswith("class "):
                            sig_lines.append(cl.strip())
                            break
                if sig_lines:
                    lines.append("Already written:\n" + "\n".join(sig_lines))

        elif step.expect == "read_file":
            lines.append(step.prompt)

        elif step.expect == "run_command":
            lines.append(step.prompt)

        else:
            # Generic fallback: just the step prompt, stripped down
            lines.append(step.prompt)

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
        """Extract the BEST code block from model output.
        Picks the highest-quality block, not just the first one."""
        # Find all code blocks
        blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)

        if not blocks:
            # No code block — try whole text if it looks like code
            if any(kw in text for kw in ("def ", "class ", "import ", "from ")):
                candidate = text.strip()
                if self._validate_code_quality(candidate):
                    return candidate
            return None

        # Score each block and pick the best
        best, best_score = None, -1
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            score = self._score_code_block(block)
            if score > best_score:
                best, best_score = block, score

        if best and self._validate_code_quality(best):
            return best
        return None

    @staticmethod
    def _score_code_block(code: str) -> int:
        """Score a code block by quality signals. Higher = better."""
        score = 0
        lines = code.splitlines()
        score += min(len(lines), 100)         # length (capped)
        score += code.count("def ") * 15      # has functions
        score += code.count("class ") * 15    # has classes
        score += code.count("return ") * 5    # has returns
        # Penalties
        if "write_file" in code:   score -= 50   # recursive tool call = garbage
        if "pandasas" in code:     score -= 100
        if "from write_file" in code: score -= 100
        if "import pandasas" in code: score -= 100
        # Repetition penalty
        unique = set(line.strip() for line in lines if line.strip())
        if len(lines) > 5 and len(unique) < len(lines) * 0.4:
            score -= 80  # >60% duplicate lines
        return score

    @staticmethod
    def _validate_code_quality(code: str) -> bool:
        """Reject obviously garbage code before writing to disk.
        Returns True if code passes basic sanity checks."""
        if not code or len(code.strip()) < 10:
            return False

        lines = [l for l in code.splitlines() if l.strip()]
        if not lines:
            return False

        # ── Reject repetitive content ─────────────────────────────────────────
        from collections import Counter
        line_counts = Counter(line.strip() for line in lines)
        if line_counts and len(lines) > 5:
            most_common_count = line_counts.most_common(1)[0][1]
            if most_common_count > len(lines) * 0.5:
                return False  # >50% identical lines

        # ── Reject recursive tool-call garbage ────────────────────────────────
        garbage_patterns = [
            "from write_file import",
            "from remember import",
            "from recall import",
            "from finish import",
            "import pandasas",
            "write_file(path=",
            'write_file("',
            "write_file('",
        ]
        garbage_count = sum(1 for p in garbage_patterns if p in code)
        if garbage_count >= 2:
            return False

        # ── Reject excessive non-ASCII in code (gibberish detection) ──────────
        # Only reject if code has NO meaningful constructs AND is mostly non-ASCII.
        # Code with def/class/import + Russian/CJK strings is legitimate.
        has_def   = "def " in code
        has_class = "class " in code
        has_assign = "=" in code and "==" not in code.replace("==", "")
        has_import = "import " in code
        has_meaningful = has_def or has_class or has_assign or has_import

        non_ascii = sum(1 for c in code if ord(c) > 127)
        if len(code) > 50 and non_ascii / len(code) > 0.15:
            if not has_meaningful:
                return False  # High non-ASCII + no code constructs = garbage

        # ── Must have at least one meaningful construct ───────────────────────
        if not has_meaningful:
            return False

        return True

    async def _call_provider(
        self,
        messages: list[dict],
        tools:    list[dict],
        emit:     EventCallback,
    ) -> dict | None:
        # Compress message history before sending — prevents context bloat
        # when implement_context accumulates many pieces across steps.
        messages = self.compressor.compress_messages(messages)

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


# ── Module-level helpers ──────────────────────────────────────────────────────

def _extract_signature_hint(code: str) -> str:
    """Pull the first meaningful line from a piece of code as a hint."""
    if not code:
        return "(empty)"
    for line in code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped != "pass":
            return stripped[:80] + ("…" if len(stripped) > 80 else "")
    return "(pass only)"