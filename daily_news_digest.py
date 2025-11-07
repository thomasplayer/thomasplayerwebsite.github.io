#!/usr/bin/env python3
"""
daily_news_digest.py

- Fetches RSS feeds (each feed tagged with a section).
- Dedupes, ranks by published date.
- Produces deterministic short summaries.
- Writes digest.html (current) and archive/digest-YYYYMMDDHHMMSS.html (archive).
- Writes digest.log for CI artifact debugging.
- Groups headlines in the HTML by section.
- Uses calendar.timegm() for struct_time -> epoch conversion.
- Exits 0 so CI can upload artifacts even on failure.
"""

import os
import sys
import hashlib
import re
import html
import calendar
from datetime import datetime, timezone

# ---------------- CONFIG ----------------
# List of (feed_url, section_name)
RSS_FEEDS = [
    # General / High-Quality News
    ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "News"),
    ("http://feeds.reuters.com/reuters/topNews", "News"),
    ("https://www.theguardian.com/world/rss", "News"),
    ("http://feeds.bbci.co.uk/news/world/rss.xml", "News"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "News"),
    ("https://www.economist.com/sections/international/rss.xml", "News"),

    # Political / Opinion
    ("https://www.wsj.com/xml/rss/3_7085.xml", "Politics"),
    ("https://www.theatlantic.com/feed/all/", "Politics"),
    ("https://www.nationalreview.com/feed/", "Politics"),
    ("https://www.americanprogress.org/feed/", "Politics"),
    ("https://reason.com/feed/", "Politics"),
    ("https://www.politico.com/rss/politics08.xml", "Politics"),
    ("https://www.foreignaffairs.com/rss.xml", "Politics"),
    ("https://theintercept.com/feed/?rss", "Politics"),
    ("https://www.foxnews.com/about/rss/", "Politics"),
    ("https://www.npr.org/rss/rss.php?id=1001", "Politics"),
    ("https://www.project-syndicate.org/feeds/latest", "Politics"),

    # Science
    ("https://www.nature.com/subjects/science.rss", "Science"),
    ("https://www.scientificamerican.com/feed/rss/", "Science"),

    # Technology
    ("https://www.wired.com/feed/rss", "Technology"),

    # Arts & Culture
    ("https://www.nytimes.com/svc/collections/v1/publish/arts/rss.xml", "Arts"),
    ("https://www.theguardian.com/artanddesign/rss", "Arts"),
    ("https://hyperallergic.com/feed/", "Arts"),

    # Literature
    ("https://lithub.com/feed/", "Literature"),
    ("https://www.theparisreview.org/blog/feed/", "Literature"),
    ("https://www.poetryfoundation.org/rss/articles.xml", "Literature"),
    ("https://electricliterature.com/feed/", "Literature"),

    # Nature / Birdwatching
    ("https://ebird.org/news/feed/", "Nature"),
    ("https://www.birdguides.com/feed/news/", "Nature"),
    ("https://www.audubon.org/rss.xml", "Nature"),

    # Crafts
    ("https://blog.tincanknits.com/feed/", "Crafts"),
    ("https://www.interweave.com/feed/", "Crafts"),

    # Film
    ("https://www.nytimes.com/svc/collections/v1/publish/entertainment/movies/rss.xml", "Film"),
    ("https://www.empireonline.com/rss/all.xml", "Film"),
    ("https://www.indiewire.com/feed/", "Film"),
    ("https://screenrant.com/feed/", "Film"),
]

MAX_ITEMS = 50
OUT_PATH = "digest.html"
ARCHIVE_DIR = "archive"
LOG_PATH = "digest.log"
# ----------------------------------------

