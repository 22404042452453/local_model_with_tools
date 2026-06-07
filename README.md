# Multi-Agent AI Development Pipeline

An autonomous pipeline that turns a natural-language task into working, tested, reviewed code. Multiple AI agents (Architect → Coder → Tester → Reviewer) collaborate inside a gated loop, with automatic fallbacks and optional Docker sandboxing.

---

## Features

- **Multi-backend**: Claude (Anthropic), Ollama (local), or LMStudio — mix and match per agent
- **Three task types**: coding projects, research/documentation, and large multi-module planning
- **Iterative quality loop**: Coder ↔ Tester ↔ Reviewer, up to `max_iterations` times
- **Tool fallback**: models without native tool-calling auto-switch to prompt-based mode
- **Docker sandbox**: run generated code in an isolated container (memory/CPU limits, no network)
- **Plugin system**: drop a `.py` file into `plugins/` to add a new tool to all agents
- **Two UIs**: browser-based (FastAPI + WebSocket) and terminal (Rich)
- **Run history**: every run, event, and generated file stored in SQLite

---

## Quick start

```bash
git clone <repo>
cd local_model_with_tools
pip install -r requirements.txt
cp .env.example .env   # or create .env manually — see Configuration below
```

### Web UI

```bash
python main.py server
# Open http://127.0.0.1:8000
```

### Terminal UI

```bash
python main.py cli "Build a todo REST API in Python"
python main.py cli   # prompts for a task interactively
```

### Docker

```bash
# Anthropic only
docker compose up agent

# With Ollama (local models)
docker compose --profile local up
docker compose exec ollama ollama pull qwen2.5:14b
```

---

## Configuration

Create a `.env` file in the project root. All variables are optional except `ANTHROPIC_API_KEY` when using the Anthropic backend.

### Global LLM defaults

```env
AGENT_BACKEND=anthropic          # anthropic | ollama | lmstudio
AGENT_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-...
AGENT_BASE_URL=                  # base URL for Ollama/LMStudio (e.g. http://localhost:11434/v1)
```

### Per-agent overrides (coding pipeline)

Each agent can use a different backend/model. Unset values fall back to the global defaults above.

```env
ARCHITECT_BACKEND=anthropic
ARCHITECT_MODEL=claude-opus-4-8

CODER_BACKEND=ollama
CODER_MODEL=qwen2.5:14b
CODER_BASE_URL=http://localhost:11434/v1

TESTER_BACKEND=ollama
TESTER_MODEL=qwen2.5:7b

REVIEWER_BACKEND=anthropic
REVIEWER_MODEL=claude-sonnet-4-20250514
```

Per-agent overrides also exist for `RESEARCHER_*`, `WRITER_*`, `EDITOR_*` (research pipeline).  
Each agent also accepts `{PREFIX}_API_KEY`, `{PREFIX}_MAX_TOKENS`, `{PREFIX}_SUPPORTS_TOOLS`.

### Pipeline behaviour

```env
AGENT_MAX_STEPS=25               # max tool calls per agent turn
AGENT_MAX_ITERATIONS=3           # max Coder→Tester→Reviewer loops
AGENT_STREAM_TOKENS=true         # stream tokens in real time
AGENT_STEP_PIPELINE=true         # use orchestrated atomic steps (recommended)
AGENT_PARALLEL_WORKERS=3         # concurrent LLM calls during step implementation
AGENT_WORKSPACE=./workspace      # where generated code is written
AGENT_HOST=127.0.0.1
AGENT_PORT=8000
```

### Docker sandbox

```env
SANDBOX_ENABLED=auto             # auto | true | false
SANDBOX_IMAGE=python:3.12-slim
SANDBOX_MEMORY=512m
SANDBOX_CPUS=1.0
SANDBOX_NETWORK=none             # none = no internet inside container
SANDBOX_TIMEOUT=120
```

### Supervisor (retry & timeouts)

```env
SUPERVISOR_MAX_RETRIES=2
SUPERVISOR_TIMEOUT=300           # seconds before killing a hung agent
SUPERVISOR_MIN_OUTPUT=10         # minimum output chars to pass quality gate
```

---

## Architecture

```
Task input
   │
   ▼
Router ──classifies──► coding / research / planner
   │
   ├─ coding ──► Architect → Coder ⇄ Tester ⇄ Reviewer (loop)
   ├─ research ─► Researcher → Writer → Editor
   └─ planner ──► Planner → N × CodingPipeline (parallel modules)
```

### Agents (coding pipeline)

