#!/usr/bin/env python3
"""
daily_news_digest.py

- Fetches RSS feeds.
- Dedupes, ranks by published date.
- Produces deterministic short summaries.
- Writes digest.html (current) and archive/digest-YYYYMMDDHHMMSS.html (archive).
- Writes digest.log for CI artifact debugging.
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
RSS_FEEDS = [
    # --- General / High-Quality News (Centrist / Mainstream) ---
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "http://feeds.reuters.com/reuters/topNews",
    "https://www.theguardian.com/world/rss",
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.economist.com/sections/international/rss.xml",

    # --- Political Spectrum Additions ---
    "https://www.wsj.com/xml/rss/3_7085.xml",
    "https://www.theatlantic.com/feed/all/",
    "https://www.nationalreview.com/feed/",
    "https://www.americanprogress.org/feed/",
    "https://reason.com/feed/",
    "https://www.politico.com/rss/politics08.xml",
    "https://www.foreignaffairs.com/rss.xml",
    "https://theintercept.com/feed/?rss",
    "https://www.foxnews.com/about/rss/",
    "https://www.npr.org/rss/rss.php?id=1001",
    "https://www.project-syndicate.org/feeds/latest",

    # --- Science ---
    "https://www.nature.com/subjects/science.rss",
    "https://www.scientificamerican.com/feed/rss/",

    # --- Technology ---
    "https://www.wired.com/feed/rss",

    # --- Arts & Culture ---
    "https://www.nytimes.com/svc/collections/v1/publish/arts/rss.xml",
    "https://www.theguardian.com/artanddesign/rss",
    "https://hyperallergic.com/feed/",

    # --- Literature ---
    "https://lithub.com/feed/",
    "https://www.theparisreview.org/blog/feed/",
    "https://www.poetryfoundation.org/rss/articles.xml",
    "https://electricliterature.com/feed/",

    # --- Birdwatching / Nature ---
    "https://ebird.org/news/feed/",
    "https://www.birdguides.com/feed/news/",
    "https://www.audubon.org/rss.xml",

    # --- Knitting & Craft ---
    "https://blog.tincanknits.com/feed/",
    "https://www.interweave.com/feed/",

    # --- Movies & Film ---
    "https://www.nytimes.com/svc/collections/v1/publish/entertainment/movies/rss.xml",
    "https://www.empireonline.com/rss/all.xml",
    "https://www.indiewire.com/feed/",
    "https://screenrant.com/feed/"
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

# ---------------- Presentation: simple centered layout ----------------
def build_html_digest(items, err_message=None):
    """
    Builds a simple centered page.
    Includes latest articles and a short list of recent archive filenames (if any).
    """
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    # build articles
    articles = []
    for i, it in enumerate(items[:MAX_ITEMS], start=1):
        t = html.escape(it.get("title", "No title"))
        link = html.escape(it.get("link", "#"))
        src = html.escape(it.get("source", ""))
        pub = it.get("published")
        pub_txt = pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if pub else ""
        summ = short_summary_from_snippet(it.get("summary", "")) or (t + ".")
        article_html = (
            f"<article class='news-item' id='item-{i}'>"
            f"<h3 class='news-title'><a href='{link}' target='_blank' rel='noopener'>{t}</a></h3>"
            f"<div class='meta'>{src} · {pub_txt}</div>"
            f"<p class='summary'>{html.escape(summ)}</p>"
            f"</article>"
        )
        articles.append(article_html)
    articles_html = "\n".join(articles) if articles else "<p>No items found.</p>"

    # build archives list (latest 10)
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

    # minimal CSS matching your monospace, centered, max-width styling
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
.news-item{{padding:12px 0;border-bottom:1px solid #eee}}
.news-title{{margin:0;font-size:1.05rem}}
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
    <main class="news-list">
      {articles_html}
    </main>

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
        for url in RSS_FEEDS:
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
                        "published": pub_dt
                    })
            except Exception as e2:
                log_lines.append(f"FeedError [{url}]: {type(e2).__name__}: {e2}")

        # dedupe & rank
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
