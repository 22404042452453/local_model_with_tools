"""
core/compressor.py — Context compression for small models

Problems with small models (4B-8B):
  - Context window fills fast with tool results (pip list = 2000 tokens)
  - Long history = model forgets the task or starts "being lazy"
  - File contents eat context quickly

Solutions:
  1. Truncate long tool results (keep first/last N chars)
  2. Summarize old messages (compress history mid-conversation)
  3. Strip redundant content (duplicate tool calls, empty thoughts)

Usage:
    compressor = ContextCompressor(max_result_chars=500, max_history_msgs=12)
    messages = compressor.compress(messages)
"""

import json
from dataclasses import dataclass


@dataclass
class CompressorConfig:
    max_result_chars:  int  = 800    # truncate tool results beyond this
    max_file_chars:    int  = 1500   # truncate file contents
    max_history_msgs:  int  = 16     # keep last N messages, summarize older
    max_env_lines:     int  = 30     # truncate pip list output
    strip_thinking:    bool = True   # remove <think>...</think> blocks from model output
    compress_repeated: bool = True   # collapse repeated tool calls (e.g. multiple list_files)


class ContextCompressor:
    def __init__(self, config: CompressorConfig | None = None):
        self.config = config or CompressorConfig()

    # ── Main entry: compress message history ──────────────────────────────────

    def compress_messages(self, messages: list[dict]) -> list[dict]:
        """
        Compress message history to fit in small model context.
        Called before sending messages to the provider.
        """
        cfg = self.config
        result = []

        for msg in messages:
            msg = self._compress_message(msg)
            result.append(msg)

        # If too many messages, summarize older ones
        if len(result) > cfg.max_history_msgs:
            keep_first = 2   # keep original task + first response
            keep_last  = cfg.max_history_msgs - keep_first - 1
            
            old_msgs = result[keep_first:-keep_last]
            summary  = self._summarize_old(old_msgs)

            result = (
                result[:keep_first]
                + [{"role": "user", "content": f"[Previous conversation summary: {summary}]"}]
                + result[-keep_last:]
            )

        return result

    # ── Compress a single tool result ─────────────────────────────────────────

    def compress_tool_result(self, tool_name: str, result: str) -> str:
        """Compress a tool result before storing in history."""
        cfg = self.config

        # pip list / env info — keep only first N lines
        if tool_name == "get_env_info" and len(result) > 500:
            lines = result.splitlines()
            # Keep Python version + first N package lines
            header = lines[:3]
            pkg_lines = [l for l in lines[3:] if l.strip()]
            if len(pkg_lines) > cfg.max_env_lines:
                kept = pkg_lines[:cfg.max_env_lines]
                result = "\n".join(header + kept + [f"... ({len(pkg_lines) - cfg.max_env_lines} more packages)"])
            return result

        # File contents — truncate middle
        if tool_name == "read_file" and len(result) > cfg.max_file_chars:
            half = cfg.max_file_chars // 2
            return result[:half] + f"\n\n... ({len(result) - cfg.max_file_chars} chars truncated) ...\n\n" + result[-half:]

        # list_files — keep as is (usually small)
        if tool_name == "list_files":
            return result

        # web_search — keep first 3 results, truncate body
        if tool_name == "web_search":
            blocks = result.split("\n\n")
            kept = blocks[:3]
            trimmed = []
            for block in kept:
                if len(block) > 300:
                    block = block[:300] + "..."
                trimmed.append(block)
            if len(blocks) > 3:
                trimmed.append(f"... ({len(blocks) - 3} more results)")
            return "\n\n".join(trimmed)

        # Generic truncation
        if len(result) > cfg.max_result_chars:
            half = cfg.max_result_chars // 2
            return result[:half] + f"\n... ({len(result)} chars total, truncated) ...\n" + result[-half:]

        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compress_message(self, msg: dict) -> dict:
        """Compress a single message."""
        cfg = self.config
        msg = dict(msg)  # shallow copy

        # Strip <think> blocks from assistant content
        if cfg.strip_thinking and msg.get("role") == "assistant" and msg.get("content"):
            content = msg["content"]
            # Remove <think>...</think> blocks
            import re
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            # Also remove "Thinking..." prefix that some models add
            if content.startswith("Thinking..."):
                content = content[len("Thinking..."):].strip()
            msg["content"] = content

        # Compress tool results in tool messages
        if msg.get("role") == "tool" and msg.get("results"):
            compressed_results = []
            for r in msg["results"]:
                r = dict(r)
                if len(r.get("content", "")) > cfg.max_result_chars:
                    r["content"] = self.compress_tool_result("unknown", r["content"])
                compressed_results.append(r)
            msg["results"] = compressed_results

        return msg

    def _summarize_old(self, messages: list[dict]) -> str:
        """Create a brief summary of old messages."""
        actions = []
        for msg in messages:
            if msg.get("role") == "assistant":
                # Extract tool call names
                for tc in msg.get("tool_calls", []):
                    actions.append(tc["name"])
                if msg.get("content"):
                    # First 50 chars of thought
                    thought = msg["content"][:50].replace("\n", " ")
                    actions.append(f"thought: {thought}")
            elif msg.get("role") == "tool":
                for r in msg.get("results", []):
                    content = r.get("content", "")
                    if "Written" in content:
                        actions.append(content[:60])

        summary = "; ".join(actions[-10:])  # last 10 actions
        return summary[:500]
