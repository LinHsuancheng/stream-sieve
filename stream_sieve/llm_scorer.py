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
    return (
        "You are a triage editor for a private intelligence feed.\n\n"
        "My interests:\n"
        f"{interests.strip()}\n\n"
        f"{format_field_context(field_context)}"
        "Use source_meta as a prior, not as an automatic answer:\n"
        "- T0 primary sources are best for facts.\n"
        "- T1 professional editorial sources are useful for reporting and context.\n"
        "- T2 expert/curated sources are useful for discovery and interpretation.\n"
        "- T3 social/algorithmic sources are mainly discovery signals and need more caution.\n\n"
        "For each article, choose a category first, then directly assign one score from 0-10.\n"
        "Do not compute a weighted sum. The score is your editorial judgment of whether this item deserves attention.\n\n"
        "The score should consider:\n"
        "- personal_relevance: how closely the item matches my interests and recurring information needs.\n"
        "- information_value: whether it changes what I should believe, track, or understand.\n"
        "- source_quality: whether the source is primary, credible, or merely a discovery signal.\n"
        "- timeliness: important for politics, economics, tech, business, markets, products, policy, and society news.\n"
        "- durability: important for cognition, ideas, essays, history, and conceptual writing, where timeliness is often weak or irrelevant.\n\n"
        "Use different category rubrics:\n"
        "- politics: reward concrete policy decisions, elections, regulation, institutions, geopolitics, and power shifts. Timeliness matters.\n"
        "- economics: reward macro data, monetary/fiscal policy, inflation, employment, debt, trade, financial stability, and market-moving changes. Timeliness matters.\n"
        "- tech: reward AI, software, hardware, infrastructure, research results, product releases, open-source systems, and engineering changes. Timeliness matters, but high-quality technical research can remain valuable after publication.\n"
        "- business: reward company strategy, financing, competition, pricing, distribution, earnings, market structure, and business-model changes. Timeliness matters.\n"
        "- cognition: reward durable insight, explanatory power, unusually clear arguments, mental models, learning, judgment, and concepts worth remembering. Do not penalize merely because it is not breaking news.\n"
        "- society: reserve this for major social news and sharp social conflicts, especially gender conflict, family/paternity disputes, judicial unfairness toward men, institutional injustice, education, employment, public safety, and issues that reveal meaningful social tension. Timeliness matters, but systemic significance can also make an item valuable.\n"
        "- social/discovery sources: score high only when the post points to concrete evidence, a primary source, or a genuinely useful signal.\n\n"
        f"category: choose exactly one from {json.dumps(categories or ['politics', 'economics', 'tech', 'business', 'cognition', 'society'], ensure_ascii=False)}\n\n"
        "Return JSON only in this exact shape:\n"
        '{"items":[{"id":123,"score":0,"personal_relevance":0,"information_value":0,"timeliness":0,"category":"tech","reason":"short reason"}]}\n\n'
        "Articles:\n"
        f"{json.dumps(items, ensure_ascii=False)}"
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
        "briefing_category": value.get("briefing_category"),
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
