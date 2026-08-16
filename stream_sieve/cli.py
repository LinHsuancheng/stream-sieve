from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import httpx
import yaml

from stream_sieve.analyze import analyze_batch
from stream_sieve.browser.linux_chrome_cdp import LinuxChromeCdpBackend
from stream_sieve.delivery.config import deliver, load_delivery
from stream_sieve.digest import render_digest_markdown, synthesize_digest
from stream_sieve.llm_scorer import DEFAULT_BASE_URL, DEFAULT_MODEL, build_prompt, score_batch, total_score
from stream_sieve.pipeline import article_markdown, acquire, discover, extract_article, load_source, run_once, sync_source, sync_sources
from stream_sieve.relevance import rank_articles
from stream_sieve.render.html import markdown_to_html, render_digest_html
from stream_sieve.source_pool import DEFAULT_SOURCE_POOL, enrich_rows, load_source_pool
from stream_sieve.storage import DEFAULT_DB, FeedStore


def print_limited(text: str, max_chars: int) -> None:
    if len(text) <= max_chars:
        print(text)
        return
    print(text[:max_chars])
    print()
    print(f"[truncated: {len(text) - max_chars} characters omitted]")


def command_browser_inspect(args: argparse.Namespace) -> int:
    backend = LinuxChromeCdpBackend(
        session=args.session,
        cdp_endpoint=args.cdp_endpoint,
    )

    print("Browser: Linux Chrome CDP")
    print(f"Session: {args.session}")
    print(f"CDP endpoint: {args.cdp_endpoint}")
    print(f"URL: {args.url}")
    print()

    attach = backend.attach()
    print("[OK] attach" if attach.ok else "[FAIL] attach")
    print_limited(attach.output, args.status_chars)
    print()
    if not attach.ok:
        return attach.code

    if args.url:
        goto = backend.goto(args.url)
        print("[OK] goto" if goto.ok else "[FAIL] goto")
        print_limited(goto.output, args.status_chars)
        print()
        if not goto.ok:
            return goto.code

    if args.wait > 0:
        print(f"Waiting {args.wait:g}s before content read...")
        time.sleep(args.wait)

    scroll_results = backend.scroll(args.scroll, args.scroll_delta, args.scroll_wait)
    for index, result in enumerate(scroll_results, start=1):
        print(f"[OK] scroll {index}" if result.ok else f"[FAIL] scroll {index}")
        print_limited(result.output, args.status_chars)
        print()
        if not result.ok:
            return result.code

    if args.content == "snapshot":
        content = backend.snapshot()
    elif args.content == "text":
        content = backend.text()
    else:
        content = backend.html()

    print("[OK] read content" if content.ok else "[FAIL] read content")
    if not content.ok:
        print_limited(content.output, args.max_chars)
        return content.code

    print_limited(content.output, args.max_chars)
    print()
    print("Document received successfully.")
    return 0


def command_discover(args: argparse.Namespace) -> int:
    source = load_source(args.source)
    for ref in discover(source)[: args.limit or None]:
        print(ref.to_json())
    return 0


def command_extract(args: argparse.Namespace) -> int:
    source = load_source(args.source)
    refs = discover(source)
    if not refs:
        print("No items discovered.", file=sys.stderr)
        return 1
    ref = refs[args.index]
    raw = acquire(source, ref)
    article = extract_article(source, raw, title=ref.title)
    print(article.to_json() if args.json else article_markdown([article]))
    return 0


def command_run_once(args: argparse.Namespace) -> int:
    source = load_source(args.source)
    articles = run_once(source, args.limit)
    output = "\n".join(article.to_json() for article in articles) if args.json else article_markdown(articles)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(args.output)
    else:
        print(output)
    return 0


def command_sync(args: argparse.Namespace) -> int:
    source = load_source(args.source)
    if args.cdp_endpoint:
        source.setdefault("browser", {})["cdp_endpoint"] = args.cdp_endpoint
    stats, articles = sync_source(source, args.limit, args.db)
    print(f"source: {stats.source_id}")
    print(f"db: {stats.db}")
    print(f"discovered: {stats.discovered}")
    print(f"new: {stats.new}")
    print(f"extracted: {stats.extracted}")
    print(f"saved: {stats.saved}")
    if args.output:
        Path(args.output).write_text(article_markdown(articles), encoding="utf-8")
        print(f"output: {args.output}")
    return 0


