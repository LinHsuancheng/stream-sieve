from __future__ import annotations

from datetime import date
from typing import Any

def render_digest_markdown(digest: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    by_id = {int(row["id"]): row for row in rows}
    meta = digest.get("meta") if isinstance(digest.get("meta"), dict) else {}
    title = str(meta.get("title") or digest.get("headline") or "Daily Reading")
    deck = str(meta.get("deck") or digest.get("intro") or "").strip()
    parts = [f"# {title}", "", date.today().isoformat(), ""]

    if deck:
        parts.extend([deck, ""])

    highlights = digest.get("highlights") or []
    sections = digest.get("sections") or []
    present_sections = [section for section in sections if section.get("items")]
    if not highlights and not present_sections and not (digest.get("quick_reads") or digest.get("reading_list")):
        return render_legacy_markdown(rows)

    if highlights:
        parts.extend(["## Highlights", ""])
        for index, item in enumerate(highlights[:12], start=1):
            row = _first_row(item, by_id)
            item_title = str(item.get("title") or row.get("title") or "").strip()
            description = str(item.get("description") or item.get("summary") or item.get("what_changed") or "").strip()
            line = " — ".join(part for part in (item_title, description) if part)
            parts.append(f"{index}. {line}")
            parts.append("")

    if present_sections:
        parts.extend(["## Contents", ""])
        for section in present_sections:
            category = str(section.get("category") or section.get("topic") or "other").strip()
            parts.append(f"- {FIELD_LABELS.get(category, category)}")
        parts.append("")

    for section in sections:
        category = str(section.get("category") or section.get("topic") or "other").strip()
        items = (section.get("items") or [])[:20]
        if not items:
            continue
        parts.extend([f"## {FIELD_LABELS.get(category, category)}", ""])
        for item in items:
            rows_for_item = _rows_for_ids(_item_ids(item), by_id)
            row = rows_for_item[0] if rows_for_item else {}
            item_title = str(item.get("title") or row.get("title") or item.get("dek") or "").strip()
            overview = str(item.get("summary") or item.get("description") or item.get("dek") or row.get("summary") or row.get("one_liner") or "").strip()
            excerpt = _item_content(item).strip()
            parts.extend([f"### {item_title}", "", _article_meta(row), ""])
            if overview:
                parts.extend([f"概括：{overview}", ""])
            if excerpt and excerpt != overview:
                parts.extend([f"正文：{excerpt}", ""])
            refs = article_links(_item_ids(item), by_id)
            if refs:
                parts.extend([refs, ""])
        parts.append("")

    return "\n".join(parts).strip() + "\n"


FIELD_LABELS = {
    "ai_news": "AI News",
    "tech": "Tech",
    "politics-china": "Politics · China",
    "politics-global": "Politics · Global",
    "economy-china": "Economy · China",
    "economy-global": "Economy · Global",
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


def _item_ids(item: dict[str, Any]) -> list[Any]:
    ids = item.get("article_ids")
    if isinstance(ids, list):
        return ids
    article_id = item.get("article_id")
    return [article_id] if article_id is not None else []


def _first_row(item: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    rows = _rows_for_ids(_item_ids(item), by_id)
    return rows[0] if rows else {}


def _item_content(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, list):
        return " ".join(str(part).strip() for part in content if str(part).strip())
    return str(content or item.get("dek") or "").strip()


def _referenced_ids(digest: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for item in digest.get("highlights") or []:
        ids.update(int(value) for value in _item_ids(item) if str(value).isdigit())
    for section in digest.get("sections") or []:
        for item in section.get("items") or []:
            ids.update(int(value) for value in _item_ids(item) if str(value).isdigit())
    for item in digest.get("quick_reads") or []:
        ids.update(int(value) for value in _item_ids(item) if str(value).isdigit())
    ids.update(int(value) for value in digest.get("reading_list") or [] if str(value).isdigit())
    return ids


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


def _demo() -> None:
    rows = [{"id": 1, "title": "T", "source_id": "s", "author": "a", "url": "u", "total_score": 8, "content": "hello " * 10}]
    digest = {
        "headline": "H",
        "highlights": [{"title": "x", "article_ids": [1], "description": "d"}],
        "sections": [{"category": "tech", "items": [{"title": "T", "article_ids": [1], "summary": "s"}]}],
    }
    assert "[s](u)" in render_digest_markdown(digest, rows)
    assert "Why it matters" not in render_digest_markdown(digest, rows)


if __name__ == "__main__":
    _demo()
