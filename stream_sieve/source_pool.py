from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_SOURCE_POOL = "sourcepool.yaml"


def load_source_pool(path: str | None = DEFAULT_SOURCE_POOL) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    file = Path(path)
    if not file.exists():
        return {}
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or {}
    if not isinstance(sources, dict):
        raise ValueError("sourcepool.yaml must contain a sources mapping")
    return {str(source_id): normalize_source_meta(source_id, meta) for source_id, meta in sources.items()}


def normalize_source_meta(source_id: str, value: Any) -> dict[str, Any]:
    meta = value if isinstance(value, dict) else {}
    quality = meta.get("quality") if isinstance(meta.get("quality"), dict) else {}
    policy = meta.get("policy") if isinstance(meta.get("policy"), dict) else {}
    return {
        "id": source_id,
        "name": str(meta.get("name") or source_id),
        "domains": string_list(meta.get("domains")),
        "briefing_category": str(meta.get("briefing_category") or ""),
        "seed_origin": str(meta.get("seed_origin") or ""),
        "tier": str(meta.get("tier") or "T3"),
        "source_type": str(meta.get("source_type") or "unknown"),
        "quality": {
            "authority": bounded_float(quality.get("authority"), 0.5),
            "originality": bounded_float(quality.get("originality"), 0.5),
            "signal_density": bounded_float(quality.get("signal_density"), 0.5),
        },
        "policy": {
            "daily_cap": int(policy.get("daily_cap") or 5),
            "discovery_only": bool(policy.get("discovery_only", False)),
            "usable_as_evidence": bool(policy.get("usable_as_evidence", True)),
        },
    }


def enrich_rows(rows: list[dict[str, Any]], source_pool: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [enrich_row(row, source_pool) for row in rows]


def enrich_row(row: dict[str, Any], source_pool: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = dict(row)
    out["source_meta"] = source_pool.get(str(row.get("source_id"))) or normalize_source_meta(str(row.get("source_id") or "unknown"), {})
    return out


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def bounded_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _demo() -> None:
    pool = load_source_pool("/does/not/exist")
    assert pool == {}
    row = enrich_row({"source_id": "x"}, pool)
    assert row["source_meta"]["id"] == "x"


if __name__ == "__main__":
    _demo()
