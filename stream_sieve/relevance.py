from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class RankedArticle:
    article: dict[str, Any]
    score: int
    matched: list[str]
    ignored: list[str]


def load_interests(path: str = "interests.md") -> tuple[list[str], list[str]]:
    text = Path(path).read_text(encoding="utf-8")
    terms: list[str] = []
    ignore: list[str] = []
    in_ignore = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_ignore = stripped.lstrip("#").strip().lower() == "ignore"
            continue
        if not stripped.startswith("-"):
            continue
        term = stripped.lstrip("-").strip()
        if not term:
            continue
        (ignore if in_ignore else terms).append(term)
    return terms, ignore


def rank_articles(rows: list[dict[str, Any]], interests_path: str = "interests.md") -> list[RankedArticle]:
    terms, ignore_terms = load_interests(interests_path)
    ranked = [score_article(row, terms, ignore_terms) for row in rows]
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def score_article(row: dict[str, Any], terms: list[str], ignore_terms: list[str]) -> RankedArticle:
    haystack = f"{row.get('title') or ''}\n{row.get('content') or ''}".lower()
    matched = [term for term in terms if _contains(haystack, term)]
    ignored = [term for term in ignore_terms if _contains(haystack, term)]
    score = len(matched) * 2 - len(ignored) * 3
    return RankedArticle(article=row, score=score, matched=matched, ignored=ignored)


def _contains(haystack: str, term: str) -> bool:
    term = term.lower().strip()
    if not term:
        return False
    if re.search(r"[\u4e00-\u9fff]", term):
        return term in haystack
    return re.search(rf"\b{re.escape(term)}\b", haystack) is not None


def _demo() -> None:
    rows = [{"title": "Nvidia AI", "content": "privacy"}, {"title": "gossip", "content": ""}]
    tmp = Path("/tmp/stream-sieve-interests-demo.md")
    tmp.write_text("# AI\n- AI\n- Nvidia\n- privacy\n# Ignore\n- gossip\n", encoding="utf-8")
    ranked = rank_articles(rows, str(tmp))
    assert ranked[0].score == 6
    assert ranked[-1].score == -3


if __name__ == "__main__":
    _demo()
