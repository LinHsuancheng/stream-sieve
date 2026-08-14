from __future__ import annotations

import json
import re
from typing import Any


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "about",
    "after",
    "before",
    "over",
    "under",
    "latest",
    "breaking",
}


def cluster_articles(rows: list[dict[str, Any]], similarity: float = 0.34) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for row in rows:
        tokens = article_tokens(row)
        target = None
        target_score = 0.0
        for cluster in clusters:
            score = token_similarity(tokens, cluster["_tokens"])
            if score > target_score:
                target = cluster
                target_score = score
        if target and target_score >= similarity:
            target["items"].append(cluster_item(row))
            target["_tokens"].update(tokens)
            target["topics"] = sorted(set(target["topics"]) | set(read_json_list(row.get("topics_json"))))
            target["entities"] = sorted(set(target["entities"]) | set(read_json_list(row.get("entities_json"))))
        else:
            clusters.append(
                {
                    "cluster_id": len(clusters) + 1,
                    "topic": cluster_topic(row),
                    "topics": read_json_list(row.get("topics_json")),
                    "entities": read_json_list(row.get("entities_json")),
                    "items": [cluster_item(row)],
                    "_tokens": tokens,
                }
            )
    for cluster in clusters:
        cluster.pop("_tokens", None)
        if len(cluster["items"]) > 1:
            cluster["topic"] = cluster_title(cluster)
    return clusters


def cluster_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": row["id"],
        "title": row["title"],
        "source": row["source_id"],
        "source_meta": row.get("source_meta"),
        "score": row.get("total_score"),
        "category": row.get("category"),
        "one_liner": row.get("one_liner") or "",
        "summary": row.get("summary") or "",
        "key_points": read_json_list(row.get("key_points_json")),
        "why_care": row.get("why_care") or "",
        "url": row.get("url"),
    }


def article_tokens(row: dict[str, Any]) -> set[str]:
    parts = [
        str(row.get("title") or ""),
        str(row.get("one_liner") or ""),
        " ".join(read_json_list(row.get("topics_json"))),
        " ".join(read_json_list(row.get("entities_json"))),
    ]
    text = " ".join(parts).lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9.+#-]{2,}|[\u4e00-\u9fff]{2,}", text))
    return {token for token in tokens if token not in STOPWORDS}


def token_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def read_json_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def cluster_topic(row: dict[str, Any]) -> str:
    topics = read_json_list(row.get("topics_json"))
    if topics:
        return topics[0]
    return str(row.get("category") or "Other")


def cluster_title(cluster: dict[str, Any]) -> str:
    entities = cluster.get("entities") or []
    topics = cluster.get("topics") or []
    if entities and topics:
        return f"{entities[0]} / {topics[0]}"
    if entities:
        return str(entities[0])
    if topics:
        return str(topics[0])
    return str(cluster.get("topic") or "Topic")


def _demo() -> None:
    rows = [
        {"id": 1, "title": "OpenAI releases GPT-X", "source_id": "a", "topics_json": '["AI"]', "entities_json": '["OpenAI"]'},
        {"id": 2, "title": "Reuters: OpenAI GPT-X launch", "source_id": "b", "topics_json": '["AI"]', "entities_json": '["OpenAI"]'},
    ]
    assert len(cluster_articles(rows)) == 1


if __name__ == "__main__":
    _demo()