def safe_write(path, text):
    """Write text to path; attempt fallback to basename if dir write fails."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception:
        try:
            with open(os.path.basename(path), "w", encoding="utf-8") as f:
                f.write(text)
            return True
        except Exception:
            return False

def make_error_html(message):
    now = datetime.now(timezone.utc).astimezone().isoformat()
    safe_msg = html.escape(message)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Digest Error</title></head>"
        "<body><h1>Daily News Digest — Error</h1>"
        f"<p>Time: {html.escape(now)}</p>"
        f"<div style='color:#b00;background:#fee;padding:8px;border:1px solid #fbb'>{safe_msg}</div>"
        "<p>The script failed to generate the digest. See <code>digest.log</code> for details.</p>"
        "</body></html>"
    )

def uid_for(link, title=""):
    return hashlib.sha1(((link or "") + (title or "")).encode("utf-8")).hexdigest()

def short_summary_from_snippet(snippet):
    if not snippet:
        return ""
    text = re.sub(r"<[^>]+>", " ", snippet)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    short = " ".join(sentences[:2])
    if len(short) > 240:
        short = short[:237].rsplit(" ", 1)[0] + "..."
    return short

# ---------------- Presentation: simple centered layout with sections ----------------
def build_html_digest(items, err_message=None):
    """
    Build a centered page. Group items by their 'section' field.
    """
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    # Group items by section. Items are expected to have a 'section' key.
    sections = {}
    for it in items:
        sec = it.get("section") or "Other"
        sections.setdefault(sec, []).append(it)

    # Sort sections alphabetically but keep 'News' first if present
    section_keys = sorted([k for k in sections.keys() if k != "News"])
    if "News" in sections:
        section_keys = ["News"] + section_keys

    # Build HTML for each section
    section_blocks = []
    for sec in section_keys:
        sec_items = sections.get(sec, [])
        if not sec_items:
            continue
        # within each section, sort by published desc
        sec_items.sort(key=lambda x: (x.get("published") or datetime.fromtimestamp(0, tz=timezone.utc)), reverse=True)
        items_html = []
        for i, it in enumerate(sec_items, start=1):
            t = html.escape(it.get("title", "No title"))
            link = html.escape(it.get("link", "#"))
            src = html.escape(it.get("source", ""))
            pub = it.get("published")
            pub_txt = pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if pub else ""
            summ = short_summary_from_snippet(it.get("summary", "")) or (t + ".")
            items_html.append(
                f"<article class='news-item'><h3 class='news-title'><a href='{link}' target='_blank' rel='noopener'>{t}</a></h3>"
                f"<div class='meta'>{src} · {pub_txt}</div>"
                f"<p class='summary'>{html.escape(summ)}</p></article>"
            )
        section_html = f"<section class='section'><h2 class='section-title'>{html.escape(sec)}</h2>" + "\n".join(items_html) + "</section>"
        section_blocks.append(section_html)

    sections_html = "\n".join(section_blocks) if section_blocks else "<p>No items found.</p>"

    # archives (latest 10)
    archives_html = ""
    try:
        if os.path.isdir(ARCHIVE_DIR):
            files = [f for f in os.listdir(ARCHIVE_DIR) if f.startswith("digest-") and f.endswith(".html")]
            files.sort(reverse=True)
            if files:
                links = "\n".join(f"<li><a href='{html.escape(os.path.join(ARCHIVE_DIR, f))}'>{html.escape(f)}</a></li>" for f in files[:10])
                archives_html = f"<h4>Archive</h4><ul class='archive'>{links}</ul>"
    except Exception:
        archives_html = ""

    error_block = f"<div class='error'>{html.escape(err_message)}</div>" if err_message else ""

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily News Digest</title>
<style>
:root {{
  --fg:#111;
  --muted:#666;
  --maxw:1000px;
  --pad:28px;
}}
html,body{{margin:0;padding:0;height:100%;background:#fff;color:var(--fg);font-family:ui-monospace,monospace;}}
.container{{max-width:var(--maxw);margin:36px auto;padding:var(--pad);box-sizing:border-box;}}
.header{{margin-bottom:12px;}}
.header h1{{margin:0;font-size:20px}}
.header .time{{color:var(--muted);font-size:0.95rem;margin-top:6px}}
.error{{color:#b00;background:#fee;padding:8px;border:1px solid #fbb;margin:10px 0}}
.section{{margin-top:18px}}
.section-title{{margin:0 0 8px 0;font-size:1.1rem}}
.news-item{{padding:10px 0;border-bottom:1px solid #eee}}
.news-title{{margin:0;font-size:1.02rem}}
.news-title a{{color:var(--fg);text-decoration:underline;text-underline-offset:2px}}
.meta{{color:var(--muted);font-size:0.9rem;margin-top:6px}}
.summary{{margin-top:8px;color:#222}}
.archive{{margin-top:14px;padding-left:1rem;color:var(--muted)}}
@media(max-width:800px){{
  .container{{padding:18px;margin:18px}}
}}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Daily News</h1>
      <div class="time">Last updated: {html.escape(now_iso)}</div>
    </div>

    {error_block}
    {sections_html}

    {archives_html}

    <footer style="margin-top:18px;color:var(--muted);font-size:0.9rem">
      Generated automatically. Source list editable in <code>daily_news_digest.py</code>.
    </footer>
  </div>
</body>
</html>"""
    return page