def command_run_source(args: argparse.Namespace) -> int:
    source_path = resolve_source_path(args.source, args.sources_dir)
    source = load_source(source_path)
    if args.cdp_endpoint:
        source.setdefault("browser", {})["cdp_endpoint"] = args.cdp_endpoint
    stats, articles = sync_source(source, args.limit, args.db)
    print(f"source: {stats.source_id}")
    print(f"source_file: {source_path}")
    print(f"db: {stats.db}")
    print(f"discovered: {stats.discovered}")
    print(f"new: {stats.new}")
    print(f"extracted: {stats.extracted}")
    print(f"saved: {stats.saved}")
    if args.output:
        Path(args.output).write_text(article_markdown(articles), encoding="utf-8")
        print(f"output: {args.output}")
    return 0


def resolve_source_path(name: str, sources_dir: str) -> Path:
    root = Path(sources_dir)
    direct = root / (name if name.endswith(".yaml") else f"{name}.yaml")
    if direct.is_file():
        return direct
    wanted = name.casefold()
    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if str(data.get("id", "")).casefold() == wanted or str(data.get("name", "")).casefold() == wanted:
            return path
    raise SystemExit(f"source not found: {name} (looked in {root})")


def command_sync_many(args: argparse.Namespace) -> int:
    pairs = []
    for spec in args.source:
        if ":" in spec:
            path, limit_text = spec.rsplit(":", 1)
            limit = int(limit_text)
        else:
            path = spec
            limit = args.limit
        source = load_source(path)
        if args.cdp_endpoint:
            source.setdefault("browser", {})["cdp_endpoint"] = args.cdp_endpoint
        pairs.append((source, limit))

    results = sync_sources(pairs, args.db, progress=lambda msg: print(msg, flush=True))
    all_articles = []
    for stats, articles in results:
        all_articles.extend(articles)
        print(f"source: {stats.source_id}", flush=True)
        print(f"db: {stats.db}", flush=True)
        print(f"discovered: {stats.discovered}", flush=True)
        print(f"new: {stats.new}", flush=True)
        print(f"extracted: {stats.extracted}", flush=True)
        print(f"saved: {stats.saved}", flush=True)
        print(flush=True)
    if args.output:
        Path(args.output).write_text(article_markdown(all_articles), encoding="utf-8")
        print(f"output: {args.output}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    store = FeedStore(args.db)
    try:
        status = store.status()
    finally:
        store.close()
    print(f"db: {status['db']}")
    print(f"sources: {status['sources']}")
    print(f"articles: {status['articles']}")
    print(f"analyses: {status['analyses']}")
    for row in status["by_source"]:
        print()
        print(row["source_id"])
        print(f"  articles: {row['articles']}")
        print(f"  last_success_at: {row['last_success_at'] or ''}")
        print(f"  latest_seen_at: {row['latest_seen_at'] or ''}")
    return 0


def command_articles(args: argparse.Namespace) -> int:
    store = FeedStore(args.db)
    try:
        rows = store.recent_articles(args.source, args.limit)
    finally:
        store.close()
    for row in rows:
        print(f"title: {row['title']}")
        print(f"source: {row['source_id']}")
        print(f"author: {row['author'] or ''}")
        print(f"published_at: {row['published_at'] or ''}")
        print(f"first_seen_at: {row['first_seen_at']}")
        print(f"content_chars: {row['content_chars']}")
        print(f"url: {row['url']}")
        print()
    return 0


def command_rank(args: argparse.Namespace) -> int:
    store = FeedStore(args.db)
    try:
        rows = store.recent_articles(args.source, args.scan_limit)
    finally:
        store.close()
    for item in rank_articles(rows, args.interests)[: args.limit]:
        row = item.article
        if item.score < args.min_score:
            continue
        print(f"score: {item.score}")
        print(f"title: {row['title']}")
        print(f"source: {row['source_id']}")
        print(f"author: {row['author'] or ''}")
        print(f"published_at: {row['published_at'] or ''}")
        print(f"matched: {', '.join(item.matched)}")
        print(f"ignored: {', '.join(item.ignored)}")
        print(f"url: {row['url']}")
        print()
    return 0


def command_score(args: argparse.Namespace) -> int:
    interests = args.field_profile or Path(args.interests).read_text(encoding="utf-8")
    source_pool = load_source_pool(args.source_pool)
    model = args.model or DEFAULT_MODEL
    store = FeedStore(args.db)
    try:
        rows = store.unscored_articles(args.source, args.prefilter_scan_limit or args.limit, parse_csv(args.source_ids))
        rows = enrich_rows(rows, source_pool)
        ignored_scores = []
        if args.prefilter_min_score is not None:
            ranked = rank_articles(rows, args.interests, interests)
            rows = [item.article for item in ranked if item.score >= args.prefilter_min_score][: args.limit]
            ignored_scores = [
                local_prefilter_score(item.article, item.score)
                for item in ranked
                if item.score < args.prefilter_min_score
            ]
        else:
            rows = rows[: args.limit]
        if args.dry_run:
            print(build_prompt(rows, interests, args.sample_chars, parse_csv(args.categories), field_context(args)))
            return 0
        ignored = store.save_scores(ignored_scores, model) if ignored_scores else 0
        if not rows:
            print("articles: 0")
            print(f"prefilter_ignored: {ignored}")
            print("scores_saved: 0")
            return 0
        scores = []
        saved = 0
        skipped_batches = 0
        for batch in chunks(rows, args.batch_size):
            try:
                batch_scores = score_batch(
                    batch,
                    interests,
                    model=model,
                    base_url=args.base_url,
                    sample_chars=args.sample_chars,
                    categories=parse_csv(args.categories),
                    field_context=field_context(args),
                    nonthink=args.nonthink,
                    timeout=args.timeout,
                    retries=args.retries,
                )
            except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                skipped_batches += 1
                ids = ",".join(str(row["id"]) for row in batch)
                print(f"score batch skipped: ids={ids}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            for score in batch_scores:
                score["total_score"] = total_score(score)
                score["raw_json"] = json.dumps(score, ensure_ascii=False)
            saved += store.save_scores(batch_scores, model)
            scores.extend(batch_scores)
    finally:
        store.close()
    print(f"model: {model}")
    print(f"articles: {len(rows)}")
    print(f"prefilter_ignored: {ignored}")
    print(f"batches_skipped: {skipped_batches}")
    print(f"scores_saved: {saved}")
    for score in sorted(scores, key=lambda item: item["total_score"], reverse=True):
        row = next((row for row in rows if row["id"] == score["id"]), {})
        title = row.get("title", "")
        print()
        print(f"score: {score['total_score']}")
        print(f"title: {title}")
        print(f"source: {row.get('source_id', '')}")
        print(f"personal_relevance: {score['relevance']}")
        print(f"information_value: {score['importance']}")
        print(f"timeliness: {score['novelty']}")
        print(f"category: {score['category']}")
        print(f"reason: {score['reason']}")
        print(f"url: {row.get('url', '')}")
    return 0


def chunks(items: list[dict[str, object]], size: int) -> list[list[dict[str, object]]]:
    size = max(1, size)
    return [items[index : index + size] for index in range(0, len(items), size)]


def local_prefilter_score(row: dict[str, object], score: int) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "relevance": 0,
        "importance": 0,
        "novelty": 0,
        "total_score": 0,
        "category": "other",
        "reason": f"local prefilter score {score} below threshold",
        "raw_json": json.dumps({"id": row["id"], "local_prefilter_score": score}, ensure_ascii=False),
    }


def command_scores(args: argparse.Namespace) -> int:
    store = FeedStore(args.db)
    try:
        rows = store.recent_scores(args.source, args.limit)
    finally:
        store.close()
    for row in rows:
        print(f"score: {row['total_score']}")
        print(f"title: {row['title']}")
        print(f"source: {row['source_id']}")
        print(f"category: {row['category']}")
        print(f"personal_relevance: {row['relevance']}")
        print(f"information_value: {row['importance']}")
        print(f"timeliness: {row['novelty']}")
        print(f"reason: {row['reason']}")
        print(f"url: {row['url']}")
        print()
    return 0


def command_analyze(args: argparse.Namespace) -> int:
    model = args.model or DEFAULT_MODEL
    source_pool = load_source_pool(args.source_pool)
    store = FeedStore(args.db)
    try:
        rows = store.unanalyzed_articles(args.source, args.min_score, args.limit, parse_csv(args.source_ids))
        rows = enrich_rows(rows, source_pool)
        if args.dry_run:
            for row in rows:
                print(f"id: {row['id']}")
                print(f"title: {row['title']}")
                print(f"score: {row['total_score']}")
                print()
            return 0
        if not rows:
            print("articles: 0")
            print("analyses_saved: 0")
            return 0
        saved = 0
        skipped_batches = 0
        analyses = []
        for batch in chunks(rows, args.batch_size):
            try:
                batch_analyses = analyze_batch(
                    batch,
                    model=model,
                    base_url=args.base_url or DEFAULT_BASE_URL,
                    content_chars=args.content_chars,
                    nonthink=args.nonthink,
                    timeout=args.timeout,
                    retries=args.retries,
                )
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                skipped_batches += 1
                ids = ",".join(str(row["id"]) for row in batch)
                print(f"analysis batch skipped: ids={ids}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            saved += store.save_analyses(batch_analyses, model)
            analyses.extend(batch_analyses)
    finally:
        store.close()
    print(f"model: {model}")
    print(f"articles: {len(rows)}")
    print(f"batches_skipped: {skipped_batches}")
    print(f"analyses_saved: {saved}")
    for analysis in analyses:
        print()
        print(f"id: {analysis['article_id']}")
        print(f"one_liner: {analysis['one_liner']}")
        print(f"topics: {', '.join(analysis['topics'])}")
        print(f"why_care: {analysis['why_care']}")
    return 0


def command_analyses(args: argparse.Namespace) -> int:
    store = FeedStore(args.db)
    try:
        rows = store.recent_analyses(args.source, args.limit)
    finally:
        store.close()
    for row in rows:
        print(f"title: {row['title']}")
        print(f"source: {row['source_id']}")
        print(f"score: {row['total_score'] or ''}")
        print(f"category: {row['category'] or ''}")
        print(f"one_liner: {row['one_liner']}")
        print(f"topics: {row['topics_json']}")
        print(f"entities: {row['entities_json']}")
        print(f"why_care: {row['why_care']}")
        print(f"url: {row['url']}")
        print()
    return 0


def command_brief(args: argparse.Namespace) -> int:
    source_pool = load_source_pool(args.source_pool)
    store = FeedStore(args.db)
    try:
        if args.delivery_key:
            rows = store.undelivered_brief_articles(args.source, args.min_score, 500, args.delivery_key, parse_csv(args.source_ids))
        else:
            rows = store.brief_articles(args.source, args.min_score, 500, parse_csv(args.source_ids))
        rows = enrich_rows(rows, source_pool)
        rows = select_field_limits(rows, args.field_limits, args.limit)
        if not args.field_limits:
            rows = select_category_limits(rows, args.category_limits, args.limit)
    finally:
        store.close()
    try:
        digest = build_digest(rows, args)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        print(
            f"brief synthesis skipped: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        digest = {
            "headline": "Daily Reading",
            "intro": "AI 摘要生成失败，以下为本次筛选出的文章。",
            "highlights": [],
            "sections": [],
        }
    output = render_digest_markdown(digest, rows)
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(output, encoding="utf-8")
        output_path.with_suffix(".json").write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(args.output)
    else:
        print(output)
    return 0


def command_send(args: argparse.Namespace) -> int:
    delivery_key = args.delivery_key or args.config
    source_pool = load_source_pool(args.source_pool)
    store = FeedStore(args.db)
    try:
        if args.resend:
            rows = store.brief_articles(args.source, args.min_score, 500, parse_csv(args.source_ids))
        else:
            rows = store.undelivered_brief_articles(args.source, args.min_score, 500, delivery_key, parse_csv(args.source_ids))
        rows = enrich_rows(rows, source_pool)
        rows = select_field_limits(rows, args.field_limits, args.limit)
        if not args.field_limits:
            rows = select_category_limits(rows, args.category_limits, args.limit)
        if not rows:
            print("delivered: skipped")
            print("reason: no undelivered scored articles matched the threshold")
            return 0
        if args.body_file:
            text = Path(args.body_file).read_text(encoding="utf-8")
            digest = read_digest_json(args.body_file)
            html = render_digest_html(digest, rows) if digest else markdown_to_html(text)
        elif args.no_synthesis:
            digest = build_local_digest(rows)
            text = render_digest_markdown(digest, rows)
            html = render_digest_html(digest, rows)
        else:
            digest = build_digest(rows, args)
            text = render_digest_markdown(digest, rows)
            html = render_digest_html(digest, rows)
        config = load_delivery(args.config)
        delivery_attempts = 10
        delivery_retry_wait = 60
        delivery_error = None
        for attempt in range(1, delivery_attempts + 1):
            try:
                result = deliver(config, args.subject, html, text)
                delivery_error = None
                break
            except Exception as exc:
                delivery_error = exc
                print(
                    f"delivery attempt {attempt}/{delivery_attempts} failed: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                if attempt < delivery_attempts:
                    print(
                        f"retrying delivery in {delivery_retry_wait}s",
                        file=sys.stderr,
                    )
                    time.sleep(delivery_retry_wait)
        if delivery_error is not None:
            print("delivered: failed")
            print(f"attempts: {delivery_attempts}")
            print("marked_delivered: 0")
            return 0
        marked = 0 if args.resend else store.mark_delivered(rows, delivery_key)
    finally:
        store.close()
    print(f"delivered: {result}")
    print(f"articles: {len(rows)}")
    print(f"marked_delivered: {marked}")
    return 0


def digest_markdown(rows: list[dict[str, object]], args: argparse.Namespace) -> str:
    return render_digest_markdown(build_digest(rows, args), rows)


def build_digest(rows: list[dict[str, object]], args: argparse.Namespace) -> dict[str, object]:
    if not rows:
        return {"headline": "Daily Reading", "intro": "No scored articles matched the threshold.", "highlights": [], "sections": []}
    return synthesize_digest(
        rows,
        model=args.model or DEFAULT_MODEL,
        base_url=args.base_url or DEFAULT_BASE_URL,
        content_chars=args.excerpt_chars,
        nonthink=args.nonthink,
        timeout=args.timeout,
        retries=args.retries,
    )


def build_local_digest(rows: list[dict[str, object]]) -> dict[str, object]:
    """Build a complete deterministic report from saved scores/analyses.

    This is intentionally LLM-free: it is useful for resending a report after
    renderer changes without re-fetching, rescoring, or consuming synthesis
    tokens.
    """
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        category = str(row.get("category") or "other")
        grouped.setdefault(category, []).append(row)
    sections = []
    for category, category_rows in grouped.items():
        items = []
        for row in category_rows[:20]:
            summary = str(row.get("summary") or row.get("one_liner") or row.get("reason") or "").strip()
            items.append({"article_id": row["id"], "dek": summary, "content": [summary] if summary else []})
        sections.append({"category": category, "note": "Saved score and analysis results.", "items": items})
    highlights = []
    for row in rows[:8]:
        summary = str(row.get("summary") or row.get("one_liner") or row.get("reason") or "").strip()
        highlights.append({"article_id": row["id"], "summary": summary})
    return {
        "meta": {"title": "Stream Sieve Daily Brief", "deck": "Based on the completed saved selection; no new model synthesis was run."},
        "highlights": highlights,
        "sections": sections,
    }


def read_digest_json(body_file: str) -> dict[str, object] | None:
    path = Path(body_file).with_suffix(".json")
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def field_context(args: argparse.Namespace) -> dict[str, object] | None:
    if not getattr(args, "field", None):
        return None
    return {
        "field": args.field,
        "mode": getattr(args, "field_mode", None),
        "horizon": getattr(args, "field_horizon", None),
    }


def select_category_limits(rows: list[dict[str, object]], spec: str | None, limit: int) -> list[dict[str, object]]:
    if not spec:
        return rows[:limit]
    limits = json.loads(spec)
    selected: list[dict[str, object]] = []
    used: set[int] = set()
    for category, count in limits.items():
        for row in rows:
            if len([item for item in selected if item.get("category") == category]) >= int(count):
                break
            if int(row["id"]) not in used and row.get("category") == category:
                selected.append(row)
                used.add(int(row["id"]))
    for row in rows:
        if len(selected) >= limit:
            break
        if int(row["id"]) not in used:
            selected.append(row)
            used.add(int(row["id"]))
    return selected[:limit]


def select_field_limits(rows: list[dict[str, object]], spec: str | None, limit: int) -> list[dict[str, object]]:
    if not spec:
        return rows[:limit]
    limits = json.loads(spec)
    selected: list[dict[str, object]] = []
    used: set[int] = set()
    for field, count in limits.items():
        for row in rows:
            source_meta = row.get("source_meta") if isinstance(row.get("source_meta"), dict) else {}
            categories = source_meta.get("briefing_categories") or [source_meta.get("briefing_category")]
            if field not in categories:
                continue
            if len([
                item for item in selected
                if field in ((item.get("source_meta") or {}).get("briefing_categories") or [(item.get("source_meta") or {}).get("briefing_category")])
            ]) >= int(count):
                break
            if int(row["id"]) not in used:
                selected.append(row)
                used.add(int(row["id"]))
    return selected[:limit]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stream-sieve", description="Stream Sieve CLI.")
    subparsers = parser.add_subparsers(dest="command")

    browser = subparsers.add_parser("browser", help="Browser backend utilities.")
    browser_subparsers = browser.add_subparsers(dest="browser_command")

    inspect = browser_subparsers.add_parser(
        "inspect",
        help="Attach to Linux Chrome over CDP, navigate, optionally scroll, and read rendered content.",
    )
    inspect.add_argument("--url", default="https://www.zhihu.com")
    inspect.add_argument("--session", default="chrome-main")
    inspect.add_argument("--cdp-endpoint", default="http://127.0.0.1:9222")
    inspect.add_argument("--content", choices=("snapshot", "text", "html"), default="snapshot")
    inspect.add_argument("--wait", type=float, default=0)
    inspect.add_argument("--scroll", type=int, default=0)
    inspect.add_argument("--scroll-delta", type=int, default=1400)
    inspect.add_argument("--scroll-wait", type=float, default=2)
    inspect.add_argument("--max-chars", type=int, default=12000)
    inspect.add_argument("--status-chars", type=int, default=4000)
    inspect.set_defaults(func=command_browser_inspect)

    discover_cmd = subparsers.add_parser("discover", help="Discover ItemRef entries from a source YAML.")
    discover_cmd.add_argument("source")
    discover_cmd.add_argument("--limit", type=int, default=20)
    discover_cmd.set_defaults(func=command_discover)

    extract_cmd = subparsers.add_parser("extract", help="Discover one item, acquire it, and extract Article content.")
    extract_cmd.add_argument("source")
    extract_cmd.add_argument("--index", type=int, default=0)
    extract_cmd.add_argument("--json", action="store_true")
    extract_cmd.set_defaults(func=command_extract)

    run_once_cmd = subparsers.add_parser("run-once", help="Discover/acquire/extract a few items and print markdown.")
    run_once_cmd.add_argument("source")
    run_once_cmd.add_argument("--limit", type=int, default=3)
    run_once_cmd.add_argument("--json", action="store_true")
    run_once_cmd.add_argument("--output", default=None)
    run_once_cmd.set_defaults(func=command_run_once)

    sync_cmd = subparsers.add_parser("sync", help="Discover/acquire/extract only unseen items and save them to SQLite.")
    sync_cmd.add_argument("source")
    sync_cmd.add_argument("--limit", type=int, default=3)
    sync_cmd.add_argument("--db", default=DEFAULT_DB)
    sync_cmd.add_argument("--cdp-endpoint", default=None)
    sync_cmd.add_argument("--output", default=None)
    sync_cmd.set_defaults(func=command_sync)

    run_source_cmd = subparsers.add_parser("run-source", help="Run one source by ID or display name.")
    run_source_cmd.add_argument("source", help="Source ID, source display name, or YAML filename.")
    run_source_cmd.add_argument("--sources-dir", default="sources")
    run_source_cmd.add_argument("--limit", type=int, default=3)
    run_source_cmd.add_argument("--db", default=DEFAULT_DB)
    run_source_cmd.add_argument("--cdp-endpoint", default=None)
    run_source_cmd.add_argument("--output", default=None)
    run_source_cmd.set_defaults(func=command_run_source)

    sync_many_cmd = subparsers.add_parser("sync-many", help="Sync multiple browser sources with one browser attach/tab.")
    sync_many_cmd.add_argument("source", nargs="+", help="Source YAML path, optionally PATH:LIMIT.")
    sync_many_cmd.add_argument("--limit", type=int, default=3)
    sync_many_cmd.add_argument("--db", default=DEFAULT_DB)
    sync_many_cmd.add_argument("--cdp-endpoint", default=None)
    sync_many_cmd.add_argument("--output", default=None)
    sync_many_cmd.set_defaults(func=command_sync_many)

    sieve_cmd = subparsers.add_parser(
        "sieve",
        help="Collect and persist content for later scoring, analysis, and delivery.",
    )
    sieve_cmd.add_argument("source", nargs="+", help="Source YAML path, optionally PATH:LIMIT.")
    sieve_cmd.add_argument("--limit", type=int, default=3)
    sieve_cmd.add_argument("--db", default=DEFAULT_DB)
    sieve_cmd.add_argument("--cdp-endpoint", default=None)
    sieve_cmd.add_argument("--output", default=None)
    sieve_cmd.set_defaults(func=command_sync_many)

    status_cmd = subparsers.add_parser("status", help="Show SQLite feed status.")
    status_cmd.add_argument("--db", default=DEFAULT_DB)
    status_cmd.set_defaults(func=command_status)

    articles_cmd = subparsers.add_parser("articles", help="List recently saved articles.")
    articles_cmd.add_argument("--db", default=DEFAULT_DB)
    articles_cmd.add_argument("--source", default=None)
    articles_cmd.add_argument("--limit", type=int, default=10)
    articles_cmd.set_defaults(func=command_articles)

    rank_cmd = subparsers.add_parser("rank", help="Rank saved articles with local interests.md keywords.")
    rank_cmd.add_argument("--db", default=DEFAULT_DB)
    rank_cmd.add_argument("--source", default=None)
    rank_cmd.add_argument("--interests", default="interests.md")
    rank_cmd.add_argument("--limit", type=int, default=10)
    rank_cmd.add_argument("--scan-limit", type=int, default=100)
    rank_cmd.add_argument("--min-score", type=int, default=-999)
    rank_cmd.set_defaults(func=command_rank)

    score_cmd = subparsers.add_parser("score", help="Score unscored articles with an OpenAI-compatible LLM.")
    score_cmd.add_argument("--db", default=DEFAULT_DB)
    score_cmd.add_argument("--source", default=None)
    score_cmd.add_argument("--source-ids", default=None)
    score_cmd.add_argument("--field", default=None)
    score_cmd.add_argument("--field-mode", default=None)
    score_cmd.add_argument("--field-horizon", default=None)
    score_cmd.add_argument("--field-profile", default=None)
    score_cmd.add_argument("--interests", default="interests.md")
    score_cmd.add_argument("--limit", type=int, default=10)
    score_cmd.add_argument("--prefilter-scan-limit", type=int, default=None)
    score_cmd.add_argument("--prefilter-min-score", type=int, default=None)
    score_cmd.add_argument("--model", default=None)
    score_cmd.add_argument("--base-url", default=None)
    score_cmd.add_argument("--sample-chars", type=int, default=50)
    score_cmd.add_argument("--categories", default=None)
    add_source_pool_arg(score_cmd)
    score_cmd.add_argument("--excerpt-chars", type=int, default=None, help=argparse.SUPPRESS)
    score_cmd.add_argument("--text-snippets", type=int, default=None, help=argparse.SUPPRESS)
    score_cmd.add_argument("--snippet-chars", type=int, default=None, help=argparse.SUPPRESS)
    score_cmd.add_argument("--nonthink", action="store_true")
    score_cmd.add_argument("--batch-size", type=int, default=3)
    score_cmd.add_argument("--timeout", type=float, default=180)
    score_cmd.add_argument("--retries", type=int, default=1)
    score_cmd.add_argument("--dry-run", action="store_true")
    score_cmd.set_defaults(func=command_score)

    scores_cmd = subparsers.add_parser("scores", help="List saved LLM scores.")
    scores_cmd.add_argument("--db", default=DEFAULT_DB)
    scores_cmd.add_argument("--source", default=None)
    scores_cmd.add_argument("--limit", type=int, default=20)
    scores_cmd.set_defaults(func=command_scores)

    analyze_cmd = subparsers.add_parser("analyze", help="Analyze high-scored articles into structured briefing notes.")
    analyze_cmd.add_argument("--db", default=DEFAULT_DB)
    analyze_cmd.add_argument("--source", default=None)
    analyze_cmd.add_argument("--source-ids", default=None)
    analyze_cmd.add_argument("--min-score", type=float, default=6.5)
    analyze_cmd.add_argument("--limit", type=int, default=20)
    analyze_cmd.add_argument("--model", default=None)
    analyze_cmd.add_argument("--base-url", default=None)
    analyze_cmd.add_argument("--content-chars", type=int, default=4000)
    add_source_pool_arg(analyze_cmd)
    analyze_cmd.add_argument("--batch-size", type=int, default=5)
    analyze_cmd.add_argument("--nonthink", action="store_true")
    analyze_cmd.add_argument("--timeout", type=float, default=180)
    analyze_cmd.add_argument("--retries", type=int, default=1)
    analyze_cmd.add_argument("--dry-run", action="store_true")
    analyze_cmd.set_defaults(func=command_analyze)

    analyses_cmd = subparsers.add_parser("analyses", help="List saved structured article analyses.")
    analyses_cmd.add_argument("--db", default=DEFAULT_DB)
    analyses_cmd.add_argument("--source", default=None)
    analyses_cmd.add_argument("--limit", type=int, default=20)
    analyses_cmd.set_defaults(func=command_analyses)

    brief_cmd = subparsers.add_parser("brief", help="Print a markdown briefing from high-scored articles.")
    brief_cmd.add_argument("--db", default=DEFAULT_DB)
    brief_cmd.add_argument("--source", default=None)
    brief_cmd.add_argument("--source-ids", default=None)
    brief_cmd.add_argument("--min-score", type=float, default=7.0)
    brief_cmd.add_argument("--limit", type=int, default=20)
    brief_cmd.add_argument("--excerpt-chars", type=int, default=700)
    brief_cmd.add_argument("--model", default=None)
    brief_cmd.add_argument("--base-url", default=None)
    brief_cmd.add_argument("--nonthink", action="store_true")
    brief_cmd.add_argument("--timeout", type=float, default=180)
    brief_cmd.add_argument("--retries", type=int, default=1)
    brief_cmd.add_argument("--delivery-key", default=None)
    brief_cmd.add_argument("--category-limits", default=None)
    brief_cmd.add_argument("--field-limits", default=None)
    add_source_pool_arg(brief_cmd)
    brief_cmd.add_argument("--output", default=None)
    brief_cmd.set_defaults(func=command_brief)

    send_cmd = subparsers.add_parser("send", help="Render high-scored articles and deliver them.")
    send_cmd.add_argument("--config", default="configs/delivery.example.yaml")
    send_cmd.add_argument("--db", default=DEFAULT_DB)
    send_cmd.add_argument("--source", default=None)
    send_cmd.add_argument("--source-ids", default=None)
    send_cmd.add_argument("--min-score", type=float, default=7.0)
    send_cmd.add_argument("--limit", type=int, default=20)
    send_cmd.add_argument("--excerpt-chars", type=int, default=700)
    send_cmd.add_argument("--model", default=None)
    send_cmd.add_argument("--base-url", default=None)
    send_cmd.add_argument("--nonthink", action="store_true")
    send_cmd.add_argument("--timeout", type=float, default=180)
    send_cmd.add_argument("--retries", type=int, default=1)
    send_cmd.add_argument("--subject", default="Stream Sieve Brief")
    send_cmd.add_argument("--body-file", default=None)
    send_cmd.add_argument("--no-synthesis", action="store_true", help="Build the report deterministically from saved scores/analyses without an LLM call.")
    send_cmd.add_argument("--category-limits", default=None)
    send_cmd.add_argument("--field-limits", default=None)
    add_source_pool_arg(send_cmd)
    send_cmd.add_argument("--delivery-key", default=None)
    send_cmd.add_argument("--resend", action="store_true")
    send_cmd.set_defaults(func=command_send)

    send_email_cmd = subparsers.add_parser(
        "send-email",
        help="Select saved content and deliver an email; never collects or scores content.",
    )
    send_email_cmd.add_argument("--config", default="configs/delivery.example.yaml")
    send_email_cmd.add_argument("--db", default=DEFAULT_DB)
    send_email_cmd.add_argument("--source", default=None)
    send_email_cmd.add_argument("--source-ids", default=None)
    send_email_cmd.add_argument("--min-score", type=float, default=7.0)
    send_email_cmd.add_argument("--limit", type=int, default=20)
    send_email_cmd.add_argument("--excerpt-chars", type=int, default=700)
    send_email_cmd.add_argument("--model", default=None)
    send_email_cmd.add_argument("--base-url", default=None)
    send_email_cmd.add_argument("--nonthink", action="store_true")
    send_email_cmd.add_argument("--timeout", type=float, default=180)
    send_email_cmd.add_argument("--retries", type=int, default=1)
    send_email_cmd.add_argument("--subject", default="Stream Sieve Brief")
    send_email_cmd.add_argument("--body-file", default=None)
    send_email_cmd.add_argument(
        "--no-synthesis",
        action="store_true",
        help="Build the report deterministically from saved scores/analyses without an LLM call.",
    )
    send_email_cmd.add_argument("--category-limits", default=None)
    send_email_cmd.add_argument("--field-limits", default=None)
    add_source_pool_arg(send_email_cmd)
    send_email_cmd.add_argument("--delivery-key", default=None)
    send_email_cmd.add_argument("--resend", action="store_true")
    send_email_cmd.set_defaults(func=command_send)
    return parser


def add_source_pool_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-pool", default=DEFAULT_SOURCE_POOL)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
