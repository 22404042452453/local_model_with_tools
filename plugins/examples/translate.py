"""
plugins/examples/translate.py — Translation plugin example

Copy to plugins/ directory to activate:
    cp plugins/examples/translate.py plugins/translate.py
"""

TOOL_DEFINITION = {
    "name": "translate",
    "description": "Translate text between languages using free API (MyMemory).",
    "parameters": {
        "type": "object",
        "properties": {
            "text":   {"type": "string", "description": "Text to translate"},
            "source": {"type": "string", "description": "Source language code: en, ru, de, fr, es, etc."},
            "target": {"type": "string", "description": "Target language code: en, ru, de, fr, es, etc."},
        },
        "required": ["text", "target"],
    },
}

# Available to all agents (omit AGENTS to make it available to all)
# AGENTS = ["researcher", "writer"]


def execute(args: dict) -> str:
    import urllib.request
    import urllib.parse
    import json

    text   = args["text"]
    source = args.get("source", "auto")
    target = args["target"]

    pair = f"{source}|{target}"
    url  = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text)}&langpair={pair}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            translated = data["responseData"]["translatedText"]
            return f"[{source} → {target}] {translated}"
    except Exception as e:
        return f"Translation error: {e}"
