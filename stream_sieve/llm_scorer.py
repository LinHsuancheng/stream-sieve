from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx


DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com/chat/completions"


def score_batch(
    rows: list[dict[str, Any]],
    interests: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    sample_chars: int = 50,
    categories: list[str] | None = None,
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
            {"role": "user", "content": build_prompt(rows, interests, sample_chars, categories)},
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
) -> str:
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "source": row["source_id"],
                "title": row["title"],
                "sample": content_sample(row.get("content") or "", sample_chars),
            }
        )
    return (
        "You are a relevance classifier for my personal information feed.\n\n"
        "My interests:\n"
        f"{interests.strip()}\n\n"
        "For each article, score 0-10:\n"
        "- relevance: relevant to my interests\n"
        "- importance: consequential or useful\n"
        "- novelty: likely to contain new information rather than repetition\n"
        f"- category: choose exactly one from {json.dumps(categories or ['tech', 'society', 'open_source', 'life', 'politics', 'economics', 'other'], ensure_ascii=False)}\n\n"
        "Return JSON only in this exact shape:\n"
        '{"items":[{"id":123,"relevance":0,"importance":0,"novelty":0,"category":"Other","reason":"short reason"}]}\n\n'
        "Articles:\n"
        f"{json.dumps(items, ensure_ascii=False)}"
    )


def content_sample(content: str, chars: int = 50) -> str:
    chars = max(0, chars)
    text = " ".join(content.split())
    return text[:chars]


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
                "relevance": _score(item.get("relevance")),
                "importance": _score(item.get("importance")),
                "novelty": _score(item.get("novelty")),
                "category": str(item.get("category") or "Other"),
                "reason": str(item.get("reason") or ""),
            }
        )
    return out


def total_score(score: dict[str, Any]) -> float:
    return round(0.5 * score["relevance"] + 0.3 * score["importance"] + 0.2 * score["novelty"], 2)


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
    content = '{"items":[{"id":1,"relevance":8,"importance":6,"novelty":7,"category":"AI","reason":"x"}]}'
    scores = parse_scores(content)
    assert scores[0]["id"] == 1
    assert total_score(scores[0]) == 7.2
    assert content_sample("  a\n\nbcdef  ", 4) == "a bc"


if __name__ == "__main__":
    _demo()
