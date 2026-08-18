from __future__ import annotations

from pathlib import Path

import yaml

from stream_sieve.delivery import filesystem, smtp


def load_delivery(path: str) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"delivery config not found: {path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    delivery = data.get("delivery", data)
    if not isinstance(delivery, dict):
        raise ValueError("delivery config must be a mapping")
    return delivery


def deliver(config: dict, subject: str, html: str, text: str | None = None) -> str:
    kind = config.get("type")
    if kind == "filesystem":
        return filesystem.send(config, subject, html, text)
    if kind == "smtp":
        return smtp.send(config, subject, html, text)
    if kind == "gmail_api":
        from stream_sieve.delivery import gmail_api

        return gmail_api.send(config, subject, html, text)
    raise ValueError(f"unsupported delivery.type: {kind}")