| Agent | Role |
|---|---|
| Architect | Reads the task, researches best practices, writes `plan.md` |
| Coder | Implements everything in `plan.md`; revises based on review issues |
| Tester | Writes and runs `pytest` tests; reports verdict |
| Reviewer | Reads all code + test report; writes `review.md` with CRITICAL/MAJOR/MINOR findings |

If any agent produces no output, automatic fallbacks generate `plan.md`, basic tests, or `review.md` from static analysis.

### Quality loop

```
Coder ──► Tester ──► Reviewer
  ▲                      │
  └──── FAIL (issues) ───┘   (up to max_iterations)
```

Both Tester and Reviewer must pass before the pipeline exits. On the last iteration the pipeline exits regardless.

### Key modules

| Path | Description |
|---|---|
| `core/config.py` | Config dataclass, env loading, per-agent overrides |
| `core/providers.py` | `AnthropicProvider`, `OpenAICompatibleProvider` (with tool fallback) |
| `core/agent.py` | `BaseAgent` — streaming, tool deduplication, context compression |
| `core/step_agent.py` | `StepAgent` — constrained atomic-step mode for small models |
| `pipeline/pipeline.py` | Main coding pipeline with `asyncio.Event` gates |
| `pipeline/step_pipeline.py` | Orchestrated step-by-step variant |
| `pipeline/router.py` | LLM-based task classifier |
| `pipeline/research_pipeline.py` | Researcher → Writer → Editor |
| `pipeline/planner_pipeline.py` | Multi-module planner |
| `pipeline/supervisor.py` | Retry, timeout, quality gates |
| `tools/executor.py` | Tool implementations (file I/O, shell, web search, memory) |
| `tools/sandbox.py` | Docker isolation for `run_command` |
| `tools/definitions.py` | Tool JSON schemas |
| `plugins/loader.py` | Plugin auto-discovery |
| `storage/history.py` | SQLite run history |
| `ui/server.py` | FastAPI web server + WebSocket streaming |
| `ui/cli.py` | Rich terminal UI |

---

## Plugins

Drop a `.py` file into `plugins/`. Each file must export:

```python
TOOL_DEFINITION = {
    "name": "my_tool",
    "description": "...",
    "parameters": {
        "type": "object",
        "properties": {"arg": {"type": "string"}},
        "required": ["arg"],
    },
}

def execute(args: dict) -> str:
    return "result"
```

Hot-reload without restarting: `POST /api/plugins/reload`.

Bundled plugins: `translate`, `screenshot`, `check_packages`, `check_imports`, `static_analysis`, `create_docx`, `create_pptx`.

---

## REST API (web server)

| Method | Path | Description |
|---|---|---|
| `POST` | `/run` | Start a pipeline run `{"task": "...", "clean": false}` |
| `POST` | `/run/planner` | Start a planner run |
| `GET` | `/status` | `{"running": bool}` |
| `WS` | `/ws` | Real-time event stream |
| `GET` | `/files` | List workspace files |
| `GET` | `/files/{path}` | Read a workspace file |
| `GET` | `/api/runs` | Run history |
| `GET` | `/api/runs/{id}` | Single run detail |
| `GET` | `/api/runs/{id}/events` | Events for a run |
| `GET` | `/api/runs/{id}/files` | Files generated in a run |
| `DELETE` | `/api/runs/{id}` | Delete a run |
| `POST` | `/api/runs/cleanup` | Mark stale 'running' records as crashed |
| `GET` | `/api/stats` | Aggregate stats |
| `GET` | `/api/health` | Agent health |
| `GET` | `/api/plugins` | Loaded plugins |
| `POST` | `/api/plugins/reload` | Hot-reload plugins |

---

## CLI reference

```
python main.py server [--host HOST] [--port PORT] [--backend BACKEND]
                      [--model MODEL] [--url URL] [--workspace DIR]
                      [--no-stream]

python main.py cli [TASK] [--backend BACKEND] [--model MODEL]
                   [--url URL] [--workspace DIR] [--iters N]
                   [--clean] [--no-stream]
```

`--clean` wipes the workspace before the run.  
`--iters` sets the maximum number of Coder→Tester→Reviewer loops (default 3).

---

## Requirements

- Python 3.12+
- Docker (optional, for sandbox)
- Ollama or LMStudio (optional, for local models)

```
anthropic>=0.50.0
openai>=1.60.0
ddgs>=2.0.0
rich>=13.7.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
websockets>=13.0
python-dotenv>=1.0.0
```

Optional formatters (auto-applied after each file write if installed):

```bash
pip install black   # or ruff
```
