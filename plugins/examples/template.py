"""
plugins/examples/template.py — Plugin template

1. Copy to plugins/ directory:
     cp plugins/examples/template.py plugins/my_tool.py
2. Edit TOOL_DEFINITION and execute()
3. Restart server or click "Reload" in UI

The tool will automatically appear for the specified agents.
"""

# ── Tool schema (sent to the LLM) ────────────────────────────────────────────

TOOL_DEFINITION = {
    "name": "my_tool",                              # unique name
    "description": "What this tool does (1-2 lines — the LLM reads this)",
    "parameters": {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "What to pass in",
            },
            # Add more params here
        },
        "required": ["input"],
    },
}

# ── Which agents can use this tool (optional) ─────────────────────────────────
# Omit AGENTS entirely to make it available to ALL agents.
# AGENTS = ["coder", "tester"]
# AGENTS = ["researcher"]

# ── Tool implementation ───────────────────────────────────────────────────────

def execute(args: dict) -> str:
    """
    Runs when the LLM calls this tool.
    
    args: dict matching the schema above
    returns: string result shown back to the LLM
    """
    input_val = args["input"]

    # Your logic here
    result = f"Processed: {input_val}"

    return result
