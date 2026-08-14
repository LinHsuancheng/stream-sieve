from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class WeightedTerm:
    term: str
    weight: int


@dataclass(frozen=True)
class RankedArticle:
    article: dict[str, Any]
    score: int
    matched: list[str]
    ignored: list[str]


def load_interests(path: str = "interests.md") -> tuple[list[WeightedTerm], list[WeightedTerm]]:
    text = Path(path).read_text(encoding="utf-8")
    positive: list[WeightedTerm] = []
    negative: list[WeightedTerm] = []
    section = "positive"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip().lower()
            section = "negative" if name in {"negative", "minus"} else "positive"
            continue
        if not stripped.startswith("-"):
            continue
        term = stripped.lstrip("-").strip()
        if not term:
            continue
        (negative if section == "negative" else positive).append(
            parse_weighted_term(term, -3 if section == "negative" else 2, negative=section == "negative")
        )
    return positive, negative


def rank_articles(rows: list[dict[str, Any]], interests_path: str = "interests.md") -> list[RankedArticle]:
    terms, ignore_terms = load_interests(interests_path)
    ranked = [score_article(row, terms, ignore_terms) for row in rows]
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def score_article(row: dict[str, Any], terms: list[WeightedTerm], ignore_terms: list[WeightedTerm]) -> RankedArticle:
    haystack = f"{row.get('title') or ''}\n{row.get('content') or ''}".lower()
    matched = [term for term in terms if _contains(haystack, term.term)]
    ignored = [term for term in ignore_terms if _contains(haystack, term.term)]
    score = sum(term.weight for term in matched) + sum(term.weight for term in ignored)
    return RankedArticle(
        article=row,
        score=score,
        matched=[term.term for term in matched],
        ignored=[term.term for term in ignored],
    )


def parse_weighted_term(text: str, default_weight: int, negative: bool = False) -> WeightedTerm:
    if ":" in text:
        term, weight = text.rsplit(":", 1)
        try:
            value = int(weight.strip())
            return WeightedTerm(term.strip(), -abs(value) if negative else abs(value))
        except ValueError:
            pass
    return WeightedTerm(text, default_weight)


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
    tmp.write_text("# Positive\n- AI: 5\n- Nvidia\n- privacy\n# Negative\n- gossip: -7\n", encoding="utf-8")
    ranked = rank_articles(rows, str(tmp))
    assert ranked[0].score == 9
    assert ranked[-1].score == -7


if __name__ == "__main__":
    _demo()
