from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urljoin

import yaml

from stream_sieve.browser.linux_chrome_cdp import LinuxChromeCdpBackend
from stream_sieve.models import Article, ItemRef, RawDocument, content_hash, now_iso
from stream_sieve.storage import FeedStore, SyncStats


SNAPSHOT_LINK_RE = re.compile(r'^\s*-\s+link\s+"(?P<title>.*?)".*$')
SNAPSHOT_URL_RE = re.compile(r"^\s*-\s+/url:\s+(?P<url>.+?)\s*$")


def load_source(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("source file must contain a mapping")
    if not data.get("id"):
        raise ValueError("source.id is required")
    return data


def discover(source: dict[str, Any]) -> list[ItemRef]:
    discovery = source.get("discovery") or {}
    kind = discovery.get("type")
    if kind == "rss":
        return discover_rss(source)
    if kind == "browser":
        return discover_browser_links(source)
    if kind == "url":
        return [ItemRef(source_id=source["id"], url=discovery["url"], title=source.get("name"))]
    raise ValueError(f"unsupported discovery.type: {kind}")


def discover_rss(source: dict[str, Any]) -> list[ItemRef]:
    try:
        import feedparser
    except ModuleNotFoundError as exc:
        raise RuntimeError("feedparser is required for RSS discovery. Install requirements.txt.") from exc

    feed = feedparser.parse(source["discovery"]["url"])
    refs: list[ItemRef] = []
    for entry in feed.entries:
        url = getattr(entry, "link", None)
        if not url:
            continue
        refs.append(
            ItemRef(
                source_id=source["id"],
                url=url,
                title=getattr(entry, "title", None),
                external_id=getattr(entry, "id", None),
                published_at=getattr(entry, "published", None),
            )
        )
    return refs


def discover_browser_links(source: dict[str, Any]) -> list[ItemRef]:
    backend = _browser_backend(source)
    try:
        _must(backend.attach(), "attach")
        return discover_browser_links_with_backend(source, backend)
    finally:
        backend.close_tab()


def _browser_backend(source: dict[str, Any]) -> LinuxChromeCdpBackend:
    browser = source.get("browser") or {}
    return LinuxChromeCdpBackend(
        session=browser.get("session", "chrome-main"),
        cdp_endpoint=browser.get("cdp_endpoint", "http://127.0.0.1:9222"),
    )


def discover_browser_links_with_backend(source: dict[str, Any], backend: LinuxChromeCdpBackend) -> list[ItemRef]:
    discovery = source["discovery"]
    _must(backend.goto(discovery["url"]), "goto")
    if discovery.get("wait"):
        _must(backend.wait_until_stable(max_seconds=float(discovery["wait"])), "wait")
    backend.scroll(int(discovery.get("scroll", 0)), int(discovery.get("scroll_delta", 1400)), float(discovery.get("scroll_wait", 2)))
    links = json.loads(_must(backend.links(), "links").output)
    return parse_dom_links(source["id"], discovery["url"], links, discovery)


def parse_dom_links(source_id: str, base_url: str, links: list[dict[str, Any]], opts: dict[str, Any] | None = None) -> list[ItemRef]:
    opts = opts or {}
    include = re.compile(opts["include_url_regex"]) if opts.get("include_url_regex") else None
    exclude = re.compile(opts["exclude_url_regex"]) if opts.get("exclude_url_regex") else None
    refs: list[ItemRef] = []
    seen: set[str] = set()
    for link in links:
        title = str(link.get("title") or "").strip()
        url = urljoin(base_url, str(link.get("url") or "").strip())
        if not title or not url or url in seen:
            continue
        if include and not include.search(url):
            continue
        if exclude and exclude.search(url):
            continue
        seen.add(url)
        refs.append(ItemRef(source_id=source_id, url=url, title=title))
    return refs


def parse_snapshot_links(source_id: str, base_url: str, snapshot: str, opts: dict[str, Any] | None = None) -> list[ItemRef]:
    opts = opts or {}
    include = re.compile(opts["include_url_regex"]) if opts.get("include_url_regex") else None
    exclude = re.compile(opts["exclude_url_regex"]) if opts.get("exclude_url_regex") else None
    refs: list[ItemRef] = []
    pending_title: str | None = None
    seen: set[str] = set()
    for line in snapshot.splitlines():
        link = SNAPSHOT_LINK_RE.match(line)
        if link:
            pending_title = _unescape_snapshot_title(link.group("title"))
            continue
        url_match = SNAPSHOT_URL_RE.match(line)
        if not url_match or not pending_title:
            continue
        url = url_match.group("url").strip().strip('"')
        url = urljoin(base_url, url)
        pending_title = pending_title.strip()
        if not pending_title or url in seen:
            continue
        if include and not include.search(url):
            continue
        if exclude and exclude.search(url):
            continue
        seen.add(url)
        refs.append(ItemRef(source_id=source_id, url=url, title=pending_title))
    return refs


def acquire(source: dict[str, Any], ref: ItemRef) -> RawDocument:
    acquire_cfg = source.get("acquire") or {"type": "http"}
    if acquire_cfg.get("type") == "browser":
        return acquire_browser(source, ref)
    return acquire_http(source, ref)


def acquire_http(source: dict[str, Any], ref: ItemRef) -> RawDocument:
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise RuntimeError("httpx is required for HTTP acquire. Install requirements.txt.") from exc

    response = httpx.get(ref.url, headers=http_headers(source), follow_redirects=True, timeout=30)
    text = response.text
    return RawDocument(
        source_id=source["id"],
        url=str(response.url),
        content=text,
        mime_type=response.headers.get("content-type", "text/html"),
        fetched_at=now_iso(),
        transport="http",
        status_code=response.status_code,
        content_hash=content_hash(text),
    )


def http_headers(source: dict[str, Any]) -> dict[str, str]:
    headers = dict((source.get("acquire") or {}).get("headers") or {})
    headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    )
    return headers


