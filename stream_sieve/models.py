from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json


@dataclass(frozen=True)
class ItemRef:
    source_id: str
    url: str
    title: str | None = None
    external_id: str | None = None
    published_at: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass(frozen=True)
class RawDocument:
    source_id: str
    url: str
    content: str
    mime_type: str
    fetched_at: str
    transport: str
    status_code: int | None
    content_hash: str


@dataclass(frozen=True)
class Article:
    source_id: str
    url: str
    title: str
    content: str
    fetched_at: str
    content_hash: str
    author: str | None = None
    published_at: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
