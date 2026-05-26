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

    def __init__(self, model: str = "llama3.1",
                 base_url: str = "http://localhost:11434/v1",
                 api_key: str = "ollama", max_tokens: int = 2048):
        from openai import OpenAI
        self.client     = OpenAI(base_url=base_url, api_key=api_key)
        self.model      = model
        self.max_tokens = max_tokens

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

    def _tools(self, tools: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["parameters"]}} for t in tools]

    def complete(self, messages, tools, system, on_token=None) -> dict:
        kwargs = dict(model=self.model, max_tokens=self.max_tokens,
                      messages=self._msgs(messages, system),
                      tools=self._tools(tools), tool_choice="auto")

        if on_token:
            # Streaming mode — accumulate tool call chunks
            kwargs["stream"] = True
            stream = self.client.chat.completions.create(**kwargs)
            text = ""
            tc_accum: dict[int, dict] = {}
            finish_reason = "stop"
            for chunk in stream:
                choice = chunk.choices[0]
                delta  = choice.delta
                if delta.content:
                    text += delta.content
                    on_token(delta.content)
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


# ── Factory ───────────────────────────────────────────────────────────────────

def make_provider(backend: str, model: str | None = None, api_key: str | None = None,
                  base_url: str | None = None, max_tokens: int = 2048) -> BaseProvider:
    if backend == "anthropic":
        return AnthropicProvider(model=model or "claude-sonnet-4-20250514",
                                 api_key=api_key, max_tokens=max_tokens)
    elif backend == "ollama":
        return OpenAICompatibleProvider(model=model or "llama3.1",
                                        base_url=base_url or "http://localhost:11434/v1",
                                        api_key="ollama", max_tokens=max_tokens)
    elif backend == "lmstudio":
        return OpenAICompatibleProvider(model=model or "local-model",
                                        base_url=base_url or "http://localhost:1234/v1",
                                        api_key="lm-studio", max_tokens=max_tokens)
    raise ValueError(f"Unknown backend: {backend!r}")
