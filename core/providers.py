"""core/providers.py — Anthropic + OpenAI-compatible providers with streaming"""

import json
import os
from abc import ABC, abstractmethod
from typing import Callable

TokenCallback = Callable[[str], None]


class BaseProvider(ABC):
    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict], system: str,
                 on_token: TokenCallback | None = None) -> dict:
        """
        Returns:
            {"text": str, "tool_calls": [...], "done": bool}

        on_token: called with each text chunk when streaming is active.
                  Not called for tool-use output.
        """


# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicProvider(BaseProvider):

    def __init__(self, model: str = "claude-sonnet-4-20250514",
                 api_key: str | None = None, max_tokens: int = 2048):
        import anthropic
        self.client     = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model      = model
        self.max_tokens = max_tokens

    def _msgs(self, messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    content.append({"type": "tool_use", "id": tc["id"],
                                    "name": tc["name"], "input": tc["arguments"]})
                out.append({"role": "assistant", "content": content})
            elif m["role"] == "tool":
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"]}
                    for r in m["results"]
                ]})
        return out

    def _tools(self, tools: list[dict]) -> list[dict]:
        return [{"name": t["name"], "description": t["description"],
                 "input_schema": t["parameters"]} for t in tools]

    def complete(self, messages, tools, system, on_token=None) -> dict:
        kwargs = dict(model=self.model, max_tokens=self.max_tokens, system=system,
                      tools=self._tools(tools), messages=self._msgs(messages))

        if on_token:
            # Streaming mode
            text = ""
            tool_calls = []
            with self.client.messages.stream(**kwargs) as stream:
                for chunk in stream.text_stream:
                    text += chunk
                    on_token(chunk)
                final = stream.get_final_message()
            for block in final.content:
                if hasattr(block, "name"):
                    tool_calls.append({"id": block.id, "name": block.name,
                                       "arguments": block.input})
            return {"text": text, "tool_calls": tool_calls,
                    "done": final.stop_reason == "end_turn"}
        else:
            # Non-streaming
            resp = self.client.messages.create(**kwargs)
            text = ""
            tool_calls = []
            for block in resp.content:
                if hasattr(block, "text"):  text = block.text
                elif hasattr(block, "name"):
                    tool_calls.append({"id": block.id, "name": block.name,
                                       "arguments": block.input})
            return {"text": text, "tool_calls": tool_calls,
                    "done": resp.stop_reason == "end_turn"}


# ── OpenAI-compatible ─────────────────────────────────────────────────────────