def acquire_browser(source: dict[str, Any], ref: ItemRef) -> RawDocument:
    backend = _browser_backend(source)
    try:
        _must(backend.attach(), "attach")
        return acquire_browser_with_backend(source, ref, backend)
    finally:
        backend.close_tab()


def acquire_browser_with_backend(source: dict[str, Any], ref: ItemRef, backend: LinuxChromeCdpBackend) -> RawDocument:
    _must(backend.goto(ref.url), "goto")
    wait = float((source.get("acquire") or {}).get("wait", 0))
    if wait:
        _must(backend.wait_until_stable(max_seconds=wait), "wait")
    html = _must(backend.html(), "html").output
    return RawDocument(
        source_id=source["id"],
        url=ref.url,
        content=html,
        mime_type="text/html",
        fetched_at=now_iso(),
        transport="browser",
        status_code=None,
        content_hash=content_hash(html),
    )


def extract_article(source: dict[str, Any], raw: RawDocument, title: str | None = None) -> Article:
    extract_cfg = source.get("extract") or {}
    extracted = extract_by_xpath(raw.content, extract_cfg, url=raw.url)
    metadata = extract_metadata(raw.content, extract_cfg, url=raw.url)
    if not extracted:
        try:
            import trafilatura
        except ModuleNotFoundError as exc:
            raise RuntimeError("trafilatura is required for extraction. Install requirements.txt.") from exc
        extracted = trafilatura.extract(raw.content, url=raw.url, include_comments=False, include_tables=False)
    text = extracted or _html_text(raw.content)
    text = apply_cleanup(text.strip(), extract_cfg, title=title)
    return Article(
        source_id=source["id"],
        url=raw.url,
        title=title or _html_title(raw.content) or raw.url,
        content=text,
        fetched_at=raw.fetched_at,
        content_hash=raw.content_hash,
        author=metadata.get("author"),
        published_at=metadata.get("published_at"),
    )


def run_once(source: dict[str, Any], limit: int) -> list[Article]:
    articles: list[Article] = []
    for ref in discover(source):
        if len(articles) >= limit:
            break
        article = acquire_extract_or_none(source, ref)
        if article and article.content:
            articles.append(article)
    return articles


