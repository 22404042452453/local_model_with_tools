"""
plugins/examples/screenshot.py — Screenshot plugin example

Takes a screenshot of a URL using a free API.
Copy to plugins/ directory to activate.

Requires: none (uses free API)
"""

TOOL_DEFINITION = {
    "name": "screenshot_url",
    "description": "Take a screenshot of a web page. Returns the saved file path.",
    "parameters": {
        "type": "object",
        "properties": {
            "url":      {"type": "string", "description": "Full URL, e.g. https://example.com"},
            "filename": {"type": "string", "description": "Output filename, e.g. 'page.png'"},
        },
        "required": ["url"],
    },
}

AGENTS = ["researcher", "reviewer"]


def execute(args: dict) -> str:
    import urllib.request
    import urllib.parse
    from pathlib import Path

    url      = args["url"]
    filename = args.get("filename", "screenshot.png")

    api_url = f"https://image.thum.io/get/width/1280/{url}"

    try:
        output = Path("workspace") / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(api_url, str(output))
        return f"Screenshot saved: {output} ({output.stat().st_size} bytes)"
    except Exception as e:
        return f"Screenshot error: {e}"
