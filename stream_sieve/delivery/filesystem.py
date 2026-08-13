from __future__ import annotations

from pathlib import Path


def send(config: dict, subject: str, html: str, text: str | None = None) -> str:
    path = Path(str(config["path"])).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)
