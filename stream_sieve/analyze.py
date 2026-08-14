from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx


ANALYZE_PROMPT = """You analyze articles for a personal daily briefing.

Write Chinese summaries unless the article itself is mainly English and the title should remain English.
Return JSON only in this exact shape:
{
  "items": [
    {
      "article_id": 123,
      "one_liner": "...",
      "summary": "...",
      "key_points": ["...", "...", "..."],
      "topics": ["AI", "Inference"],
      "entities": ["OpenAI"],
      "why_care": "..."
    }
  ]
}

Rules:
- Keep article_id exactly as provided.
- Do not invent facts, numbers, names, or URLs.
- Prefer concrete facts over generic descriptions.
- key_points should contain 2-5 concise points.
- topics and entities should be short labels.
- why_care should explain the practical consequence for an informed reader.
"""


def analyze_batch(
    rows: list[dict[str, Any]],
    *,
    model: str,
    base_url: str,
    api_key: str | None = None,
    content_chars: int = 4000,
    nonthink: bool = True,
    timeout: float = 180,
    retries: int = 1,
) -> list[dict[str, Any]]:
    api_key = api_key or _api_key()
    if not api_key:
        raise RuntimeError("missing API key: set STREAM_SIEVE_LLM_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": ANALYZE_PROMPT},
            {"role": "user", "content": json.dumps(_analysis_items(rows, content_chars), ensure_ascii=False)},
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
    return parse_analyses(content)


def parse_analyses(content: str) -> list[dict[str, Any]]:
    data = json.loads(_strip_json_fence(content))
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("LLM response must contain an items list")
    out = []
    for item in items:
        analysis = {
            "article_id": int(item["article_id"]),
            "one_liner": str(item.get("one_liner") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "key_points": _string_list(item.get("key_points")),
            "topics": _string_list(item.get("topics")),
            "entities": _string_list(item.get("entities")),
            "why_care": str(item.get("why_care") or "").strip(),
        }
        analysis["raw_json"] = json.dumps(analysis, ensure_ascii=False)
        out.append(analysis)
    return out


def _analysis_items(rows: list[dict[str, Any]], content_chars: int) -> list[dict[str, Any]]:
    return [
        {
            "article_id": row["id"],
            "title": row["title"],
            "source": row["source_id"],
            "author": row.get("author"),
            "published_at": row.get("published_at"),
            "score": row.get("total_score"),
            "category": row.get("category"),
            "score_reason": row.get("reason"),
            "content": " ".join(str(row.get("content") or "").split())[:content_chars],
        }
        for row in rows
    ]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    return stripped


def _api_key() -> str | None:
    return (
        os.environ.get("STREAM_SIEVE_LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )


def _demo() -> None:
    data = '{"items":[{"article_id":1,"one_liner":"o","summary":"s","key_points":["a"],"topics":["t"],"entities":["e"],"why_care":"w"}]}'
    rows = parse_analyses(data)
    assert rows[0]["article_id"] == 1
    assert rows[0]["key_points"] == ["a"]


if __name__ == "__main__":
    _demo()
