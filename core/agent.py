"""core/agent.py — BaseAgent with streaming, compression, and dedup"""

import asyncio
import json
import re
import threading
from typing import Awaitable, Callable

from core.events import AgentName, Event
from core.providers import BaseProvider
from core.compressor import ContextCompressor

EventCallback = Callable[[Event], Awaitable[None]]


class BaseAgent:
    def __init__(self, name: AgentName, provider: BaseProvider,
                 tools: list[dict], executor, system: str,
                 max_steps: int = 25, stream_tokens: bool = True,
                 compressor: ContextCompressor | None = None):
        self.name          = name
        self.provider      = provider
        self.tools         = tools
        self.executor      = executor
        self.system        = system
        self.max_steps     = max_steps
        self.stream_tokens = stream_tokens
        self.compressor    = compressor or ContextCompressor()

    async def run(self, task: str, emit: EventCallback) -> tuple[str | None, str]:
        await emit(Event.start(self.name, task))

        messages: list[dict] = [{"role": "user", "content": task}]
        memory:   dict       = {}
        tool_cache: dict[str, str] = {}   # cache: "tool_name|args_json" -> result
        call_counts: dict[str, int] = {}  # count repeated calls

        for step in range(1, self.max_steps + 1):
            compressed = self.compressor.compress_messages(messages)
            resp = await self._call_provider(compressed, emit)

            if resp is None:
                await emit(Event.error(self.name, "Provider call failed."))
                return None, "FAIL"

            text = self._strip_thinking(resp["text"])

            if text:
                await emit(Event.thought(self.name, text))

            messages.append({"role": "assistant", "content": text,
                              "tool_calls": resp["tool_calls"]})

            if not resp["tool_calls"]:
                await emit(Event.done(self.name, text))
                return text, "PASS"

            tool_results   = []
            final_summary  = None
            final_verdict  = "PASS"

            for tc in resp["tool_calls"]:
                name, args = tc["name"], tc["arguments"]

                # ── Dedup: detect repeated identical calls ────────────────────
                cache_key = f"{name}|{json.dumps(args, sort_keys=True)}"
                call_counts[cache_key] = call_counts.get(cache_key, 0) + 1

                if call_counts[cache_key] > 2 and name in ("read_file", "list_files", "get_env_info"):
                    # Already called 2+ times with same args — return cached + warning
                    cached = tool_cache.get(cache_key, "(no cached result)")
                    warning = f"[DUPLICATE CALL #{call_counts[cache_key]}] You already called {name} with these args. Here is the cached result. Do NOT call this again — proceed with your task.\n\n{cached[:300]}"
                    await emit(Event.tool_call(self.name, name, {"DUPLICATE": call_counts[cache_key]}))
                    await emit(Event.tool_result(self.name, name, "[cached — duplicate call]"))
                    tool_results.append({"id": tc["id"], "content": warning})
                    continue

                await emit(Event.tool_call(self.name, name, args))
                result, is_done = self.executor(name, args, memory)

                # Cache the result
                tool_cache[cache_key] = result

                compressed_result = self.compressor.compress_tool_result(name, result)
                display = compressed_result[:800] + ("..." if len(compressed_result) > 800 else "")
                await emit(Event.tool_result(self.name, name, display))

                if is_done:
                    try:
                        payload       = json.loads(result)
                        final_summary = payload.get("summary", result)
                        final_verdict = payload.get("verdict", "PASS")
                    except Exception:
                        final_summary = result
                        final_verdict = "PASS"
                    tool_results.append({"id": tc["id"], "content": "Task complete."})
                else:
                    tool_results.append({"id": tc["id"], "content": compressed_result})

            messages.append({"role": "tool", "results": tool_results})

            if final_summary is not None:
                await emit(Event.done(self.name, final_summary, final_verdict))
                return final_summary, final_verdict

        await emit(Event.error(self.name, f"Reached max_steps ({self.max_steps})."))
        return None, "FAIL"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _strip_thinking(self, text: str | None) -> str:
        if not text:
            return ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if text.startswith("Thinking..."):
            text = text[len("Thinking..."):].strip()
        return text

    async def _call_provider(self, messages: list[dict], emit: EventCallback) -> dict | None:
        if not self.stream_tokens:
            try:
                return await asyncio.to_thread(
                    self.provider.complete, messages, self.tools, self.system, None)
            except Exception as e:
                await emit(Event.error(self.name, str(e)))
                return None

        loop        = asyncio.get_event_loop()
        token_queue: asyncio.Queue = asyncio.Queue()

        def on_token(chunk: str):
            loop.call_soon_threadsafe(token_queue.put_nowait, ("token", chunk))

        def run_in_thread():
            try:
                result = self.provider.complete(messages, self.tools, self.system, on_token)
                loop.call_soon_threadsafe(token_queue.put_nowait, ("done", result))
            except Exception as e:
                loop.call_soon_threadsafe(token_queue.put_nowait, ("error", str(e)))

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

        while True:
            msg_type, payload = await token_queue.get()
            if msg_type == "token":
                await emit(Event.token(self.name, payload))
            elif msg_type == "done":
                return payload
            elif msg_type == "error":
                await emit(Event.error(self.name, payload))
                return None
