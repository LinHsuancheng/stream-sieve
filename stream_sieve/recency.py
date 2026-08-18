from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from typing import Any

DEFAULT_HALF_LIFE_DAYS: dict[str, float | None] = {
    "ai_news": 1.0, "tech": 7.0,
    "politics-china": 3.0, "politics-global": 3.0,
    "economy-china": 7.0, "economy-global": 7.0,
    "society": 7.0, "cognition": None,
}


def apply_recency(rows: list[dict[str, Any]], spec: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    spec = spec or {}
    if spec.get("enabled", True) is False:
        return rows
    floor = max(0.0, min(1.0, float(spec.get("floor", 0.1))))
    half_lives = dict(DEFAULT_HALF_LIFE_DAYS)
    configured = spec.get("half_life_days") or {}
    if isinstance(configured, dict):
        half_lives.update(configured)
    ranked = []
    for row in rows:
        age_days = article_age_days(row)
        factor = recency_factor(age_days, half_lives.get(str(row.get("category") or "")), floor)
        raw_score = float(row.get("total_score") or 0.0)
        ranked_row = dict(row)
        ranked_row["age_days"] = round(age_days, 2)
        ranked_row["recency_factor"] = round(factor, 4)
        ranked_row["effective_score"] = round(raw_score * factor, 4)
        ranked.append(ranked_row)
    return sorted(ranked, key=lambda item: (item["effective_score"], float(item.get("total_score") or 0.0)), reverse=True)


def article_age_days(row: dict[str, Any], now: datetime | None = None) -> float:
    timestamp = parse_timestamp(row.get("published_at")) or parse_timestamp(row.get("first_seen_at"))
    if timestamp is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - timestamp).total_seconds() / 86400.0)


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def recency_factor(age_days: float, half_life_days: Any, floor: float = 0.1) -> float:
    if half_life_days is None:
        return 1.0
    try:
        half_life = float(half_life_days)
    except (TypeError, ValueError):
        return 1.0
    if half_life <= 0:
        return 1.0
    floor = max(0.0, min(1.0, float(floor)))
    return floor + (1.0 - floor) * math.pow(0.5, max(0.0, age_days) / half_life)


if __name__ == "__main__":
    assert recency_factor(0, 1) == 1.0
    assert recency_factor(1, 1, 0) == 0.5
    assert recency_factor(100, None) == 1.0
