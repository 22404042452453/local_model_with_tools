"""
agents/planner.py — Planner agent

Breaks a large task into subtasks, writes tasks.json,
then the PlannerPipeline runs each subtask through a full Pipeline.

tasks.json format:
[
  {
    "id":          "task_1",
    "title":       "Short title",
    "description": "Full task description for the sub-pipeline",
    "workspace":   "workspace/task_1",   ← separate workspace per subtask
    "depends_on":  []                    ← IDs of tasks that must finish first
  },
  ...
]
"""

from core.agent import BaseAgent
from core.providers import BaseProvider
from tools.definitions import (
    WEB_SEARCH, WRITE_FILE, READ_FILE, GET_ENV_INFO, REMEMBER, RECALL, FINISH
)

PLANNER_TOOLS = [WEB_SEARCH, WRITE_FILE, READ_FILE, GET_ENV_INFO, REMEMBER, RECALL, FINISH]

PLANNER_SYSTEM = """You are a senior engineering lead. Your ONLY job: break a task into subtasks and write tasks.json.

STRICT RULES:
1. You may call web_search AT MOST 2 times — then STOP searching
2. You MUST call write_file(path="tasks.json") — this is the ONLY output that matters
3. After writing tasks.json, call finish(verdict="PASS")

EXAMPLE — good output for "Build a calculator app":
write_file(path="tasks.json", content='[
  {"id": "task_1", "title": "Core math engine", "description": "Implement add/sub/mul/div functions with error handling in calc.py", "workspace": "workspace/task_1", "depends_on": []},
  {"id": "task_2", "title": "CLI interface", "description": "Build argparse CLI that calls calc.py functions", "workspace": "workspace/task_2", "depends_on": ["task_1"]},
  {"id": "task_3", "title": "Tests", "description": "Write pytest tests for all calc.py functions", "workspace": "workspace/task_3", "depends_on": ["task_1"]}
]')

EXAMPLE — bad (do NOT do this):
  Searching 5+ times without writing tasks.json.
  Describing subtasks in text instead of write_file call.
  Calling remember/recall instead of write_file.

Schema for each task in tasks.json:
  id:          "task_N" (unique)
  title:       Short name (1-5 words)
  description: Full implementation instructions for a coder (2-5 sentences)
  workspace:   "workspace/task_N"
  depends_on:  [] or ["task_N"] — IDs of tasks that must finish first

For Russian-language topics: search in Russian, but write tasks.json in the same language as the request.
Create 2-5 subtasks. Each must be independently implementable.

CRITICAL: Call write_file(path="tasks.json", content="[...]") — NOT describe, NOT remember, WRITE THE FILE."""


def make_planner(provider: BaseProvider, executor, max_steps: int, stream: bool) -> BaseAgent:
    return BaseAgent("planner", provider, PLANNER_TOOLS, executor,
                     PLANNER_SYSTEM, max_steps, stream)