"""
plugins/loader.py — Plugin system

Drop a .py file into plugins/ and agents automatically get new tools.

Each plugin must define:
    TOOL_DEFINITION = {
        "name":        "my_tool",
        "description": "What it does",
        "parameters":  { "type": "object", "properties": {...}, "required": [...] }
    }
    
    def execute(args: dict) -> str:
        '''Runs the tool. Returns result string.'''
        return "result"

Optional:
    AGENTS = ["coder", "tester"]   # which agents get this tool (default: all)

Example:
    plugins/
    ├── loader.py          ← this file
    ├── examples/
    │   ├── translate.py   ← example plugin
    │   └── screenshot.py  ← example plugin
    └── my_custom_tool.py  ← your plugin (auto-discovered)
"""

import importlib.util
import sys
from pathlib import Path
from typing import Callable


PLUGINS_DIR = Path(__file__).parent


class Plugin:
    """Loaded plugin instance."""
    def __init__(self, name: str, definition: dict, execute_fn: Callable,
                 agents: list[str] | None = None, source: Path | None = None):
        self.name       = name
        self.definition = definition
        self.execute     = execute_fn
        self.agents     = agents      # None = all agents
        self.source     = source

    def __repr__(self):
        return f"Plugin({self.name}, agents={self.agents or 'all'})"


class PluginRegistry:
    """
    Discovers and loads plugins from the plugins/ directory.
    
    Usage:
        registry = PluginRegistry()
        registry.load_all()
        
        # Get tools for a specific agent
        tools = registry.get_tools("coder")
        
        # Execute a plugin tool
        result = registry.execute("my_tool", {"arg": "value"})
    """

    def __init__(self, plugins_dir: Path | None = None):
        self.plugins_dir = plugins_dir or PLUGINS_DIR
        self._plugins: dict[str, Plugin] = {}

    def load_all(self) -> list[Plugin]:
        """Scan plugins/ directory and load all valid plugins."""
        self._plugins.clear()
        loaded = []

        if not self.plugins_dir.exists():
            return loaded

        for py_file in sorted(self.plugins_dir.glob("*.py")):
            # Skip loader.py and __init__.py
            if py_file.name in ("loader.py", "__init__.py"):
                continue

            plugin = self._load_file(py_file)
            if plugin:
                self._plugins[plugin.name] = plugin
                loaded.append(plugin)

        return loaded

    def _load_file(self, path: Path) -> Plugin | None:
        """Load a single plugin file."""
        try:
            module_name = f"plugin_{path.stem}"
            spec   = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)

            # Don't pollute sys.modules permanently
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Validate required attributes
            if not hasattr(module, "TOOL_DEFINITION"):
                print(f"  ⚠ Plugin {path.name}: missing TOOL_DEFINITION, skipping")
                return None
            if not hasattr(module, "execute"):
                print(f"  ⚠ Plugin {path.name}: missing execute(), skipping")
                return None

            definition = module.TOOL_DEFINITION
            execute_fn = module.execute
            agents     = getattr(module, "AGENTS", None)

            plugin = Plugin(
                name       = definition["name"],
                definition = definition,
                execute_fn = execute_fn,
                agents     = agents,
                source     = path,
            )

            print(f"  ✓ Plugin loaded: {plugin.name} ({path.name})")
            return plugin

        except Exception as e:
            print(f"  ✗ Plugin {path.name} failed: {e}")
            return None

        finally:
            # Clean up
            if f"plugin_{path.stem}" in sys.modules:
                del sys.modules[f"plugin_{path.stem}"]

    def reload(self) -> list[Plugin]:
        """Reload all plugins (hot-reload)."""
        return self.load_all()

    def get_plugins(self, agent_name: str | None = None) -> list[Plugin]:
        """Get plugins available for a specific agent."""
        if agent_name is None:
            return list(self._plugins.values())
        return [
            p for p in self._plugins.values()
            if p.agents is None or agent_name in p.agents
        ]

    def get_tools(self, agent_name: str | None = None) -> list[dict]:
        """Get tool definitions for a specific agent."""
        return [p.definition for p in self.get_plugins(agent_name)]

    def execute(self, tool_name: str, args: dict) -> str:
        """Execute a plugin tool by name."""
        plugin = self._plugins.get(tool_name)
        if not plugin:
            return f"Plugin not found: {tool_name}"
        try:
            return str(plugin.execute(args))
        except Exception as e:
            return f"Plugin error ({tool_name}): {e}"

    def has(self, tool_name: str) -> bool:
        return tool_name in self._plugins

    @property
    def names(self) -> list[str]:
        return list(self._plugins.keys())


# ── Global registry singleton ─────────────────────────────────────────────────

_registry: PluginRegistry | None = None


def get_registry(plugins_dir: Path | None = None) -> PluginRegistry:
    """Get or create the global plugin registry."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry(plugins_dir)
        _registry.load_all()
    return _registry