# ---------------- Utility / IO ----------------
def safe_log_write(lines):
    txt = "\n".join(lines) + "\n"
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(txt)
        return True
    except Exception:
        try:
            with open(os.path.basename(LOG_PATH), "w", encoding="utf-8") as f:
                f.write(txt)
            return True
        except Exception:
            return False

def timestamp_string():
    """UTC timestamp formatted as YYYYMMDDHHMMSS."""
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")

def run():
    log_lines = []
    items = []
    err = None

    # Defer import
    try:
        import feedparser
    except Exception as e:
        err = f"ImportError: {type(e).__name__}: {e}"
        log_lines.append("ERROR: " + err)
        safe_write(OUT_PATH, make_error_html(err))
        safe_log_write(log_lines)
        return 0

    # Fetch feeds
    try:
        # prepare mapping from feed url to section for quick lookup
        feed_section_map = {url: section for url, section in RSS_FEEDS}

        for url, section in RSS_FEEDS:
            try:
                d = feedparser.parse(url)
                source = d.feed.get("title") or url
                for e in d.entries:
                    link = e.get("link") or ""
                    title = e.get("title") or ""
                    summary = e.get("summary") or e.get("description") or ""
                    tp = e.get("published_parsed") or e.get("updated_parsed")
                    if tp:
                        try:
                            pub_dt = datetime.fromtimestamp(int(calendar.timegm(tp)), tz=timezone.utc)
                        except Exception:
                            pub_dt = datetime.fromtimestamp(0, tz=timezone.utc)
                    else:
                        pub_dt = None
                        for k in ("published", "updated"):
                            v = e.get(k)
                            if v:
                                try:
                                    pub_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                                    break
                                except Exception:
                                    pass
                    items.append({
                        "uid": uid_for(link, title),
                        "title": title.strip(),
                        "link": link.strip(),
                        "summary": summary.strip(),
                        "source": source,
                        "published": pub_dt,
                        "section": feed_section_map.get(url, "Other")
                    })
            except Exception as e2:
                log_lines.append(f"FeedError [{url}]: {type(e2).__name__}: {e2}")

        # dedupe & rank (chronological by default)
        seen = {}
        for it in items:
            u = it["uid"]
            if u not in seen:
                seen[u] = it
            else:
                a = it.get("published") or datetime.fromtimestamp(0, tz=timezone.utc)
                b = seen[u].get("published") or datetime.fromtimestamp(0, tz=timezone.utc)
                if a and b:
                    if a > b:
                        seen[u] = it
                elif a and not b:
                    seen[u] = it

        items = sorted(
            list(seen.values()),
            key=lambda x: (x.get("published") or datetime.fromtimestamp(0, tz=timezone.utc)),
            reverse=True
        )[:MAX_ITEMS]

        # Build current HTML
        html_body = build_html_digest(items)
        wrote_current = safe_write(OUT_PATH, html_body)
        log_lines.append(f"wrote:{OUT_PATH} ok={wrote_current}")
        log_lines.append(f"items:{len(items)}")

        # Write archive copy with UTC timestamp
        ts = timestamp_string()
        archive_name = f"digest-{ts}.html"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        # ensure archive dir exists
        try:
            os.makedirs(ARCHIVE_DIR, exist_ok=True)
        except Exception:
            pass
        wrote_archive = safe_write(archive_path, html_body)
        log_lines.append(f"archive:{archive_path} ok={wrote_archive}")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        log_lines.append("ERROR: " + err)
        safe_write(OUT_PATH, make_error_html(err))
    finally:
        safe_log_write(log_lines)
    return 0

if __name__ == "__main__":
    code = run()
    try:
        sys.exit(code)
    except SystemExit:
        pass
    sys.exit(0)