def sync_source(source: dict[str, Any], limit: int, db_path: str) -> tuple[SyncStats, list[Article]]:
    if _can_reuse_browser(source):
        return sync_source_browser_reuse(source, limit, db_path)

    refs = discover(source)
    store = FeedStore(db_path)
    articles: list[Article] = []
    saved = 0
    try:
        new_refs = [ref for ref in refs if not store.seen_url(source["id"], ref.url)]
        for ref in new_refs:
            if len(articles) >= limit:
                break
            article = acquire_extract_or_none(source, ref)
            if not article or not article.content.strip():
                continue
            articles.append(article)
            if store.save_article(article):
                saved += 1
        store.mark_success(source["id"])
        return (
            SyncStats(
                source_id=source["id"],
                discovered=len(refs),
                new=len(new_refs),
                extracted=len(articles),
                saved=saved,
                db=store.path,
            ),
            articles,
        )
    finally:
        store.close()


def _can_reuse_browser(source: dict[str, Any]) -> bool:
    return (source.get("discovery") or {}).get("type") == "browser" and (source.get("acquire") or {}).get("type") == "browser"


def sync_source_browser_reuse(source: dict[str, Any], limit: int, db_path: str) -> tuple[SyncStats, list[Article]]:
    backend = _browser_backend(source)
    store = FeedStore(db_path)
    articles: list[Article] = []
    saved = 0
    try:
        _must(backend.attach(), "attach")
        refs = discover_browser_links_with_backend(source, backend)
        new_refs = [ref for ref in refs if not store.seen_url(source["id"], ref.url)]
        for ref in new_refs:
            if len(articles) >= limit:
                break
            article = acquire_extract_or_none(source, ref, backend)
            if not article or not article.content.strip():
                continue
            articles.append(article)
            if store.save_article(article):
                saved += 1
        store.mark_success(source["id"])
        return (
            SyncStats(
                source_id=source["id"],
                discovered=len(refs),
                new=len(new_refs),
                extracted=len(articles),
                saved=saved,
                db=store.path,
            ),
            articles,
        )
    finally:
        backend.close_tab()
        store.close()


def acquire_extract_or_none(source: dict[str, Any], ref: ItemRef, backend: LinuxChromeCdpBackend | None = None, progress=None) -> Article | None:
    try:
        raw = acquire_browser_with_backend(source, ref, backend) if backend else acquire(source, ref)
        if not raw.content.strip():
            raise ValueError("empty document")
        return extract_article(source, raw, title=ref.title)
    except Exception as exc:
        if progress:
            progress(f"skip article: {ref.url} ({type(exc).__name__}: {exc})")
        return None


def sync_sources(
    sources: list[tuple[dict[str, Any], int]],
    db_path: str,
    progress=None,
) -> list[tuple[SyncStats, list[Article]]]:
    browser_sources = [(source, limit) for source, limit in sources if _can_reuse_browser(source)]
    if len(browser_sources) != len(sources):
        results = []
        for source, limit in sources:
            if progress:
                progress(f"sync source: {source['id']}")
            results.append(sync_source_soft(source, limit, db_path, progress))
        return results
    if not sources:
        return []

    backend = _browser_backend(sources[0][0])
    store = FeedStore(db_path)
    results: list[tuple[SyncStats, list[Article]]] = []
    try:
        try:
            _must(backend.attach(), "attach")
        except Exception as exc:
            message = short_error(exc)
            if progress:
                progress(f"[ERROR] browser attach failed: {message}")
            return [
                (failed_sync_stats(source, db_path, message), [])
                for source, _limit in sources
            ]
        for source, limit in sources:
            if progress:
                progress(f"sync source: {source['id']}")
            try:
                articles: list[Article] = []
                saved = 0
                refs = discover_browser_links_with_backend(source, backend)
                new_refs = [ref for ref in refs if not store.seen_url(source["id"], ref.url)]
                for ref in new_refs:
                    if len(articles) >= limit:
                        break
                    article = acquire_extract_or_none(source, ref, backend, progress)
                    if not article or not article.content.strip():
                        continue
                    articles.append(article)
                    if store.save_article(article):
                        saved += 1
                store.mark_success(source["id"])
                results.append(
                    (
                        SyncStats(
                            source_id=source["id"],
                            discovered=len(refs),
                            new=len(new_refs),
                            extracted=len(articles),
                            saved=saved,
                            db=store.path,
                        ),
                        articles,
                    )
                )
            except Exception as exc:
                message = short_error(exc)
                if progress:
                    progress(f"[ERROR] {source['id']}: {message}; skipping source")
                results.append((failed_sync_stats(source, store.path, message), []))
        return results
    finally:
        backend.close_tab()
        store.close()


