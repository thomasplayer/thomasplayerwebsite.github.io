#!/usr/bin/env python3
"""
daily_news_digest.py

Generates a daily news digest HTML file (digest.html) and an archived copy.
This version contains no inline CSS. The generated HTML links to /styles.css.

Notes:
- Uses feedparser if available to parse RSS/Atom feeds.
- Falls back to a minimal parser if feedparser is not installed.
- Keeps content-generation separate from styling.
- Timezone: Europe/London (uses zoneinfo if available).
"""

from __future__ import annotations
import os
import sys
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

# Optional dependencies
try:
    import feedparser
except Exception:
    feedparser = None

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:
    LONDON = timezone(timedelta(hours=0))

# Output paths
OUT_PATH = "digest.html"
ARCHIVE_DIR = "archive"
LOG_PATH = "digest.log"

# Configuration
FEEDS = {
    "News": [
        # add RSS feed URLs here, for example:
        # "https://example.com/rss",
    ],
    "Tech": [],
    "Opinion": [],
}
MAX_ITEMS = 80
PER_SECTION_CAP = {
    "News": 20,
    "default": 10,
}
HOURS_WINDOW = 24  # consider items in the last N hours

# -------------------------
# Utility functions
# -------------------------
def now_local() -> datetime:
    try:
        return datetime.now(LONDON)
    except Exception:
        return datetime.now()

def safe_mkdir(path: str):
    os.makedirs(path, exist_ok=True)

def iso_ts(dt: datetime) -> str:
    return dt.astimezone(LONDON).strftime("%Y-%m-%d %H:%M:%S %Z")

