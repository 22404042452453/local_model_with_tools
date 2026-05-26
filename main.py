"""
main.py — Entry point (run from project root)

Usage:
    python main.py server                          # Web UI at http://127.0.0.1:8000
    python main.py server --port 8001 --backend ollama --model qwen2.5:7b
    python main.py cli "Build a todo REST API"
    python main.py cli --backend ollama --model qwen2.5:14b
"""

import sys
import argparse
from pathlib import Path

# Always run from project root
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def cmd_server(args):
    import uvicorn
    from ui.server import app, init
    from core.config import Config

    cfg = Config.from_env()
    cfg.host      = args.host
    cfg.port      = args.port
    cfg.workspace = Path(args.workspace)
    if args.backend: cfg.backend  = args.backend
    if args.model:   cfg.model    = args.model
    if args.url:     cfg.base_url = args.url
    cfg.stream_tokens = not args.no_stream

    init(cfg)
    print(f"Web UI → http://{cfg.host}:{cfg.port}")
    uvicorn.run(app, host=cfg.host, port=cfg.port)


def cmd_cli(args):
    import asyncio
    from ui.cli import run_terminal
    from core.config import Config

    cfg = Config.from_env()
    cfg.workspace      = Path(args.workspace)
    cfg.max_iterations = args.iters
    cfg.stream_tokens  = not args.no_stream
    if args.backend: cfg.backend  = args.backend
    if args.model:   cfg.model    = args.model
    if args.url:     cfg.base_url = args.url

    from rich.console import Console
    task = args.task or Console().input("[bold]> Task:[/bold] ").strip()
    if task:
        asyncio.run(run_terminal(task, cfg, clean=args.clean))


# ── Shared args ───────────────────────────────────────────────────────────────

def add_common(p):
    p.add_argument("--backend",    default=None, choices=["anthropic", "ollama", "lmstudio"])
    p.add_argument("--model",      default=None)
    p.add_argument("--url",        default=None, dest="url")
    p.add_argument("--workspace",  default="./workspace")
    p.add_argument("--no-stream",  action="store_true")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="main.py")
    sub    = parser.add_subparsers(dest="cmd", required=True)

    # server
    srv = sub.add_parser("server", help="Start Web UI")
    add_common(srv)
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)

    # cli
    cli = sub.add_parser("cli", help="Terminal UI")
    add_common(cli)
    cli.add_argument("task",    nargs="?")
    cli.add_argument("--iters", type=int, default=3)
    cli.add_argument("--clean", action="store_true")

    args = parser.parse_args()

    if args.cmd == "server": cmd_server(args)
    elif args.cmd == "cli":  cmd_cli(args)