def sync_source_soft(
    source: dict[str, Any],
    limit: int,
    db_path: str,
    progress=None,
) -> tuple[SyncStats, list[Article]]:
    try:
        return sync_source(source, limit, db_path)
    except Exception as exc:
        message = short_error(exc)
        if progress:
            progress(f"[ERROR] {source['id']}: {message}; skipping source")
        return failed_sync_stats(source, db_path, message), []


def failed_sync_stats(source: dict[str, Any], db_path: str, error: str) -> SyncStats:
    return SyncStats(
        source_id=str(source.get("id") or "unknown"),
        discovered=0,
        new=0,
        extracted=0,
        saved=0,
        db=db_path,
        error=error,
    )


def short_error(exc: Exception, max_chars: int = 500) -> str:
    message = " ".join(str(exc).split()) or type(exc).__name__
    return message[:max_chars]


def article_markdown(articles: list[Article]) -> str:
    parts = []
    for index, article in enumerate(articles, start=1):
        body = article.content.strip()
        parts.append(
            f"## item {index}\n\n"
            f"title: {article.title}\n\n"
            f"url: {article.url}\n\n"
            f"author: {article.author or ''}\n\n"
            f"published_at: {article.published_at or ''}\n\n"
            "content:\n\n"
            f"{body}\n"
        )
    return "\n".join(parts)


def extract_by_xpath(html: str, extract_cfg: dict[str, Any], url: str = "") -> str | None:
    if not html.strip():
        return None
    xpaths = extract_cfg.get("content_xpath") or []
    if isinstance(xpaths, str):
        xpaths = [xpaths]
    if not xpaths:
        return None
    try:
        from lxml import html as lxml_html
    except ModuleNotFoundError:
        return None

    doc = lxml_html.fromstring(html)
    external_id = _extract_external_id(url, extract_cfg)
    for xpath in xpaths:
        if "{external_id}" in xpath:
            if not external_id:
                continue
            xpath = xpath.replace("{external_id}", external_id)
        parts: list[str] = []
        for node in doc.xpath(xpath):
            if hasattr(node, "text_content"):
                text = _node_text(node)
            else:
                text = str(node).strip()
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
    return None


def extract_metadata(html: str, extract_cfg: dict[str, Any], url: str = "") -> dict[str, str]:
    if not html.strip():
        return {}
    metadata_xpath = extract_cfg.get("metadata_xpath") or {}
    metadata_regex = extract_cfg.get("metadata_regex") or {}
    if not metadata_xpath:
        return {}
    try:
        from lxml import html as lxml_html
    except ModuleNotFoundError:
        return {}

    doc = lxml_html.fromstring(html)
    external_id = _extract_external_id(url, extract_cfg)
    out: dict[str, str] = {}
    for key, xpath_or_list in metadata_xpath.items():
        value = _first_metadata_value(doc, xpath_or_list, external_id)
        pattern = metadata_regex.get(key)
        if value and pattern:
            match = re.search(str(pattern), value)
            if match:
                value = match.group(1)
        if value:
            out[str(key)] = _clean_scalar(value)
    return out