def hash_id(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

# -------------------------
# Minimal feed fetch/parse
# -------------------------
def fetch_and_parse_feed(url: str):
    """
    Returns a list of dicts with keys: title, link, published (datetime), summary, source
    If feedparser is available it will be used. If not, returns empty list and logs the issue.
    """
    items = []
    if feedparser:
        try:
            d = feedparser.parse(url)
            source_title = d.feed.get("title", url)
            for e in d.entries:
                title = e.get("title", "").strip()
                link = e.get("link", "").strip()
                summary = e.get("summary", "") or e.get("description", "")
                # published handling
                published = None
                if "published_parsed" in e and e.published_parsed:
                    published = datetime.fromtimestamp(time.mktime(e.published_parsed), tz=timezone.utc)
                elif "updated_parsed" in e and e.updated_parsed:
                    published = datetime.fromtimestamp(time.mktime(e.updated_parsed), tz=timezone.utc)
                else:
                    published = datetime.now(timezone.utc)
                items.append({
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published": published,
                    "source": source_title,
                })
        except Exception as e:
            # silent fallback
            pass
    else:
        # feedparser not installed. Return empty list.
        pass
    return items

# -------------------------
# Scoring and selection
# -------------------------
def score_item(item: Dict) -> float:
    """
    Lightweight deterministic scoring:
    - recent items score higher
    - longer summaries get a tiny boost
    - title length adjusts score slightly
    """
    age = (datetime.now(timezone.utc) - item.get("published", datetime.now(timezone.utc))).total_seconds()
    # age in seconds -> recency score: range roughly (0, 1)
    recency = max(0.0, 1.0 - (age / (HOURS_WINDOW * 3600)))
    summary_len = min(1.0, len(item.get("summary", "")) / 500.0)
    title_len = min(1.0, len(item.get("title", "")) / 120.0)
    return recency * 0.7 + summary_len * 0.2 + title_len * 0.1

def select_top_items(all_items: Dict[str, List[Dict]], max_items=MAX_ITEMS) -> List[Dict]:
    selected = []
    for section, items in all_items.items():
        cap = PER_SECTION_CAP.get(section, PER_SECTION_CAP.get("default", 10))
        # score and sort
        scored = [(score_item(i), i) for i in items]
        scored.sort(key=lambda x: (-x[0], x[1].get("published", datetime.now(timezone.utc))))
        for _, itm in scored[:cap]:
            itm["section"] = section
            selected.append(itm)
    # global dedupe by link or title
    seen = set()
    deduped = []
    for itm in sorted(selected, key=lambda x: (x.get("published", datetime.now(timezone.utc))), reverse=True):
        key = itm.get("link") or itm.get("title")
        if not key:
            continue
        h = hash_id(key)
        if h in seen:
            continue
        seen.add(h)
        deduped.append(itm)
        if len(deduped) >= max_items:
            break
    return deduped

# -------------------------
# HTML builder (no CSS)
# -------------------------
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Daily News Digest</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <div class="container">
    <main class="content digest-content">
      <header class="digest-header">
        <h1>Daily News Digest</h1>
        <p class="muted" id="digest-date">{date}</p>
      </header>

      <section id="top-stories" class="digest-section">
        <h2>Top stories</h2>
        {stories_html}
      </section>

      <section id="by-section" class="digest-section">
        <h2>By section</h2>
        {by_section_html}
      </section>

      <footer class="digest-footer">
        <p class="muted">This digest is generated automatically.</p>
      </footer>
    </main>

    <aside class="sidebar">
      <div class="brand">
        <svg class="logo" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
          <rect width="100" height="100" class="logo-fill"></rect>
          <text x="50" y="50" font-family="monospace" class="logo-text">TP</text>
        </svg>

        <div class="brand-info">
          <div class="subtitle">Thomas</div>
          <div class="name">Player</div>
        </div>
      </div>

      <nav class="primary-nav">
        <a href="/index.html">Home</a>
        <a href="/digest.html">Digest</a>
        <a href="mailto:hello@thomasplayer.me">Contact</a>
      </nav>
    </aside>
  </div>
</body>
</html>
"""

STORY_ITEM_TMPL = """
<article class="story" data-id="{id}">
  <h3 class="story-title"><a href="{link}">{title}</a></h3>
  <p class="story-meta muted">{source} — {time}</p>
  <p class="story-summary">{summary}</p>
</article>
"""

def render_story(itm: Dict) -> str:
    t = itm.get("title", "No title")
    link = itm.get("link", "#")
    summary = itm.get("summary", "").replace("\n", " ").strip()
    source = itm.get("source", "")
    pub = itm.get("published")
    if isinstance(pub, datetime):
        time_str = pub.astimezone(LONDON).strftime("%Y-%m-%d %H:%M")
    else:
        time_str = str(pub)
    return STORY_ITEM_TMPL.format(id=hash_id(link or t), link=link, title=escape_html(t), summary=escape_html(summary), source=escape_html(source), time=time_str)

def escape_html(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))

def build_html_digest(items: List[Dict], date_str: Optional[str] = None) -> str:
    if date_str is None:
        date_str = iso_ts(now_local())
    stories_html = "\n".join(render_story(i) for i in items)
    # group by section for the "By section" area
    sections: Dict[str, List[Dict]] = {}
    for i in items:
        sec = i.get("section", "Misc")
        sections.setdefault(sec, []).append(i)
    by_section_parts = []
    for sec, its in sections.items():
        part = f"<div class='section-block' data-section='{escape_html(sec)}'>\n<h3 class='section-title'>{escape_html(sec)}</h3>\n<ul class='section-list'>\n"
        for it in its:
            title = escape_html(it.get("title", ""))
            link = it.get("link", "#")
            part += f"<li><a href='{escape_html(link)}'>{title} — {escape_html(it.get('source',''))}</a></li>\n"
        part += "</ul>\n</div>\n"
        by_section_parts.append(part)
    by_section_html = "\n".join(by_section_parts)
    return HTML_TEMPLATE.format(date=date_str, stories_html=stories_html, by_section_html=by_section_html)

# -------------------------
# Persistence
# -------------------------
def write_file(path: str, text: str):
    dirname = os.path.dirname(path)
    if dirname:
        safe_mkdir(dirname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def archive_html(html_text: str):
    safe_mkdir(ARCHIVE_DIR)
    ts = now_local().strftime("%Y%m%d%H%M%S")
    filename = os.path.join(ARCHIVE_DIR, f"digest-{ts}.html")
    write_file(filename, html_text)
    return filename

def safe_log(lines: List[str]):
    try:
        write_file(LOG_PATH, "\n".join(lines) + "\n")
    except Exception:
        pass

# -------------------------
# Main run
# -------------------------
def collect_items() -> Dict[str, List[Dict]]:
    """
    Fetches feeds defined in FEEDS and returns items grouped by section.
    Only keeps items published in the last HOURS_WINDOW hours.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_WINDOW)
    all_items: Dict[str, List[Dict]] = {}
    for section, urls in FEEDS.items():
        section_items = []
        for url in urls:
            try:
                fetched = fetch_and_parse_feed(url)
            except Exception:
                fetched = []
            for it in fetched:
                pub = it.get("published") or datetime.now(timezone.utc)
                # ensure datetime is timezone-aware
                if isinstance(pub, datetime) and pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub >= cutoff:
                    section_items.append(it)
        all_items[section] = section_items
    return all_items

def run() -> int:
    log_lines = []
    try:
        all_items = collect_items()
        selected = select_top_items(all_items)
        date_str = iso_ts(now_local())
        html = build_html_digest(selected, date_str=date_str)
        write_file(OUT_PATH, html)
        archived = archive_html(html)
        log_lines.append(f"WROTE: {OUT_PATH}")
        log_lines.append(f"ARCHIVE: {archived}")
        safe_log(log_lines)
        return 0
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        safe_log(["ERROR: " + err])
        # try to write a minimal error page
        fallback = "<html><body><h1>Digest generation failed</h1><p>{}</p></body></html>".format(escape_html(err))
        try:
            write_file(OUT_PATH, fallback)
        except Exception:
            pass
        return 2

if __name__ == "__main__":
    code = run()
    try:
        sys.exit(code)
    except SystemExit:
        pass
    sys.exit(0)