class OpenAICompatibleProvider(BaseProvider):
    """
    OpenAI-compatible provider with automatic prompt-based tool fallback.

    If the model returns HTTP 400 "does not support tools", the provider
    switches to prompt-based mode: tool definitions are embedded in the
    system prompt, and the model responds with JSON that we parse into
    tool_calls.  This makes models like deepcoder:1.5b usable in the
    pipeline despite lacking native tool-calling support.
    """

    _call_counter: int = 0   # for generating synthetic tool-call IDs
    _MAX_OUTPUT_CHARS = 8000  # hard cap on model output to prevent infinite generation

    @staticmethod
    def _detect_repetition(text: str, window: int = 150, min_len: int = 500) -> bool:
        """Detect if model is stuck in a repetitive loop.
        Checks if the last `window` chars appeared earlier in the output."""
        if len(text) < min_len:
            return False
        tail = text[-window:]
        # Check if this exact tail appears earlier
        earlier = text[:-window]
        if tail in earlier:
            return True
        # Also check line-level repetition: >60% identical lines = loop
        lines = text.strip().splitlines()
        if len(lines) > 10:
            from collections import Counter
            counts = Counter(line.strip() for line in lines if line.strip())
            if counts and counts.most_common(1)[0][1] > len(lines) * 0.5:
                return True
        return False

    def __init__(self, model: str = "llama3.1",
                 base_url: str = "http://localhost:11434/v1",
                 api_key: str = "ollama", max_tokens: int = 2048,
                 supports_tools: bool | None = None):
        from openai import OpenAI
        self.client          = OpenAI(base_url=base_url, api_key=api_key)
        self.model           = model
        self.max_tokens      = max_tokens
        self._supports_tools = supports_tools   # None=auto-detect, False=skip native tools

    # ── Message formatting (native tool mode) ─────────────────────────────────

    def _msgs(self, messages: list[dict], system: str) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg: dict = {"role": "assistant", "content": m.get("content") or ""}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"],
                                      "arguments": json.dumps(tc["arguments"])}}
                        for tc in m["tool_calls"]
                    ]
                out.append(msg)
            elif m["role"] == "tool":
                for r in m["results"]:
                    out.append({"role": "tool", "tool_call_id": r["id"],
                                "content": r["content"]})
        return out

    # ── Message formatting (prompt-based fallback) ────────────────────────────

    def _msgs_no_tools(self, messages: list[dict], system: str, tools: list[dict]) -> list[dict]:
        """Convert messages for models without tool support.
        Tool calls/results become plain text in the conversation."""
        tools_prompt = self._build_tools_prompt(tools)
        out = [{"role": "system", "content": f"{system}\n\n{tools_prompt}"}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                parts = []
                if m.get("content"):
                    parts.append(m["content"])
                for tc in m.get("tool_calls", []):
                    parts.append(json.dumps(
                        {"tool": tc["name"], "arguments": tc["arguments"]},
                        ensure_ascii=False))
                out.append({"role": "assistant", "content": "\n".join(parts) or ""})
            elif m["role"] == "tool":
                results = []
                for r in m["results"]:
                    results.append(f"[Tool result]: {r['content']}")
                out.append({"role": "user", "content": "\n".join(results)})
        return out

    @staticmethod
    def _build_tools_prompt(tools: list[dict]) -> str:
        """Build tool instructions for the system prompt.
        For models without native tools, uses a MINIMAL instruction
        to avoid confusing small models with complex JSON schemas."""
        if not tools:
            return ""

        # Check if this looks like a coding task (write_file is the main tool)
        tool_names = {t["name"] for t in tools}
        if "write_file" in tool_names:
            # Coding model: just tell it to output code
            return (
                "OUTPUT RULES:\n"
                "- Output ONLY Python code\n"
                "- No explanations, no markdown fences, no tool calls\n"
                "- Code must be complete and syntactically valid\n"
                "- Do NOT write any text before or after the code"
            )

        # For other tools (web_search, etc.) use JSON format
        lines = [
            "── AVAILABLE TOOLS ──",
            "To call a tool, respond with ONLY a JSON object (no other text):",
            '{"tool": "tool_name", "arguments": {"arg1": "value1"}}',
            "",
            "To respond WITHOUT calling a tool, write regular text.",
            "",
            "Tools:",
        ]
        for t in tools:
            params = t.get("parameters", {}).get("properties", {})
            req    = t.get("parameters", {}).get("required", [])
            param_parts = []
            for pname, pdef in params.items():
                ptype = pdef.get("type", "string")
                star  = " *required*" if pname in req else ""
                param_parts.append(f"    - {pname} ({ptype}){star}")
            lines.append(f"\n• {t['name']}: {t.get('description', '')}")
            if param_parts:
                lines.extend(param_parts)
        lines.append("\n── END TOOLS ──")
        return "\n".join(lines)

    def _parse_tool_calls_from_text(self, text: str) -> tuple[str, list[dict]]:
        """Extract tool calls from model text response (prompt-based mode).

        Returns (remaining_text, tool_calls).
        Handles JSON anywhere in the response — beginning, end, or wrapped in markdown.
        """
        import re
        tool_calls = []
        remaining = text

        # Strip markdown code fences
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        # Try to find JSON objects with "tool" key
        # Strategy: try the whole cleaned text first, then search for embedded JSON
        candidates = [cleaned]
        # Also find all {...} blocks
        for match in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text):
            candidates.append(match.group())

        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and "tool" in data:
                    OpenAICompatibleProvider._call_counter += 1
                    tc_id = f"prompt_call_{OpenAICompatibleProvider._call_counter}"
                    args = data.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    tool_calls.append({
                        "id":        tc_id,
                        "name":      data["tool"],
                        "arguments": args,
                    })
                    # Remove the JSON from remaining text
                    remaining = text.replace(candidate, "").strip()
                    break  # one tool call per response
            except (json.JSONDecodeError, TypeError):
                continue

        return remaining, tool_calls

    # ── Tool list formatting ──────────────────────────────────────────────────

    def _tools(self, tools: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["parameters"]}} for t in tools]

    # ── Main complete method ──────────────────────────────────────────────────

    def complete(self, messages, tools, system, on_token=None) -> dict:
        # If we already know the model doesn't support tools, go straight to fallback
        if self._supports_tools is False and tools:
            return self._complete_no_tools(messages, tools, system, on_token)

        kwargs = dict(model=self.model, max_tokens=self.max_tokens,
                      messages=self._msgs(messages, system))
        if tools:
            kwargs["tools"] = self._tools(tools)
            kwargs["tool_choice"] = "auto"

        try:
            return self._do_complete(kwargs, on_token)
        except Exception as e:
            err_str = str(e).lower()
            if "does not support tools" in err_str or ("tool" in err_str and "support" in err_str):
                # Auto-detect: this model can't do native tools
                self._supports_tools = False
                if tools:
                    return self._complete_no_tools(messages, tools, system, on_token)
            raise  # re-raise other errors

    def _do_complete(self, kwargs: dict, on_token) -> dict:
        """Execute completion with or without streaming."""
        if on_token:
            kwargs["stream"] = True
            stream = self.client.chat.completions.create(**kwargs)
            text = ""
            tc_accum: dict[int, dict] = {}
            finish_reason = "stop"
            _stopped_early = False
            for chunk in stream:
                choice = chunk.choices[0]
                delta  = choice.delta
                if delta.content:
                    text += delta.content
                    on_token(delta.content)
                    # Guard: stop on repetition or max length
                    if (len(text) > self._MAX_OUTPUT_CHARS
                            or self._detect_repetition(text)):
                        _stopped_early = True
                        try:
                            stream.close()
                        except Exception:
                            pass
                        break
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        i = tc.index
                        if i not in tc_accum:
                            tc_accum[i] = {"id": tc.id or "", "name": tc.function.name or "", "args": ""}
                        if tc.id:   tc_accum[i]["id"]   = tc.id
                        if tc.function.name: tc_accum[i]["name"] = tc.function.name
                        if tc.function.arguments: tc_accum[i]["args"] += tc.function.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
            tool_calls = []
            for i in sorted(tc_accum):
                tc = tc_accum[i]
                try:    arguments = json.loads(tc["args"]) if tc["args"] else {}
                except: arguments = {}
                tool_calls.append({"id": tc["id"], "name": tc["name"], "arguments": arguments})
            return {"text": text, "tool_calls": tool_calls, "done": finish_reason == "stop"}
        else:
            resp   = self.client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append({"id": tc.id, "name": tc.function.name,
                                       "arguments": json.loads(tc.function.arguments)})
            return {"text": choice.message.content or "",
                    "tool_calls": tool_calls,
                    "done": choice.finish_reason == "stop"}

    def _complete_no_tools(self, messages, tools, system, on_token) -> dict:
        """Prompt-based tool calling for models without native support."""
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=self._msgs_no_tools(messages, system, tools),
        )

        if on_token:
            kwargs["stream"] = True
            stream = self.client.chat.completions.create(**kwargs)
            text = ""
            finish_reason = "stop"
            for chunk in stream:
                choice = chunk.choices[0]
                delta  = choice.delta
                if delta.content:
                    text += delta.content
                    on_token(delta.content)
                    # Guard: stop on repetition or max length
                    if (len(text) > self._MAX_OUTPUT_CHARS
                            or self._detect_repetition(text)):
                        try:
                            stream.close()
                        except Exception:
                            pass
                        break
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        else:
            resp = self.client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            finish_reason = resp.choices[0].finish_reason or "stop"

        # Parse tool calls from text
        remaining, tool_calls = self._parse_tool_calls_from_text(text)
        return {"text": remaining, "tool_calls": tool_calls, "done": finish_reason == "stop"}


# ── Factory ───────────────────────────────────────────────────────────────────

def make_provider(backend: str, model: str | None = None, api_key: str | None = None,
                  base_url: str | None = None, max_tokens: int = 2048,
                  supports_tools: bool | None = None) -> BaseProvider:
    if backend == "anthropic":
        return AnthropicProvider(model=model or "claude-sonnet-4-20250514",
                                 api_key=api_key, max_tokens=max_tokens)
    elif backend == "ollama":
        return OpenAICompatibleProvider(model=model or "llama3.1",
                                        base_url=base_url or "http://localhost:11434/v1",
                                        api_key="ollama", max_tokens=max_tokens,
                                        supports_tools=supports_tools)
    elif backend == "lmstudio":
        return OpenAICompatibleProvider(model=model or "local-model",
                                        base_url=base_url or "http://localhost:1234/v1",
                                        api_key="lm-studio", max_tokens=max_tokens,
                                        supports_tools=supports_tools)
    raise ValueError(f"Unknown backend: {backend!r}")