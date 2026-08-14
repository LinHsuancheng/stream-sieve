from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from stream_sieve.cluster import cluster_articles


DIGEST_PROMPT = """You are an editor writing a concise personal daily briefing.

Use the supplied article clusters to produce a readable morning digest, not a list dump.
Write in Chinese unless the article title is English.

Return JSON only in this exact shape:
{
  "headline": "Morning Brief",
  "headlines": [
    {
      "title": "...",
      "article_ids": [123],
      "why_it_matters": "..."
    }
  ],
  "sections": [
    {
      "topic": "...",
      "overview": "...",
      "items": [
        {
          "article_ids": [123],
          "title": "...",
          "what_happened": "...",
          "why_it_matters": "...",
          "sources": ["..."]
        }
      ]
    }
  ],
  "connections": ["...", "..."],
  "further_reads": [123, 456]
}

Rules:
- Keep article_ids exactly as provided.
- Do not invent URLs.
- Merge duplicates into one item instead of repeating them.
- Use the best source as the lead, and mention useful secondary coverage when available.
- Make summaries specific and useful.
"""


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
    parts = [f"# {digest.get('headline') or 'Morning Brief'}", ""]

    headlines = digest.get("headlines") or []
    if headlines:
        parts.extend(["## 今日最重要的 3 件事", ""])
        for index, item in enumerate(headlines, start=1):
            title = str(item.get("title") or "").strip()
            why = str(item.get("why_it_matters") or "").strip()
            refs = article_links(item.get("article_ids"), by_id)
            parts.append(f"{index}. {title}")
            if why:
                parts.append(f"   为什么重要：{why}")
            if refs:
                parts.append(f"   来源：{refs}")
        parts.append("")

    sections = digest.get("sections") or []
    for section in sections:
        topic = str(section.get("topic") or "Other").strip()
        overview = str(section.get("overview") or "").strip()
        parts.extend([f"## {topic}", ""])
        if overview:
            parts.extend([overview, ""])
        for item in section.get("items") or []:
            title = str(item.get("title") or "").strip()
            parts.extend([f"### {title}", ""])
            what = str(item.get("what_happened") or "").strip()
            why = str(item.get("why_it_matters") or "").strip()
            if what:
                parts.extend(["发生了什么：", what, ""])
            if why:
                parts.extend(["为什么值得关注：", why, ""])
            refs = article_links(item.get("article_ids"), by_id)
            if refs:
                parts.extend([f"来源：{refs}", ""])

    connections = digest.get("connections") or []
    if connections:
        parts.extend(["## 关联观察", ""])
        for item in connections:
            parts.append(f"- {item}")
        parts.append("")

    further_reads = digest.get("further_reads") or []
    if further_reads:
        parts.extend(["## Further Reading", ""])
        for article_id in further_reads:
            try:
                row = by_id[int(article_id)]
            except (KeyError, TypeError, ValueError):
                continue
            parts.append(f"- [{row['title']}]({row['url']})")
        parts.append("")

    if len(parts) == 2:
        return render_legacy_markdown(rows)
    return "\n".join(parts).strip() + "\n"


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
    parts = ["# Morning Brief", ""]
    for index, row in enumerate(rows, start=1):
        summary = row.get("summary") or row.get("one_liner") or row.get("reason") or ""
        parts.extend(
            [
                f"### {index}. {row['title']}",
                "",
                str(summary).strip(),
                "",
                f"为什么值得关注：{str(row.get('why_care') or '').strip()}",
                "",
                f"来源：[{row['source_id']}]({row['url']})",
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
    digest = {"headline": "H", "headlines": [{"title": "x", "article_ids": [1], "why_it_matters": "w"}], "sections": []}
    assert "[s](u)" in render_digest_markdown(digest, rows)
    assert len(_fallback_items(rows, 5)[0]["content"]) == 5


if __name__ == "__main__":
    _demo()
