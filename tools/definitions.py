"""tools/definitions.py — tool schemas (provider-agnostic)"""


def _def(name, description, properties, required) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


# ── Individual tools ──────────────────────────────────────────────────────────

WEB_SEARCH = _def("web_search", "Search the web for current information.",
    {"query": {"type": "string"}}, ["query"])

CALCULATE = _def("calculate",
    "Evaluate a Python math expression. The math module is available.",
    {"expression": {"type": "string", "description": "e.g. 'math.sqrt(144)' or '365*24*3600'"}},
    ["expression"])

READ_FILE = _def("read_file", "Read a file from the workspace.",
    {"path": {"type": "string", "description": "Relative path, e.g. 'src/main.py'"}},
    ["path"])

WRITE_FILE = _def("write_file", "Create or overwrite a file in the workspace.",
    {"path":    {"type": "string"},
     "content": {"type": "string"}},
    ["path", "content"])

LIST_FILES = _def("list_files", "List all files in the workspace recursively.", {}, [])

RUN_COMMAND = _def("run_command",
    "Run a shell command inside the workspace (tests, linting, installs, etc.).",
    {"command": {"type": "string", "description": "e.g. 'python -m pytest tests/ -v'"},
     "timeout": {"type": "integer", "description": "Seconds, default 60"}},
    ["command"])

GET_ENV_INFO = _def("get_env_info",
    "Get information about the current Python environment: version, installed packages, OS info.",
    {"include_packages": {"type": "boolean",
                          "description": "Include full pip list (default true)"}},
    [])

READ_ENV_FILE = _def("read_env_file",
    "Read the .env file from the workspace (if it exists). Shows environment variables available to the project.",
    {}, [])

REMEMBER = _def("remember", "Store a key-value fact in working memory.",
    {"key": {"type": "string"}, "value": {"type": "string"}}, ["key", "value"])

RECALL = _def("recall", "Retrieve a stored fact from working memory.",
    {"key": {"type": "string"}}, ["key"])

# finish with structured verdict for tester/reviewer
FINISH = _def("finish",
    "Call when the task is fully complete. verdict=PASS means no blocking issues, FAIL means critical problems found.",
    {"summary": {"type": "string", "description": "What was done / key findings"},
     "verdict": {"type": "string", "enum": ["PASS", "FAIL"],
                 "description": "PASS = ready to ship, FAIL = needs more work"}},
    ["summary", "verdict"])


# ── Toolsets per agent ────────────────────────────────────────────────────────

ARCHITECT_TOOLS = [WEB_SEARCH, WRITE_FILE, GET_ENV_INFO, REMEMBER, RECALL, FINISH]
CODER_TOOLS     = [WEB_SEARCH, READ_FILE, WRITE_FILE, LIST_FILES, RUN_COMMAND,
                   GET_ENV_INFO, READ_ENV_FILE, REMEMBER, RECALL, FINISH]
TESTER_TOOLS    = [READ_FILE, WRITE_FILE, LIST_FILES, RUN_COMMAND,
                   GET_ENV_INFO, REMEMBER, RECALL, FINISH]
REVIEWER_TOOLS  = [READ_FILE, LIST_FILES, WRITE_FILE, REMEMBER, RECALL, FINISH]
