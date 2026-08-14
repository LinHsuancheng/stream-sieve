from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from stream_sieve.cluster import cluster_articles


DIGEST_PROMPT = """You are the editor of a private daily intelligence brief.

Your goal is NOT to summarize every article.
Your goal is to update the reader's world model with the smallest amount of reading possible.

The input contains clusters of articles collected from multiple sources.
Write the final brief in Chinese unless a title or named entity should remain in its original language.

Return JSON only in this exact shape:
{
  "headline": "Daily Brief",
  "highlights": [
    {
      "title": "<event / development>",
      "category": "tech",
      "article_ids": [123],
      "what_changed": "...",
      "why_important": "...",
      "evidence": ["..."],
      "uncertainty": "...",
      "watch_next": "..."
    }
  ],
  "sections": [
    {
      "category": "technology",
      "overview": "...",
      "items": [
        {
          "title": "...",
          "article_ids": [456],
          "what_changed": "...",
          "why_it_matters": "...",
          "evidence": ["..."],
          "uncertainty": "...",
          "watch_next": "...",
          "reading_value": "high|medium|low"
        }
      ]
    }
  ],
  "connections": ["..."]
}

Rules:
- Keep article_ids exactly as provided.
- Use only information supplied in the input. Never invent facts, numbers, names, URLs, or history.
- Determine whether there is actually new information. Do not fill space.
- highlights means the most important few items across the whole brief. It is not fixed to three. Use 0-8 items depending on the input.
- sections must organize the rest by field. Use only these fields: politics, economics, tech, business, cognition, society.
- Each section may contain at most 5 items.
- It is acceptable for a section to be absent if nothing in that field is worth reading today.
- Merge articles describing the same underlying event.
- Prefer primary sources for factual claims.
- Use secondary sources for context, interpretation, or independent confirmation.
- Treat source_meta as a prior: T0/T1 sources can carry evidence; T3 social sources are mainly discovery unless the article itself contains direct evidence.
- Separate facts, interpretation, uncertainty, and disagreement.
- Do not repeat background knowledge unless needed to explain what changed.
- Explicitly identify what is NEW compared with the previous known state when possible.
- If sources disagree, describe the disagreement instead of averaging them.
- Prefer concrete numbers, decisions, releases, policy changes, research results, and structural changes over commentary and generic opinions.

Field-specific editorial judgment:
- politics: emphasize policy decisions, regulation, institutions, elections, geopolitics, power shifts, credible reporting, and likely consequences.
- economics: emphasize macro data, monetary/fiscal policy, inflation, employment, debt, trade, financial stability, and market-moving changes.
- tech: emphasize AI, software, hardware, infrastructure, research results, product releases, open-source systems, and engineering changes.
- business: emphasize company strategy, financing, competition, pricing, distribution, earnings, market structure, and business-model changes.
- cognition: timeliness is optional. Emphasize durable ideas, reasoning quality, explanatory power, mental models, learning, judgment, and whether the piece is worth the reader's scarce attention.
- society: reserve for major social news and sharp social conflicts, especially gender conflict, family/paternity disputes, judicial unfairness toward men, institutional injustice, education, employment, public safety, and issues that reveal meaningful social tension.
- social/X/YouTube items can appear when they are high-signal, but avoid treating them as factual evidence unless the supplied item itself contains direct evidence.
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

    highlights = digest.get("highlights") or digest.get("key_signals") or []
    if highlights:
        parts.extend(["## Highlights", ""])
        for item in highlights:
            title = str(item.get("title") or "").strip()
            parts.extend([f"### {title}", ""])
            for label, key in [
                ("What changed", "what_changed"),
                ("Why important", "why_important"),
                ("Evidence", "evidence"),
                ("Uncertainty", "uncertainty"),
                ("Watch next", "watch_next"),
            ]:
                value = item.get(key) or (item.get("why_it_matters") if key == "why_important" else None)
                if not value:
                    continue
                parts.append(f"**{label}**")
                if isinstance(value, list):
                    for entry in value:
                        parts.append(f"- {entry}")
                else:
                    parts.append(str(value).strip())
                parts.append("")
            refs = article_links(item.get("article_ids"), by_id)
            if refs:
                parts.extend([f"Sources: {refs}", ""])

    sections = digest.get("sections") or []
    for section in sections:
        topic = str(section.get("category") or section.get("topic") or "Other").strip()
        overview = str(section.get("overview") or "").strip()
        parts.extend([f"## {topic}", ""])
        if overview:
            parts.extend([overview, ""])
        for item in (section.get("items") or [])[:5]:
            title = str(item.get("title") or "").strip()
            parts.extend([f"### {title}", ""])
            what = str(item.get("what_changed") or item.get("what_happened") or "").strip()
            why = str(item.get("why_it_matters") or "").strip()
            if what:
                parts.extend(["**What changed**", what, ""])
            if why:
                parts.extend(["**Why it matters**", why, ""])
            evidence = item.get("evidence")
            if evidence:
                parts.append("**Evidence**")
                if isinstance(evidence, list):
                    for entry in evidence:
                        parts.append(f"- {entry}")
                else:
                    parts.append(str(evidence).strip())
                parts.append("")
            if item.get("uncertainty"):
                parts.extend(["**Uncertainty**", str(item["uncertainty"]).strip(), ""])
            if item.get("watch_next"):
                parts.extend(["**Watch next**", str(item["watch_next"]).strip(), ""])
            if item.get("reading_value"):
                parts.extend([f"Reading value: {item['reading_value']}", ""])
            refs = article_links(item.get("article_ids"), by_id)
            if refs:
                parts.extend([f"Sources: {refs}", ""])

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
    digest = {"headline": "H", "key_signals": [{"title": "x", "article_ids": [1], "what_changed": "c"}]}
    assert "[s](u)" in render_digest_markdown(digest, rows)
    assert len(_fallback_items(rows, 5)[0]["content"]) == 5


if __name__ == "__main__":
    _demo()
