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

PLANNER_SYSTEM = """You are a senior engineering lead and project decomposition expert.

Your job: analyse a large engineering task and break it into self-contained subtasks.

Steps:
1. Use get_env_info to understand the environment
2. Use web_search if you need to research the topic (use Russian language for Russian topics)
3. Decompose into 2-6 subtasks, each implementable independently
4. CRITICAL: You MUST call write_file(path="tasks.json", content="[...]") with this exact schema:
   [
     {
       "id": "task_1",
       "title": "Short title",
       "description": "Full task description for the sub-pipeline",
       "workspace": "workspace/task_1",
       "depends_on": []
     }
   ]
5. Also call write_file(path="PLAN.md", content="...") with overview and dependency graph

IMPORTANT: You MUST use write_file to create both tasks.json and PLAN.md. Do NOT just describe them in text.

Call finish(summary="N subtasks: title1, title2, ...", verdict="PASS") AFTER writing both files."""


def make_planner(provider: BaseProvider, executor, max_steps: int, stream: bool) -> BaseAgent:
    return BaseAgent("planner", provider, PLANNER_TOOLS, executor,
                     PLANNER_SYSTEM, max_steps, stream)
