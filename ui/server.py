"""ui/server.py — FastAPI web server with WebSocket event streaming"""

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import asyncio
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import Config
from pipeline.pipeline import Pipeline

app   = FastAPI(title="Multi-Agent Pipeline v2")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_config:   Config   | None = None
_running:  bool     = False
_clients:  set[WebSocket] = set()


def init(config: Config) -> None:
    global _config
    _config = config

    # Check Ollama model availability if using ollama backend
    if config.backend == "ollama":
        from core.config import check_ollama_model
        base_url = config.base_url or "http://localhost:11434"
        ok, err = check_ollama_model(config.model, base_url)
        if not ok:
            print(f"\n⚠️  WARNING: {err}")
            print(f"   Update AGENT_MODEL in .env or pull the model: ollama pull {config.model}\n")

    init_extensions(config)


# ── Broadcast helpers ─────────────────────────────────────────────────────────

async def _broadcast(data: dict) -> None:
    dead = set()
    msg  = json.dumps(data)
    for ws in _clients:
        try:    await ws.send_text(msg)
        except: dead.add(ws)
    _clients.difference_update(dead)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")

@app.get("/status")
async def status():
    return {"running": _running}

@app.post("/run")
async def run_pipeline(body: dict):
    global _running
    if _running:
        return JSONResponse({"error": "Already running"}, status_code=409)

    task  = body.get("task", "").strip()
    clean = body.get("clean", False)
    if not task:
        return JSONResponse({"error": "task required"}, status_code=400)

    async def _run():
        global _running
        _running = True
        from pipeline.router import RouterPipeline
        pipeline = RouterPipeline(_config)
        queue    = pipeline.subscribe()

        async def forward():
            while True:
                ev = await queue.get()
                await _broadcast(ev.to_dict())
                if ev.type in ("pipeline_done", "error") and ev.agent == "pipeline":
                    break

        await asyncio.gather(
            asyncio.create_task(pipeline.run(task, clean_workspace=clean)),
            asyncio.create_task(forward()),
        )
        _running = False

    asyncio.create_task(_run())
    return {"started": True}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        _clients.discard(ws)

@app.get("/files")
async def list_files():
    ws = _config.workspace
    if not ws.exists(): return {"files": []}
    return {"files": [
        {"path": str(f.relative_to(ws)), "bytes": f.stat().st_size}
        for f in sorted(ws.rglob("*")) if f.is_file()
    ]}

@app.get("/files/{file_path:path}")
async def get_file(file_path: str):
    target = (_config.workspace / file_path).resolve()
    if not str(target).startswith(str(_config.workspace.resolve())):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    if not target.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"path": file_path, "content": target.read_text(encoding="utf-8")}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend",   default="anthropic")
    parser.add_argument("--model",     default=None)
    parser.add_argument("--url",       default=None)
    parser.add_argument("--host",      default="127.0.0.1")
    parser.add_argument("--port",      type=int, default=8000)
    parser.add_argument("--workspace", default="./workspace")
    parser.add_argument("--no-stream", action="store_true")
    args = parser.parse_args()

    cfg = Config.from_env()
    cfg.backend       = args.backend
    cfg.host          = args.host
    cfg.port          = args.port
    cfg.workspace     = Path(args.workspace)
    cfg.stream_tokens = not args.no_stream
    if args.model: cfg.model    = args.model
    if args.url:   cfg.base_url = args.url

    init(cfg)
    print(f"http://{cfg.host}:{cfg.port}")
    uvicorn.run(app, host=cfg.host, port=cfg.port)


# ── Planner endpoint ──────────────────────────────────────────────────────────

@app.post("/run/planner")
async def run_planner(body: dict):
    from pipeline.planner_pipeline import PlannerPipeline
    global _running
    if _running:
        return JSONResponse({"error": "Already running"}, status_code=409)

    task  = body.get("task", "").strip()
    if not task:
        return JSONResponse({"error": "task required"}, status_code=400)

    async def _run():
        global _running
        _running  = True
        pipeline  = PlannerPipeline(_config)
        queue     = pipeline.subscribe()

        async def forward():
            while True:
                ev = await queue.get()
                await _broadcast(ev.to_dict())
                if ev.type in ("pipeline_done", "error") and ev.agent == "pipeline":
                    break

        await asyncio.gather(
            asyncio.create_task(pipeline.run(task)),
            asyncio.create_task(forward()),
        )
        _running = False

    asyncio.create_task(_run())
    return {"started": True, "mode": "planner"}


# ── History API ───────────────────────────────────────────────────────────────

_history = None

def _get_history():
    global _history
    if _history is None:
        from storage.history import History
        _history = History(str(Path(_config.workspace.parent / "runs.db")))
    return _history


@app.get("/api/runs")
async def api_list_runs(limit: int = 50, offset: int = 0, status: str = None):
    return {"runs": _get_history().list_runs(limit, offset, status)}


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: int):
    run = _get_history().get_run(run_id)
    if not run:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"run": run}


@app.get("/api/runs/{run_id}/events")
async def api_get_events(run_id: int, event_type: str = None):
    events = _get_history().get_events(run_id, event_type)
    return {"events": events, "count": len(events)}


@app.get("/api/runs/{run_id}/files")
async def api_get_run_files(run_id: int):
    files = _get_history().get_files(run_id)
    return {"files": files}


@app.get("/api/runs/{run_id}/files/{file_id}")
async def api_get_file_content(run_id: int, file_id: int):
    content = _get_history().get_file_content(file_id)
    if content is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"content": content}


@app.delete("/api/runs/{run_id}")
async def api_delete_run(run_id: int):
    _get_history().delete_run(run_id)
    return {"deleted": True}


@app.get("/api/stats")
async def api_stats():
    return _get_history().get_stats()


@app.get("/api/health")
async def api_health():
    """Agent health from supervisor."""
    if _supervisor:
        return {"agents": _supervisor.get_health()}
    return {"agents": []}


@app.get("/api/plugins")
async def api_plugins():
    """List loaded plugins."""
    if _plugin_registry:
        return {"plugins": [
            {"name": p.name, "agents": p.agents or "all", "source": str(p.source)}
            for p in _plugin_registry.get_plugins()
        ]}
    return {"plugins": []}


@app.post("/api/plugins/reload")
async def api_reload_plugins():
    """Hot-reload plugins."""
    if _plugin_registry:
        loaded = _plugin_registry.reload()
        return {"reloaded": len(loaded), "plugins": [p.name for p in loaded]}
    return {"reloaded": 0}


_supervisor = None
_plugin_registry = None


def init_extensions(config):
    """Initialize supervisor, plugins, history after config is set."""
    global _supervisor, _plugin_registry

    from pipeline.supervisor import Supervisor, SupervisorConfig
    _supervisor = Supervisor(SupervisorConfig())

    from plugins.loader import get_registry
    _plugin_registry = get_registry(Path(__file__).parent.parent / "plugins")

    _get_history()  # init db