def _first_metadata_value(doc: Any, xpath_or_list: Any, external_id: str | None) -> str | None:
    xpaths = xpath_or_list if isinstance(xpath_or_list, list) else [xpath_or_list]
    for xpath in xpaths:
        value = _first_xpath_text(doc, _fill_external_id(str(xpath), external_id))
        if value:
            return value
    return None


def _first_xpath_text(doc: Any, xpath: str | None) -> str | None:
    if not xpath:
        return None
    nodes = doc.xpath(xpath)
    if not nodes:
        return None
    node = nodes[0]
    if hasattr(node, "text_content"):
        return node.text_content().strip()
    return str(node).strip()


def _node_text(node: Any) -> str:
    blocks = node.xpath(".//p|.//li|.//h1|.//h2|.//h3|.//blockquote")
    if not blocks:
        return _clean_content_line(node.text_content())
    lines = [_clean_content_line(block.text_content()) for block in blocks]
    return "\n".join(line for line in lines if line)


def _extract_external_id(url: str, extract_cfg: dict[str, Any]) -> str | None:
    pattern = extract_cfg.get("external_id_regex")
    if not pattern:
        return None
    match = re.search(pattern, url)
    return match.group(1) if match else None


def _fill_external_id(xpath: str, external_id: str | None) -> str | None:
    if "{external_id}" not in xpath:
        return xpath
    if not external_id:
        return None
    return xpath.replace("{external_id}", external_id)


def _clean_scalar(value: str) -> str:
    value = value.replace("\u200b", "")
    return re.sub(r"\s+", " ", value).strip()


def _clean_content_line(value: str) -> str:
    value = value.replace("\u200b", "")
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def apply_cleanup(text: str, extract_cfg: dict[str, Any], title: str | None = None) -> str:
    cleanup = extract_cfg.get("cleanup") or {}
    if not cleanup:
        return text.strip()

    lines = [_clean_content_line(line) for line in text.splitlines()]
    if cleanup.get("start_at_title") and title:
        for index, line in enumerate(lines):
            if line == title:
                lines = lines[index:]
                break

    stop_before = set(cleanup.get("stop_before") or [])
    drop_lines = set(cleanup.get("drop_lines") or [])
    kept: list[str] = []
    previous_blank = False
    for line in lines:
        if line in stop_before:
            break
        if line in drop_lines:
            continue
        blank = not line
        if blank and previous_blank:
            continue
        kept.append(line)
        previous_blank = blank
    return "\n".join(kept).strip()


def _must(result: Any, step: str) -> Any:
    if not result.ok:
        raise RuntimeError(f"{step} failed: {result.output}")
    return result


def _unescape_snapshot_title(title: str) -> str:
    return title.replace('\\"', '"')


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self._in_title = False
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        if self._in_title and not self.title:
            self.title = stripped
        self.text.append(stripped)


def _html_title(html: str) -> str | None:
    parser = _TextParser()
    parser.feed(html)
    return parser.title


def _html_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    return "\n".join(parser.text)


def _demo() -> None:
    raw = RawDocument("demo", "https://example.com/b", "<p>ok</p>", "text/html", now_iso(), "browser", None, "h")
    article = Article("demo", raw.url, "B", "short", raw.fetched_at, raw.content_hash)
    assert article.content.strip()
    wsj_opts = {
        "include_url_regex": r"^https://www\.wsj\.com/(articles/|world/|business/|finance/|tech/|economy/|politics/|us-news/|opinion/|lifestyle/|arts-culture/|personal-finance/|real-estate/|health/)",
        "exclude_url_regex": r"(subscribe|login|market-data|digital-print-edition|client/silent-login|#comments)",
    }
    refs = parse_dom_links(
        "wsj-home",
        "https://www.wsj.com",
        [
            {"title": "Print Edition", "url": "https://www.wsj.com/digital-print-edition?mod=wsjheader"},
            {"title": "Real Article", "url": "https://www.wsj.com/tech/ai/example-story-123"},
        ],
        wsj_opts,
    )
    assert [ref.title for ref in refs] == ["Real Article"]


if __name__ == "__main__":
    _demo()
