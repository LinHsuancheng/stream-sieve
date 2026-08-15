from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

import httpx


DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com/chat/completions"
SCORE_PROMPT_TEMPLATE = (Path(__file__).resolve().parents[1] / "prompts" / "score.md").read_text(encoding="utf-8")


def score_batch(
    rows: list[dict[str, Any]],
    interests: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    sample_chars: int = 50,
    categories: list[str] | None = None,
    field_context: dict[str, Any] | None = None,
    nonthink: bool = False,
    timeout: float = 180,
    retries: int = 1,
) -> list[dict[str, Any]]:
    model = model or os.environ.get("STREAM_SIEVE_LLM_MODEL") or DEFAULT_MODEL
    base_url = base_url or os.environ.get("STREAM_SIEVE_LLM_BASE_URL") or DEFAULT_BASE_URL
    api_key = api_key or _api_key()
    if not api_key:
        raise RuntimeError("missing API key: set STREAM_SIEVE_LLM_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You score articles for a personal information feed. Return JSON only."},
            {"role": "user", "content": build_prompt(rows, interests, sample_chars, categories, field_context)},
        ],
        "response_format": {"type": "json_object"},
    }
    if nonthink:
        payload["enable_thinking"] = False
        payload["thinking"] = {"type": "disabled"}
    for attempt in range(retries + 1):
        try:
            response = httpx.post(
                base_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            break
        except httpx.TimeoutException:
            if attempt >= retries:
                raise
            time.sleep(2 * (attempt + 1))
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_scores(content)


def build_prompt(
    rows: list[dict[str, Any]],
    interests: str,
    sample_chars: int = 50,
    categories: list[str] | None = None,
    field_context: dict[str, Any] | None = None,
) -> str:
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "source": row["source_id"],
                "source_meta": compact_source_meta(row.get("source_meta")),
                "title": row["title"],
                "sample": content_sample(row.get("content") or "", sample_chars),
            }
        )
    allowed_categories = categories or ["ai_news", "politics", "economics", "tech", "business", "cognition", "society"]
    return SCORE_PROMPT_TEMPLATE.format(
        interests=interests.strip(),
        field_context=format_field_context(field_context),
        categories=json.dumps(allowed_categories, ensure_ascii=False),
        example_category=json.dumps(allowed_categories[0], ensure_ascii=False),
        articles=json.dumps(items, ensure_ascii=False),
    )


def format_field_context(field_context: dict[str, Any] | None) -> str:
    if not field_context:
        return ""
    return (
        "Current field context:\n"
        f"{json.dumps(field_context, ensure_ascii=False)}\n\n"
        "Score only for this field's time horizon and purpose. Do not compare against other fields.\n\n"
    )


def content_sample(content: str, chars: int = 50) -> str:
    chars = max(0, chars)
    text = " ".join(content.split())
    return text[:chars]


def compact_source_meta(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "tier": value.get("tier"),
        "source_type": value.get("source_type"),
        "topic_focus": value.get("topic_focus"),
        "briefing_category": value.get("briefing_category"),
        "briefing_categories": value.get("briefing_categories"),
        "domains": value.get("domains"),
        "seed_origin": value.get("seed_origin"),
        "quality": value.get("quality"),
        "policy": value.get("policy"),
    }


def parse_scores(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    data = json.loads(text)
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("LLM response must contain an items list")
    out = []
    for item in items:
        out.append(
            {
                "id": int(item["id"]),
                "score": _score(item.get("score", item.get("total_score", item.get("importance", 0)))),
                "relevance": _score(item.get("personal_relevance", item.get("relevance", item.get("score", 0)))),
                "importance": _score(item.get("information_value", item.get("importance", item.get("score", 0)))),
                "novelty": _score(item.get("timeliness", item.get("novelty", 0))),
                "category": str(item.get("category") or "Other"),
                "reason": str(item.get("reason") or ""),
            }
        )
    return out


def total_score(score: dict[str, Any]) -> float:
    if "score" in score:
        return round(_score(score["score"]), 2)
    return round(_score(score.get("importance", 0)), 2)


def _score(value: Any) -> float:
    number = float(value)
    return max(0.0, min(10.0, number))


def _api_key() -> str | None:
    return (
        os.environ.get("STREAM_SIEVE_LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )


def _demo() -> None:
    content = '{"items":[{"id":1,"score":8,"personal_relevance":7,"information_value":8,"timeliness":6,"category":"AI","reason":"x"}]}'
    scores = parse_scores(content)
    assert scores[0]["id"] == 1
    assert total_score(scores[0]) == 8
    assert content_sample("  a\n\nbcdef  ", 4) == "a bc"


if __name__ == "__main__":
    _demo()
