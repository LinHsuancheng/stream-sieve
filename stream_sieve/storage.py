from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from stream_sieve.models import Article, now_iso


DEFAULT_DB = "~/.stream-sieve/stream-sieve.db"


@dataclass(frozen=True)
class SyncStats:
    source_id: str
    discovered: int
    new: int
    extracted: int
    saved: int
    db: str


class FeedStore:
    def __init__(self, path: str = DEFAULT_DB) -> None:
        self.path = str(Path(path).expanduser())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.init()

    def close(self) -> None:
        self.conn.close()

    def init(self) -> None:
        self.conn.executescript(
            """
            create table if not exists source_state (
                source_id text primary key,
                last_success_at text
            );

            create table if not exists articles (
                id integer primary key,
                source_id text not null,
                url text not null,
                title text not null,
                author text,
                published_at text,
                content text not null,
                content_hash text not null,
                first_seen_at text not null,
                fetched_at text not null,
                unique(source_id, url),
                unique(source_id, content_hash)
            );

            create table if not exists article_scores (
                article_id integer primary key,
                relevance real not null,
                importance real not null,
                novelty real not null,
                total_score real not null,
                category text not null,
                reason text not null,
                scorer_model text not null,
                scored_at text not null,
                raw_json text not null,
                foreign key(article_id) references articles(id)
            );

            create table if not exists article_analysis (
                article_id integer primary key,
                one_liner text not null,
                summary text not null,
                key_points_json text not null,
                topics_json text not null,
                entities_json text not null,
                why_care text not null,
                analyzer_model text not null,
                analyzed_at text not null,
                raw_json text not null,
                foreign key(article_id) references articles(id)
            );

            create table if not exists article_deliveries (
                article_id integer not null,
                delivery_key text not null,
                delivered_at text not null,
                primary key(article_id, delivery_key),
                foreign key(article_id) references articles(id)
            );
            """
        )
        self.conn.commit()

    def seen_url(self, source_id: str, url: str) -> bool:
        row = self.conn.execute(
            "select 1 from articles where source_id = ? and url = ? limit 1",
            (source_id, url),
        ).fetchone()
        return row is not None

    def save_article(self, article: Article) -> bool:
        cur = self.conn.execute(
            """
            insert or ignore into articles (
                source_id, url, title, author, published_at, content,
                content_hash, first_seen_at, fetched_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.source_id,
                article.url,
                article.title,
                article.author,
                article.published_at,
                article.content,
                article.content_hash,
                now_iso(),
                article.fetched_at,
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_success(self, source_id: str) -> None:
        self.conn.execute(
            """
            insert into source_state (source_id, last_success_at)
            values (?, ?)
            on conflict(source_id) do update set last_success_at = excluded.last_success_at
            """,
            (source_id, now_iso()),
        )
        self.conn.commit()

    def status(self) -> dict[str, Any]:
        source_count = self.conn.execute("select count(*) from source_state").fetchone()[0]
        article_count = self.conn.execute("select count(*) from articles").fetchone()[0]
        analysis_count = self.conn.execute("select count(*) from article_analysis").fetchone()[0]
        sources = [
            dict(row)
            for row in self.conn.execute(
                """
                select
                    ids.source_id,
                    s.last_success_at,
                    count(a.id) as articles,
                    max(a.first_seen_at) as latest_seen_at
                from (
                    select source_id from source_state
                    union
                    select source_id from articles
                ) ids
                left join source_state s on s.source_id = ids.source_id
                left join articles a on a.source_id = ids.source_id
                group by ids.source_id, s.last_success_at
                order by ids.source_id
                """
            )
        ]
        return {"db": self.path, "sources": source_count, "articles": article_count, "analyses": analysis_count, "by_source": sources}

    def recent_articles(self, source_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        sql = """
            select id, source_id, title, author, published_at, url, first_seen_at, content, length(content) as content_chars
            from articles
        """
        params: list[Any] = []
        if source_id:
            sql += " where source_id = ?"
            params.append(source_id)
        sql += " order by id desc limit ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def unscored_articles(self, source_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            select a.id, a.source_id, a.title, a.author, a.published_at, a.url, a.content, length(a.content) as content_chars
            from articles a
            left join article_scores s on s.article_id = a.id
            where s.article_id is null
        """
        params: list[Any] = []
        if source_id:
            sql += " and a.source_id = ?"
            params.append(source_id)
        sql += " order by a.id desc limit ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def save_scores(self, scores: list[dict[str, Any]], model: str) -> int:
        saved = 0
        for score in scores:
            cur = self.conn.execute(
                """
                insert or replace into article_scores (
                    article_id, relevance, importance, novelty, total_score,
                    category, reason, scorer_model, scored_at, raw_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score["id"],
                    score["relevance"],
                    score["importance"],
                    score["novelty"],
                    score["total_score"],
                    score["category"],
                    score["reason"],
                    model,
                    now_iso(),
                    score["raw_json"],
                ),
            )
            saved += cur.rowcount
        self.conn.commit()
        return saved

    def unanalyzed_articles(
        self,
        source_id: str | None = None,
        min_score: float = 6.5,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        sql = """
            select
                a.id, a.source_id, a.title, a.author, a.published_at, a.url, a.content,
                s.relevance, s.importance, s.novelty, s.total_score,
                s.category, s.reason
            from article_scores s
            join articles a on a.id = s.article_id
            left join article_analysis aa on aa.article_id = a.id
            where s.total_score >= ? and aa.article_id is null
        """
        params: list[Any] = [min_score]
        if source_id:
            sql += " and a.source_id = ?"
            params.append(source_id)
        sql += " order by s.total_score desc, s.scored_at desc limit ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def save_analyses(self, analyses: list[dict[str, Any]], model: str) -> int:
        saved = 0
        for analysis in analyses:
            cur = self.conn.execute(
                """
                insert or replace into article_analysis (
                    article_id, one_liner, summary, key_points_json,
                    topics_json, entities_json, why_care, analyzer_model,
                    analyzed_at, raw_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis["article_id"],
                    analysis["one_liner"],
                    analysis["summary"],
                    json_dumps(analysis["key_points"]),
                    json_dumps(analysis["topics"]),
                    json_dumps(analysis["entities"]),
                    analysis["why_care"],
                    model,
                    now_iso(),
                    analysis["raw_json"],
                ),
            )
            saved += cur.rowcount
        self.conn.commit()
        return saved

    def recent_scores(self, source_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            select
                a.source_id, a.title, a.author, a.published_at, a.url,
                s.relevance, s.importance, s.novelty, s.total_score,
                s.category, s.reason, s.scorer_model, s.scored_at
            from article_scores s
            join articles a on a.id = s.article_id
        """
        params: list[Any] = []
        if source_id:
            sql += " where a.source_id = ?"
            params.append(source_id)
        sql += " order by s.total_score desc, s.scored_at desc limit ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def recent_analyses(self, source_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            select
                a.source_id, a.title, a.author, a.published_at, a.url,
                s.total_score, s.category,
                aa.one_liner, aa.summary, aa.key_points_json,
                aa.topics_json, aa.entities_json, aa.why_care,
                aa.analyzer_model, aa.analyzed_at
            from article_analysis aa
            join articles a on a.id = aa.article_id
            left join article_scores s on s.article_id = a.id
        """
        params: list[Any] = []
        if source_id:
            sql += " where a.source_id = ?"
            params.append(source_id)
        sql += " order by aa.analyzed_at desc limit ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def brief_articles(self, source_id: str | None = None, min_score: float = 7.0, limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            select
                a.id, a.source_id, a.title, a.author, a.published_at, a.url, a.content,
                s.relevance, s.importance, s.novelty, s.total_score,
                s.category, s.reason,
                aa.one_liner, aa.summary, aa.key_points_json,
                aa.topics_json, aa.entities_json, aa.why_care
            from article_scores s
            join articles a on a.id = s.article_id
            left join article_analysis aa on aa.article_id = a.id
            where s.total_score >= ?
        """
        params: list[Any] = [min_score]
        if source_id:
            sql += " and a.source_id = ?"
            params.append(source_id)
        sql += " order by s.total_score desc, s.scored_at desc limit ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def undelivered_brief_articles(
        self,
        source_id: str | None = None,
        min_score: float = 7.0,
        limit: int = 20,
        delivery_key: str = "default",
    ) -> list[dict[str, Any]]:
        sql = """
            select
                a.id, a.source_id, a.title, a.author, a.published_at, a.url, a.content,
                s.relevance, s.importance, s.novelty, s.total_score,
                s.category, s.reason,
                aa.one_liner, aa.summary, aa.key_points_json,
                aa.topics_json, aa.entities_json, aa.why_care
            from article_scores s
            join articles a on a.id = s.article_id
            left join article_analysis aa on aa.article_id = a.id
            left join article_deliveries d on d.article_id = a.id and d.delivery_key = ?
            where s.total_score >= ? and d.article_id is null
        """
        params: list[Any] = [delivery_key, min_score]
        if source_id:
            sql += " and a.source_id = ?"
            params.append(source_id)
        sql += " order by s.total_score desc, s.scored_at desc limit ?"
        params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def mark_delivered(self, rows: list[dict[str, Any]], delivery_key: str = "default") -> int:
        count = 0
        for row in rows:
            cur = self.conn.execute(
                """
                insert or ignore into article_deliveries (article_id, delivery_key, delivered_at)
                values (?, ?, ?)
                """,
                (row["id"], delivery_key, now_iso()),
            )
            count += cur.rowcount
        self.conn.commit()
        return count


def _demo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = FeedStore(str(Path(tmp) / "stream-sieve.db"))
        article = Article(
            source_id="demo",
            url="https://example.com/a",
            title="A",
            content="body",
            fetched_at=now_iso(),
            content_hash="hash-a",
        )
        assert not store.seen_url("demo", article.url)
        assert store.save_article(article)
        assert store.seen_url("demo", article.url)
        assert not store.save_article(article)
        store.mark_success("demo")
        assert store.status()["articles"] == 1
        assert store.recent_articles("demo", 1)[0]["title"] == "A"
        assert store.unscored_articles("demo", 1)[0]["id"] == 1
        store.close()


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


if __name__ == "__main__":
    _demo()
