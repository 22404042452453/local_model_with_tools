"""tools/definitions.py — tool schemas (provider-agnostic)

Tool descriptions are written with ASSERTIVE CUES (research: Tool Preferences in
Agentic LLMs, 2025) — imperative mood, explicit use-cases, anti-patterns.
This measurably improves correct tool selection in small models (Qwen2.5-7B +20–30%).
"""


def _def(name, description, properties, required) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


# ── Individual tools ──────────────────────────────────────────────────────────

WEB_SEARCH = _def(
    "web_search",
    "Search the web for libraries, docs, or best practices. "
    "Use when you are unsure which package to import or need current API docs. "
    "Query must be specific and technical (e.g. 'python tkinter canvas animation').",
    {"query": {"type": "string", "description": "Short technical search query in English or Russian"}},
    ["query"],
)

CALCULATE = _def(
    "calculate",
    "Evaluate a Python math expression. The math module is available.",
    {"expression": {"type": "string", "description": "e.g. 'math.sqrt(144)' or '365*24*3600'"}},
    ["expression"],
)

READ_FILE = _def(
    "read_file",
    "Read a file's full content from the workspace. "
    "ALWAYS call this before editing a file. "
    "Call ONCE per file — remember the content, do NOT read the same file twice.",
    {"path": {"type": "string",
              "description": "Relative path — e.g. 'main.py' or 'tests/test_main.py'"}},
    ["path"],
)

WRITE_FILE = _def(
    "write_file",
    "Save code or text to a file. "
    "ALWAYS call this to persist any code — NEVER describe code in your text response. "
    "content must be COMPLETE and working — no '...', no 'pass', no TODOs. "
    "path must be RELATIVE (e.g. 'main.py', NOT '/workspace/main.py').",
    {"path":    {"type": "string",
                 "description": "Relative path, e.g. 'main.py' or 'tests/test_main.py'"},
     "content": {"type": "string",
                 "description": "Complete file content — every line, no placeholders"}},
    ["path", "content"],
)

LIST_FILES = _def(
    "list_files",
    "List all files in the workspace. "
    "Call ONCE at the start to discover what exists. "
    "Do NOT call repeatedly — remember the output and use read_file for contents.",
    {},
    [],
)

EDIT_FILE = _def(
    "edit_file",
    "Fix a specific bug by replacing an exact string in a file. "
    "PREFER this over write_file when fixing errors — preserves working code unchanged. "
    "find must be the EXACT string currently in the file (copy-paste it). "
    "Use for: fixing imports, correcting a function body, removing a bad line.",
    {"path":    {"type": "string",
                 "description": "Relative path of the file to edit, e.g. 'main.py'"},
     "find":    {"type": "string",
                 "description": "Exact string to find — must match character-for-character"},
     "replace": {"type": "string",
                 "description": "Replacement string (can be empty to delete the found text)"}},
    ["path", "find", "replace"],
)

DELETE_FILE = _def(
    "delete_file",
    "Delete a file from the workspace. Use only when a file must be removed entirely.",
    {"path": {"type": "string", "description": "Relative path, e.g. 'broken.py'"}},
    ["path"],
)

RUN_COMMAND = _def(
    "run_command",
    "Run a shell command in the workspace directory. "
    "Use to: run tests ('python -m pytest tests/ -v'), check syntax "
    "('python -m py_compile main.py'), or verify imports ('python -c \"import main\"'). "
    "Always capture and read the output.",
    {"command": {"type": "string",
                 "description": "Shell command, e.g. 'python -m pytest tests/ -v --tb=short'"},
     "timeout": {"type": "integer",
                 "description": "Max seconds to wait (default 60). Use 120 for slow tests."}},
    ["command"],
)

GET_ENV_INFO = _def(
    "get_env_info",
    "Get Python version and list of installed packages. "
    "Call ONCE at the start to know which libraries are available. "
    "ONLY use packages that appear in this list — never import packages not listed here.",
    {"include_packages": {"type": "boolean",
                          "description": "Include full pip list (default true)"}},
    [],
)

READ_ENV_FILE = _def(
    "read_env_file",
    "Read the .env file to see environment variables available to the project.",
    {},
    [],
)

REMEMBER = _def(
    "remember",
    "Store a key fact in working memory for later use in this session.",
    {"key":   {"type": "string", "description": "Short identifier, e.g. 'main_file'"},
     "value": {"type": "string", "description": "Value to store"}},
    ["key", "value"],
)

RECALL = _def(
    "recall",
    "Retrieve a previously stored fact from working memory.",
    {"key": {"type": "string", "description": "Key used in the remember call"}},
    ["key"],
)

FINISH = _def(
    "finish",
    "Signal task completion. "
    "ONLY call this after ALL required files are written and verified. "
    "verdict=PASS means the output is correct and complete. "
    "verdict=FAIL means critical problems remain that must be fixed.",
    {"summary": {"type": "string",
                 "description": "What was done — list files created or issues found"},
     "verdict": {"type": "string", "enum": ["PASS", "FAIL"],
                 "description": "PASS = done and working, FAIL = needs more work"}},
    ["summary", "verdict"],
)


# ── Toolsets per agent ────────────────────────────────────────────────────────

ARCHITECT_TOOLS = [WEB_SEARCH, WRITE_FILE, GET_ENV_INFO, REMEMBER, RECALL, FINISH]
CODER_TOOLS     = [WEB_SEARCH, READ_FILE, WRITE_FILE, EDIT_FILE, DELETE_FILE, LIST_FILES,
                   RUN_COMMAND, GET_ENV_INFO, READ_ENV_FILE, REMEMBER, RECALL, FINISH]
TESTER_TOOLS    = [READ_FILE, WRITE_FILE, LIST_FILES, RUN_COMMAND,
                   GET_ENV_INFO, REMEMBER, RECALL, FINISH]
REVIEWER_TOOLS  = [READ_FILE, LIST_FILES, WRITE_FILE, EDIT_FILE, REMEMBER, RECALL, FINISH]