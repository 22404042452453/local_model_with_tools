"""core/config.py — project settings, loaded from .env

Per-agent overrides: set ARCHITECT_MODEL, CODER_BACKEND, etc.
Unset values fall back to the global AGENT_* defaults.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ── Per-agent provider override ───────────────────────────────────────────────

@dataclass
class AgentProviderConfig:
    """
    Provider settings for a single agent.
    None = inherit from global Config.
    """
    backend:    str | None = None
    model:      str | None = None
    api_key:    str | None = None
    base_url:   str | None = None
    max_tokens: int | None = None

    def resolve(self, global_cfg: "Config") -> dict:
        """Return final kwargs for make_provider(), merging with global defaults."""
        return {
            "backend":    self.backend    or global_cfg.backend,
            "model":      self.model      or global_cfg.model,
            "api_key":    self.api_key    or global_cfg.api_key,
            "base_url":   self.base_url   or global_cfg.base_url,
            "max_tokens": self.max_tokens or global_cfg.max_tokens,
        }

    @classmethod
    def from_env(cls, prefix: str) -> "AgentProviderConfig":
        """Load from env vars like ARCHITECT_BACKEND, ARCHITECT_MODEL, etc."""
        p = prefix.upper()
        return cls(
            backend    = os.getenv(f"{p}_BACKEND"),
            model      = os.getenv(f"{p}_MODEL"),
            api_key    = os.getenv(f"{p}_API_KEY"),
            base_url   = os.getenv(f"{p}_BASE_URL"),
            max_tokens = int(os.getenv(f"{p}_MAX_TOKENS", "0")) or None,
        )


# ── Main config ───────────────────────────────────────────────────────────────

@dataclass
class Config:
    # ── Global LLM defaults (used when agent has no override) ─────────────────
    backend:    str      = "anthropic"
    model:      str      = "claude-sonnet-4-20250514"
    api_key:    str|None = None
    base_url:   str|None = None
    max_tokens: int      = 2048

    # ── Per-agent provider overrides ──────────────────────────────────────────
    architect_cfg: AgentProviderConfig = field(default_factory=AgentProviderConfig)
    coder_cfg:     AgentProviderConfig = field(default_factory=AgentProviderConfig)
    tester_cfg:    AgentProviderConfig = field(default_factory=AgentProviderConfig)
    reviewer_cfg:  AgentProviderConfig = field(default_factory=AgentProviderConfig)

    # ── Pipeline behaviour ────────────────────────────────────────────────────
    max_steps:          int  = 25
    max_iterations:     int  = 3
    stream_tokens:      bool = True
    use_step_pipeline:  bool = True   # use StepPipeline (atomic steps) for coding tasks

    # ── Workspace ─────────────────────────────────────────────────────────────
    workspace: Path = field(default_factory=lambda: Path("./workspace"))

    # ── Web server ────────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8000

    def __post_init__(self):
        self.workspace = Path(self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    def provider_kwargs(self, agent: str) -> dict:
        """Return resolved provider kwargs for a named agent."""
        cfg_map = {
            "architect": self.architect_cfg,
            "coder":     self.coder_cfg,
            "tester":    self.tester_cfg,
            "reviewer":  self.reviewer_cfg,
        }
        return cfg_map[agent].resolve(self)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            backend        = os.getenv("AGENT_BACKEND",    "anthropic"),
            model          = os.getenv("AGENT_MODEL",      "claude-sonnet-4-20250514"),
            api_key        = os.getenv("ANTHROPIC_API_KEY"),
            base_url       = os.getenv("AGENT_BASE_URL"),
            max_steps          = int(os.getenv("AGENT_MAX_STEPS",      "25")),
            max_iterations     = int(os.getenv("AGENT_MAX_ITERATIONS", "3")),
            stream_tokens      = os.getenv("AGENT_STREAM_TOKENS", "true").lower() == "true",
            use_step_pipeline  = os.getenv("AGENT_STEP_PIPELINE", "true").lower() == "true",
            workspace      = Path(os.getenv("AGENT_WORKSPACE", "./workspace")),
            host           = os.getenv("AGENT_HOST", "127.0.0.1"),
            port           = int(os.getenv("AGENT_PORT", "8000")),
            # Per-agent
            architect_cfg  = AgentProviderConfig.from_env("architect"),
            coder_cfg      = AgentProviderConfig.from_env("coder"),
            tester_cfg     = AgentProviderConfig.from_env("tester"),
            reviewer_cfg   = AgentProviderConfig.from_env("reviewer"),
        )


def check_ollama_model(model: str, base_url: str = "http://localhost:11434") -> tuple[bool, str]:
    """Check if Ollama model exists. Returns (ok, error_message)."""
    try:
        import urllib.request, json
        # Strip /v1 suffix if present (Ollama native API is on root)
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        url = f"{base}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        if model in models:
            return True, ""
        base_name = model.split(":")[0]
        matches = [m for m in models if m.startswith(base_name)]
        if matches:
            return False, f"Model '{model}' not found. Did you mean: {', '.join(matches[:3])}?"
        return False, f"Model '{model}' not found. Available: {', '.join(models[:5])}"
    except Exception as e:
        return False, f"Cannot connect to Ollama: {e}"
