from __future__ import annotations

from html import escape


def markdown_to_html(markdown: str) -> str:
    body = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            body.append(f"<h3>{escape(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            body.append(f"<h2>{escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            body.append(f"<h1>{escape(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            body.append(f"<p>{escape(stripped)}</p>")
        else:
            body.append(f"<p>{escape(stripped)}</p>")
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<style>body{font-family:Arial,sans-serif;line-height:1.5;max-width:760px;margin:24px auto;padding:0 16px}"
        "h1,h2,h3{line-height:1.25}p{margin:8px 0}</style>"
        "</head><body>"
        + "\n".join(body)
        + "</body></html>"
    )
