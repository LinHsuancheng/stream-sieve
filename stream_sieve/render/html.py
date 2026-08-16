from __future__ import annotations

from datetime import date
from html import escape
from typing import Any


FIELD_LABELS = {
    "ai_news": "AI & Computing",
    "tech": "Technology",
    "economy": "Economy",
    "politics": "Politics",
    "society": "Society",
    "cognition": "Cognition & Growth",
}


def render_digest_html(digest: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    by_id = {int(row["id"]): row for row in rows}
    meta = digest.get("meta") if isinstance(digest.get("meta"), dict) else {}
    sections = [section for section in digest.get("sections", []) if _section_items(section)]
    fields = [FIELD_LABELS.get(str(section.get("category") or ""), str(section.get("category") or "")) for section in sections]
    field_links = " · ".join(
        f'<a href="#field-{escape(str(section.get("category") or ""), quote=True)}">{escape(label)}</a>'
        for section, label in zip(sections, fields)
    )
    title = str(meta.get("title") or digest.get("headline") or "Daily Brief")

    body = [
        "<!doctype html><html><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<style>{NEWSLETTER_CSS}</style></head><body>",
        '<main class="page-shell">',
        '<header class="masthead">',
        '<div class="brand-row">',
        '<div class="brand">STREAM SIEVE</div>',
        '<div class="edition">DAILY EDITION</div>',
        "</div>",
        '<div class="hero">',
        '<p class="eyebrow">Curated reading</p>',
        f"<h1>{escape(title)}</h1>",
        '<div class="meta-line">',
        f"<span>{date.today().isoformat()}</span>",
        f"<span>{len(rows)} articles</span>",
        f'<span class="field-nav">{field_links}</span>' if field_links else "",
        "</div>",
        "</div>",
        "</header>",
    ]

    highlights = digest.get("highlights") or []
    if highlights:
        body.extend(['<section class="section-block">', '<div class="section-label-row"><p class="section-label">Today\'s Highlights</p><span class="section-count">TOP</span></div>', '<div class="highlight-list">'])
        for index, item in enumerate(highlights[:12], start=1):
            row = _first_row(item, by_id)
            if not row:
                continue
            summary = str(item.get("summary") or item.get("description") or "").strip()
            title = str(row.get("title") or "").strip()
            line = " — ".join(part for part in (title, summary) if part)
            klass = "highlight-row"
            body.extend(
                [
                    f'<article class="{klass}">',
                    f'<span class="highlight-number">{index:02d}</span>',
                    f'<p class="highlight-take">{escape(line)}</p>',
                    "</article>",
                ]
            )
        body.extend(["</div>", "</section>"])

    for section_index, section in enumerate(sections, start=1):
        category = str(section.get("category") or "")
        items = _section_items(section)[:20]
        body.extend(
            [
                f'<section id="field-{escape(category, quote=True)}" class="section-block">',
                '<div class="section-header">',
                "<div>",
                f'<p class="section-index">{section_index:02d}</p>',
                f"<h2>{escape(FIELD_LABELS.get(category, category))}</h2>",
                "</div>",
                "</div>",
            ]
        )
        body.append('<div class="article-grid">')
        for article_index, item in enumerate(items, start=1):
            row = _first_row(item, by_id)
            if not row:
                continue
            paragraphs = _paragraphs(item, row)[:1]
            dek = str(item.get("dek") or "").strip()
            body.extend([
                '<article class="article">',
                f'<div class="article-number">{section_index:02d}.{article_index:02d}</div>',
                f'<h3><a href="{escape(str(row.get("url") or ""), quote=True)}">{escape(str(row.get("title") or ""))}</a></h3>',
                *([f'<p class="article-dek">{escape(dek)}</p>'] if dek else []),
                f'<div class="article-meta"><span>{escape(_source_name(row))}</span><span>{_word_count(row)} words</span><span>{escape(_short_date(row))}</span><span>{_reading_minutes(row)} min</span><span>{escape(str(row.get("total_score") or ""))}</span></div>',
                '<div class="article-body">',
                *[f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs],
                "</div>",
                f'<div class="article-footer"><a class="source-link" href="{escape(str(row.get("url") or ""), quote=True)}">Read original &rarr;</a></div>',
                "</article>",
            ])
        body.extend(["</div>", "</section>"])

    quick_reads = digest.get("quick_reads") or []
    if quick_reads:
        body.extend([
            '<section class="section-block"><div class="section-header"><div><p class="section-index">Q</p><h2>Quick reads</h2></div></div>',
            '<div class="article-grid">',
        ])
        for index, item in enumerate(quick_reads, start=1):
            row = _first_row(item, by_id)
            if not row:
                continue
            summary = str(item.get("summary") or item.get("description") or row.get("one_liner") or row.get("reason") or "").strip()
            body.extend([
                '<article class="article">',
                f'<div class="article-number">Q.{index:02d}</div>',
                f'<h3><a href="{escape(str(row.get("url") or ""), quote=True)}">{escape(str(row.get("title") or ""))}</a></h3>',
                f'<p class="article-dek">{escape(summary)}</p>',
                f'<div class="article-footer"><a class="source-link" href="{escape(str(row.get("url") or ""), quote=True)}">Read original &rarr;</a></div>',
                '</article>',
            ])
        body.extend(["</div>", "</section>"])

    reading_list = digest.get("reading_list") or []
    if reading_list:
        body.extend([
            '<section class="section-block"><div class="section-header"><div><p class="section-index">R</p><h2>Reading list</h2></div></div>',
            '<ol class="reading-list">',
        ])
        for article_id in reading_list:
            row = _row_by_id(article_id, by_id)
            if row:
                body.append(f'<li><a href="{escape(str(row.get("url") or ""), quote=True)}">{escape(str(row.get("title") or ""))}</a><span>{escape(_source_name(row))}</span></li>')
        body.extend(["</ol>", "</section>"])

    referenced = _referenced_ids(digest)
    extras = [row for row in rows if int(row["id"]) not in referenced]
    if extras:
        body.extend([
            '<section class="section-block"><div class="section-header"><div><p class="section-index">+</p><h2>More selected reading</h2></div></div>',
            '<div class="article-grid">',
        ])
        for index, row in enumerate(extras, start=1):
            summary = str(row.get("summary") or row.get("one_liner") or row.get("reason") or "").strip()
            body.extend([
                '<article class="article">',
                f'<div class="article-number">+.{index:02d}</div>',
                f'<h3><a href="{escape(str(row.get("url") or ""), quote=True)}">{escape(str(row.get("title") or ""))}</a></h3>',
                f'<p class="article-dek">{escape(summary)}</p>',
                f'<div class="article-meta"><span>{escape(_source_name(row))}</span><span>{escape(str(row.get("total_score") or ""))}</span></div>',
                '</article>',
            ])
        body.extend(["</div>", "</section>"])

    body.extend(['<footer class="report-footer"><span>STREAM SIEVE</span><span>END OF BRIEF</span></footer>', "</main>", "</body></html>"])
    return "\n".join(part for part in body if part)


def _section_items(section: dict[str, Any]) -> list[dict[str, Any]]:
    return section.get("items") or section.get("articles") or []


def _first_row(item: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    ids = item.get("article_ids")
    if not isinstance(ids, list):
        ids = [item.get("article_id")] if item.get("article_id") is not None else []
    for article_id in ids:
        row = _row_by_id(article_id, by_id)
        if row:
            return row
    return {}


def _row_by_id(article_id: Any, by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    try:
        return by_id[int(article_id)]
    except (KeyError, TypeError, ValueError):
        return {}


def _item_ids(item: dict[str, Any]) -> list[Any]:
    ids = item.get("article_ids")
    if isinstance(ids, list):
        return ids
    article_id = item.get("article_id")
    return [article_id] if article_id is not None else []


def _referenced_ids(digest: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for item in digest.get("highlights") or []:
        ids.update(int(value) for value in _item_ids(item) if str(value).isdigit())
    for section in digest.get("sections") or []:
        for item in _section_items(section):
            ids.update(int(value) for value in _item_ids(item) if str(value).isdigit())
    for item in digest.get("quick_reads") or []:
        ids.update(int(value) for value in _item_ids(item) if str(value).isdigit())
    ids.update(int(value) for value in digest.get("reading_list") or [] if str(value).isdigit())
    return ids


def _paragraphs(item: dict[str, Any], row: dict[str, Any]) -> list[str]:
    content = item.get("content")
    if isinstance(content, list):
        return [str(paragraph).strip() for paragraph in content if str(paragraph).strip()]
    summary = str(item.get("summary") or item.get("description") or row.get("summary") or row.get("one_liner") or "").strip()
    return [summary] if summary else []


def _category(row: dict[str, Any]) -> str:
    meta = row.get("source_meta") or {}
    category = row.get("category") or meta.get("briefing_category") or ""
    return FIELD_LABELS.get(str(category), str(category))


def _source_name(row: dict[str, Any]) -> str:
    meta = row.get("source_meta") or {}
    return str(meta.get("name") or row.get("source_id") or "")


def _word_count(row: dict[str, Any]) -> int:
    content = str(row.get("content") or "")
    return len(content.split()) or len(content) // 2


def _short_date(row: dict[str, Any]) -> str:
    published = str(row.get("published_at") or row.get("first_seen_at") or "").strip()
    return published[:10] if published else ""


def _reading_minutes(row: dict[str, Any]) -> int:
    words = len(str(row.get("content") or "").split()) or len(str(row.get("content") or "")) // 2
    return max(1, (words + 199) // 200) if words else 1


NEWSLETTER_CSS = """
:root{--paper:#f1eee8;--paper-raised:#ebe7df;--ink:#2e312f;--ink-soft:#5f645f;--ink-faint:#858983;--rule:#d5d0c6;--accent:#9ca89b;--accent-2:#a8afb3;--accent-warm:#b3a19b;--display:"Iowan Old Style","Palatino Linotype","Book Antiqua","Noto Serif CJK SC","Source Han Serif SC","Songti SC",serif;--body:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei",sans-serif;--mono:"SFMono-Regular",Consolas,"Liberation Mono",monospace;--wide:1080px;--reading:690px}
*{box-sizing:border-box}html{background:var(--paper);color:var(--ink);font-size:16px;text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased}body{margin:0;background:linear-gradient(to bottom,rgba(255,255,255,.18),rgba(255,255,255,0) 22rem),var(--paper);color:var(--ink);font-family:var(--body);line-height:1.68}a{color:inherit;text-decoration-color:rgba(46,49,47,.35);text-underline-offset:.16em;text-decoration-thickness:1px}.page-shell{width:min(calc(100% - 48px),var(--wide));margin:0 auto}.masthead{padding:30px 0 72px;border-bottom:1px solid var(--rule)}.brand-row{display:flex;justify-content:space-between;gap:24px;align-items:baseline;font-size:.72rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-soft)}.brand{font-weight:700}.edition{color:var(--ink-faint)}.hero{max-width:890px;padding-top:92px}.eyebrow,.story-kicker,.section-label,.section-index{margin:0;color:var(--ink-soft);font-size:.72rem;font-weight:700;line-height:1.25;letter-spacing:.11em;text-transform:uppercase}.hero h1{max-width:900px;margin:14px 0 22px;font-family:var(--display);font-size:clamp(3.7rem,9vw,7.8rem);font-weight:500;letter-spacing:-.055em;line-height:.89}.deck{max-width:720px;margin:0;color:var(--ink-soft);font-family:var(--display);font-size:clamp(1.18rem,2vw,1.55rem);line-height:1.42}.meta-line{display:flex;flex-wrap:wrap;gap:10px 20px;margin-top:34px;color:var(--ink-faint);font-size:.78rem}.section-block{padding:68px 0 76px;border-bottom:1px solid var(--rule)}.section-label-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:34px}.section-count{font-family:var(--mono);color:var(--ink-faint);font-size:.72rem}.highlight-grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(240px,.55fr);gap:44px 54px}.highlight{align-self:start}.highlight:not(.highlight-primary){padding-top:5px;border-top:4px solid var(--accent)}.highlight-primary{grid-row:span 2}.highlight h2{margin:10px 0 14px;font-family:var(--display);font-size:clamp(1.9rem,4.5vw,3.65rem);font-weight:500;letter-spacing:-.035em;line-height:1.02}.highlight:not(.highlight-primary) h2{font-size:clamp(1.45rem,2.8vw,2.05rem);line-height:1.08}.highlight h2 a,.article h3 a,.quick-item h3 a{text-decoration:none}.summary{max-width:60ch;margin:0;color:var(--ink-soft);font-size:.98rem}.story-meta,.article-meta,.quick-meta{color:var(--ink-faint);font-size:.73rem}.story-meta{display:flex;gap:10px 16px;margin-top:18px}.section-header{display:grid;grid-template-columns:minmax(0,1fr) minmax(240px,360px);gap:40px;align-items:end;margin-bottom:58px}.section-header h2{margin:7px 0 0;font-family:var(--display);font-size:clamp(2.5rem,6vw,5.2rem);font-weight:500;letter-spacing:-.045em;line-height:.94}.section-note{margin:0 0 4px;color:var(--ink-soft);font-family:var(--display);font-size:1.03rem;line-height:1.5}.article{padding:0 0 64px}.article+.article{padding-top:58px;border-top:1px solid var(--rule)}.article-header{display:grid;grid-template-columns:minmax(0,1fr) 145px;gap:56px;align-items:start;margin-bottom:34px}.article h3{max-width:780px;margin:9px 0 12px;font-family:var(--display);font-size:clamp(2rem,4vw,3.25rem);font-weight:500;letter-spacing:-.032em;line-height:1.03}.article-dek{max-width:700px;margin:0;color:var(--ink-soft);font-family:var(--display);font-size:1.08rem;line-height:1.5}.article-meta{display:grid;gap:5px;padding-top:25px;text-align:right}.article-body{width:min(100%,var(--reading));margin-left:clamp(0px,8vw,96px)}.article-body p{margin:0 0 1.15em;font-size:1.02rem;line-height:1.78;letter-spacing:.002em}.article-body p:first-child::first-letter{float:left;margin:.12em .09em 0 0;font-family:var(--display);font-size:3.4em;line-height:.72;color:var(--ink)}.article-footer{width:min(100%,var(--reading));margin:26px 0 0 clamp(0px,8vw,96px)}.source-link{font-size:.78rem;font-weight:650;text-decoration:none}.quick-list{display:grid;grid-template-columns:1fr 1fr;gap:0 50px}.quick-item{display:grid;grid-template-columns:minmax(0,1fr) 100px;gap:24px;padding:28px 0;border-top:1px solid var(--rule)}.quick-item h3{margin:7px 0 8px;font-family:var(--display);font-size:1.42rem;font-weight:500;letter-spacing:-.018em;line-height:1.12}.quick-item p:not(.story-kicker){margin:0;color:var(--ink-soft);font-size:.9rem;line-height:1.6}.quick-meta{display:grid;align-content:start;gap:4px;padding-top:20px;text-align:right}.reading-list ol{list-style:none;margin:0;padding:0;counter-reset:read}.reading-list li{counter-increment:read;display:grid;grid-template-columns:46px minmax(0,1fr) 180px;gap:18px;align-items:baseline;padding:17px 0;border-top:1px solid var(--rule)}.reading-list li:before{content:counter(read,decimal-leading-zero);color:var(--ink-faint);font-family:var(--mono);font-size:.7rem}.reading-list li a{font-family:var(--display);font-size:1.05rem;text-decoration:none}.reading-list li span{color:var(--ink-faint);font-size:.74rem;text-align:right}.report-footer{display:flex;justify-content:space-between;padding:28px 0 42px;color:var(--ink-faint);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase}
@media(max-width:780px){.page-shell{width:min(calc(100% - 32px),var(--wide))}.masthead{padding-bottom:52px}.hero{padding-top:62px}.highlight-grid,.section-header,.article-header,.quick-list{grid-template-columns:1fr}.highlight-primary{grid-row:auto}.highlight:not(.highlight-primary){padding-top:20px}.section-header{gap:20px}.article-header{gap:14px}.article-meta{display:flex;flex-wrap:wrap;gap:8px 16px;padding-top:0;text-align:left}.article-body,.article-footer{margin-left:0}.quick-item{grid-template-columns:1fr;gap:10px}.quick-meta{display:flex;gap:12px;padding:0;text-align:left}.reading-list li{grid-template-columns:34px 1fr}.reading-list li span{grid-column:2;text-align:left}}
"""


# Compact editorial overrides: BestBlogs-style scanning density while keeping
# the existing HTML structure and email-safe inline stylesheet.
NEWSLETTER_CSS += """
.page-shell{width:calc(100% - 60px);max-width:none}
:root{--paper:#e9e5dd;--paper-raised:#f3f0ea;--ink:#343633;--ink-soft:#666b65;--ink-faint:#898d85;--rule:#c4bbb0;--accent:#9eaa9b;--accent-2:#9eafb4;--accent-warm:#b99d98}
html{font-size:20px}
.masthead{padding:20px 0 30px}
.hero{padding-top:38px}
.hero h1{font-size:clamp(2.3rem,4vw,3.8rem);letter-spacing:-.03em;line-height:1}
.deck{font-size:1rem;max-width:900px}
.meta-line{margin-top:22px;font-size:.72rem}
.section-block{padding:24px 26px 28px;margin:22px 0;border:1px solid var(--rule);border-top:3px solid var(--accent);border-radius:8px;background:var(--paper-raised)}
.section-block:nth-of-type(2){border-top-color:var(--accent-2)}
.section-block:nth-of-type(3){border-top-color:var(--accent-warm)}
.section-block:nth-of-type(4){border-top-color:#b5aa8e}
.section-block:nth-of-type(5){border-top-color:#aaa4b2}
.section-block:nth-of-type(6){border-top-color:#a6aaa0}
.section-label-row{margin-bottom:14px}
.section-header{margin-bottom:18px}
.section-header h2{font-size:1.55rem;letter-spacing:-.015em}
.section-note{font-size:.92rem}
.highlight-list{border-top:1px solid var(--rule)}
.highlight-row{display:grid;grid-template-columns:32px minmax(0,1fr);gap:10px;align-items:baseline;padding:12px 14px;margin:10px 0;border:1px solid var(--rule);border-radius:6px;background:rgba(255,255,255,.28)}
.highlight-number{color:var(--ink-faint);font-family:var(--mono);font-size:.7rem}
.highlight-row h2{margin:0;font-family:var(--display);font-size:1.04rem;font-weight:500;letter-spacing:0;line-height:1.35}
.article{width:87.5%;margin-left:auto;margin-right:auto;padding:18px 22px;border:1px solid var(--rule);border-radius:6px;background:rgba(255,255,255,.28)}
.article+.article{padding-top:18px;margin-top:14px}
.article-header{display:block;margin-bottom:12px}
.article h3{font-size:1.6em;letter-spacing:0;line-height:1.25}
.article-dek{font-size:.9rem;line-height:1.5}
.article-meta{display:flex;flex-wrap:wrap;gap:5px 0;align-items:center;width:max-content;max-width:100%;padding:3px 8px;border:1px solid var(--rule);border-radius:4px;background:rgba(255,255,255,.32);font-size:.62rem;text-align:left}
.article-meta span+span{border-left:1px solid var(--rule);margin-left:8px;padding-left:8px}
.article-body{width:100%;margin:16px 0 0;font-size:.92rem;line-height:1.68}
.article-body p:first-child::first-letter{float:none;margin:0;font-size:inherit;line-height:inherit}
.article-footer{width:100%;margin:12px 0 0}
.source-link{font-size:.72rem}
.quick-list{grid-template-columns:1fr}
@media(max-width:780px){.page-shell{width:calc(100% - 24px)}.article{width:100%}.article-body,.article-footer{margin-left:0}.article-header{display:block}.article-meta{text-align:left;margin-top:8px}.highlight-row{grid-template-columns:26px minmax(0,1fr)}}
"""

# Dense two-column item layout modeled on BestBlogs' scan-first entries.
NEWSLETTER_CSS += """
.highlight-list{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;border-top:0}
.highlight-row{margin:0;min-height:54px;padding:9px 11px;align-items:start}
.highlight-take{margin:0;color:var(--ink);font-size:.83rem;line-height:1.35}
.article-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;width:100%;padding:0 30px}
.article{width:100%;min-height:112px;margin:0;padding:10px 13px;border-radius:6px}
.article+.article{margin-top:0;padding-top:12px}
.article-number{color:var(--ink-faint);font-family:var(--mono);font-size:.62rem;line-height:1}
.article h3{margin:4px 0 6px;font-size:1.05rem;font-weight:750;line-height:1.2;letter-spacing:0}
.article-dek{margin:0 0 6px;font-family:var(--body);font-size:.82rem;line-height:1.3;color:var(--ink-soft)}
.article-meta{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto auto;gap:7px;border:0;border-top:1px solid var(--rule);border-radius:0;padding:5px 0 0;width:100%;background:transparent;font-size:.61rem;line-height:1.2;color:var(--ink-faint)}
.article-meta span+span{border-left:0;margin-left:0;padding-left:0}
.article-meta span:first-child{color:var(--ink-soft);font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.article-meta span:last-child{color:var(--ink);font-weight:700}
.article-body{margin:6px 0 0;font-size:.82rem;line-height:1.3;color:var(--ink-soft)}
.article-body p{margin:0;font-size:.82rem;line-height:1.3}
.article-footer{margin:6px 0 0}
.source-link{font-size:.62rem;color:var(--ink-faint)}
/* Small reading-focused responses for the interactive preview and webmail. */
.article,.highlight-row{position:relative;overflow:hidden;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease,background-color .18s ease}
.article::before,.highlight-row::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent-2);transform:scaleY(0);transform-origin:center;transition:transform .18s ease}
.article:hover,.highlight-row:hover{transform:translateY(-2px);border-color:var(--accent-2);background:rgba(255,255,255,.52);box-shadow:0 5px 16px rgba(71,72,67,.11)}
.article:hover::before,.highlight-row:hover::before{transform:scaleY(1)}
.article a,.highlight-row a{transition:color .18s ease}
.article a:hover,.highlight-row a:hover{color:#536d72;text-decoration:none}
.masthead{transition:border-color .22s ease,background-color .22s ease}
.masthead:hover{border-bottom-color:var(--accent-2);background:rgba(255,255,255,.08)}
.hero h1{position:relative;display:inline-block;transition:color .2s ease,letter-spacing .2s ease,text-shadow .2s ease}
.hero h1::after{content:"";position:absolute;left:0;right:0;bottom:-7px;height:2px;background:var(--accent-2);transform:scaleX(0);transform-origin:left;transition:transform .22s ease}
.hero h1:hover{color:#536d72;letter-spacing:.005em;text-shadow:0 2px 10px rgba(83,109,114,.12)}
.hero h1:hover::after{transform:scaleX(1)}
.field-nav{display:inline-flex;flex-wrap:wrap;gap:5px 10px}
.field-nav a{padding:2px 7px;border:1px solid transparent;border-radius:999px;transition:background-color .18s ease,border-color .18s ease,color .18s ease}
.field-nav a:hover{border-color:var(--accent-2);background:rgba(158,175,180,.18);color:#536d72;text-decoration:none}
.deck{transition:color .2s ease}
.hero:hover .deck{color:var(--ink)}
.section-block{transition:border-color .2s ease,background-color .2s ease,box-shadow .2s ease}
.section-block:hover{transform:translateY(-3px);border-color:var(--accent-2);background:rgba(255,255,255,.42);box-shadow:0 10px 28px rgba(71,72,67,.12)}
.section-header h2{transition:color .2s ease,letter-spacing .2s ease}
.section-block:hover .section-header h2{color:#536d72;letter-spacing:.005em}
@media(max-width:780px){.page-shell{width:calc(100% - 24px)}.highlight-list,.article-grid{grid-template-columns:1fr;padding-left:0;padding-right:0}.article{min-height:0}.article-meta{grid-template-columns:minmax(0,1fr) auto auto auto auto}}
@media(prefers-reduced-motion:reduce){.masthead,.hero h1,.hero h1::after,.deck,.field-nav a,.section-block,.section-header h2,.article,.highlight-row,.article::before,.highlight-row::before,.article a,.highlight-row a{transition:none}.article:hover,.highlight-row:hover,.section-block:hover{transform:none}}
"""


def markdown_to_html(markdown: str) -> str:
    body = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            body.append(f"<h3>{escape(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            body.append(f"<h2>{escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            body.append(f"<h1>{escape(stripped[2:])}</h1>")
        else:
            body.append(f"<p>{escape(stripped)}</p>")
    return "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>" + "\n".join(body) + "</body></html>"
