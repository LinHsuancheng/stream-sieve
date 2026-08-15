from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
import time
from typing import Any

import httpx

from stream_sieve.cluster import cluster_articles


DIGEST_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "digest.md").read_text(encoding="utf-8")


def synthesize_digest(
    rows: list[dict[str, Any]],
    *,
    model: str,
    base_url: str,
    api_key: str | None = None,
    content_chars: int = 2000,
    nonthink: bool = True,
    timeout: float = 180,
    retries: int = 1,
) -> dict[str, Any]:
    api_key = api_key or _api_key()
    if not api_key:
        raise RuntimeError("missing API key: set STREAM_SIEVE_LLM_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": DIGEST_PROMPT},
            {"role": "user", "content": json.dumps(_digest_input(rows, content_chars), ensure_ascii=False)},
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
    return json.loads(_strip_json_fence(response.json()["choices"][0]["message"]["content"]))


def render_digest_markdown(digest: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    by_id = {int(row["id"]): row for row in rows}
    parts = [f"# {digest.get('headline') or 'Daily Reading'}", "", date.today().isoformat(), ""]

    intro = str(digest.get("intro") or "").strip()
    if intro:
        parts.extend([intro, ""])

    highlights = digest.get("highlights") or []
    sections = digest.get("sections") or []
    present_sections = [section for section in sections if section.get("items")]
    if not highlights and not present_sections:
        return render_legacy_markdown(rows)

    if highlights:
        parts.extend(["## Highlights", ""])
        for index, item in enumerate(highlights[:10], start=1):
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or item.get("summary") or item.get("what_changed") or "").strip()
            parts.append(f"{index}. **{title}**")
            if description:
                parts.append(f"   {description}")
            refs = article_links(item.get("article_ids"), by_id)
            if refs:
                parts.append(f"   {refs}")
            parts.append("")

    if present_sections:
        parts.extend(["## Contents", ""])
        for section in present_sections:
            category = str(section.get("category") or section.get("topic") or "other").strip()
            parts.append(f"- {FIELD_LABELS.get(category, category)}")
        parts.append("")

    for section in sections:
        category = str(section.get("category") or section.get("topic") or "other").strip()
        items = (section.get("items") or [])[:5]
        if not items:
            continue
        parts.extend([f"## {FIELD_LABELS.get(category, category)}", ""])
        for item in items:
            rows_for_item = _rows_for_ids(item.get("article_ids"), by_id)
            row = rows_for_item[0] if rows_for_item else {}
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or item.get("description") or row.get("summary") or row.get("one_liner") or "").strip()
            parts.extend([f"### {title}", "", _article_meta(row), ""])
            if summary:
                parts.extend([summary, ""])
            refs = article_links(item.get("article_ids"), by_id)
            if refs:
                parts.extend([refs, ""])
        parts.append("")

    return "\n".join(parts).strip() + "\n"


FIELD_LABELS = {
    "ai_news": "AI News",
    "tech": "Tech",
    "business": "Business",
    "economics": "Economics",
    "politics": "Politics",
    "society": "Society",
    "cognition": "Cognition",
}


def _rows_for_ids(article_ids: Any, by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(article_ids, list):
        return []
    rows = []
    for article_id in article_ids:
        try:
            rows.append(by_id[int(article_id)])
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def _article_meta(row: dict[str, Any]) -> str:
    if not row:
        return ""
    words = _word_count(str(row.get("content") or ""))
    minutes = max(1, (words + 199) // 200) if words else 1
    bits = [
        str(row.get("source_id") or "").strip(),
        str(row.get("published_at") or "").strip(),
        f"{words} words",
        f"{minutes} min",
    ]
    if row.get("total_score") is not None:
        bits.append(f"score {row.get('total_score')}")
    return " · ".join(bit for bit in bits if bit)


def _word_count(text: str) -> int:
    return len(text.split()) or len(text) // 2


def _digest_input(rows: list[dict[str, Any]], content_chars: int) -> dict[str, Any]:
    return {
        "clusters": cluster_articles(rows),
        "fallback_articles": _fallback_items(rows, content_chars),
    }


def _fallback_items(rows: list[dict[str, Any]], content_chars: int) -> list[dict[str, Any]]:
    items = []
    for row in rows:
        if row.get("one_liner") or row.get("summary"):
            continue
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "source": row["source_id"],
                "source_meta": row.get("source_meta"),
                "author": row.get("author"),
                "score": row.get("total_score"),
                "category": row.get("category"),
                "reason": row.get("reason"),
                "content": " ".join(str(row.get("content") or "").split())[:content_chars],
            }
        )
    return items


def article_links(article_ids: Any, by_id: dict[int, dict[str, Any]]) -> str:
    if not isinstance(article_ids, list):
        return ""
    links = []
    for article_id in article_ids:
        try:
            row = by_id[int(article_id)]
        except (KeyError, TypeError, ValueError):
            continue
        links.append(f"[{row['source_id']}]({row['url']})")
    return " / ".join(links)


def render_legacy_markdown(rows: list[dict[str, Any]]) -> str:
    parts = ["# Daily Reading", "", date.today().isoformat(), ""]
    for index, row in enumerate(rows, start=1):
        summary = row.get("summary") or row.get("one_liner") or row.get("reason") or ""
        parts.extend(
            [
                f"### {index}. {row['title']}",
                "",
                _article_meta(row),
                "",
                str(summary).strip(),
                "",
                f"[{row['source_id']}]({row['url']})",
                "",
            ]
        )
    return "\n".join(parts).strip() + "\n"


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
    rows = [{"id": 1, "title": "T", "source_id": "s", "author": "a", "url": "u", "total_score": 8, "content": "hello " * 10}]
    digest = {
        "headline": "H",
        "highlights": [{"title": "x", "article_ids": [1], "description": "d"}],
        "sections": [{"category": "tech", "items": [{"title": "T", "article_ids": [1], "summary": "s"}]}],
    }
    assert "[s](u)" in render_digest_markdown(digest, rows)
    assert "Why it matters" not in render_digest_markdown(digest, rows)
    assert len(_fallback_items(rows, 5)[0]["content"]) == 5


if __name__ == "__main__":
    _demo()
