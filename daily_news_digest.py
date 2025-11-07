#!/usr/bin/env python3
"""
daily_news_digest.py

- Fetches RSS feeds.
- Dedupes, ranks by published date.
- Produces deterministic short summaries.
- Writes docs/digest.html (current) and docs/archive/digest-YYYYMMDDHHMMSS.html (archive).
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

def build_html_digest(items, err_message=None):
    now = datetime.now(timezone.utc).astimezone().isoformat()
    header = (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Daily News Digest</title></head><body>"
        f"<h1>Daily News Digest</h1><div>Last updated: {html.escape(now)}</div>"
    )
    if err_message:
        header += (
            "<div style='color:#b00;background:#fee;padding:8px;border:1px solid #fbb;margin:10px 0'>"
            f"{html.escape(err_message)}</div>"
        )
    rows = []
    for it in items:
        t = html.escape(it.get("title", "No title"))
        link = html.escape(it.get("link", "#"))
        src = html.escape(it.get("source", ""))
        pub = it.get("published")
        pub_txt = pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if pub else ""
        summ = short_summary_from_snippet(it.get("summary", "")) or (t + ".")
        rows.append(
            f"<div style='padding:12px 0;border-bottom:1px solid #eee'>"
            f"<div style='font-weight:600'><a href='{link}' target='_blank' rel='noopener'>{t}</a></div>"
            f"<div style='color:#777;font-size:.9rem'>{src} · {pub_txt}</div>"
            f"<div style='margin-top:6px'>{html.escape(summ)}</div></div>"
        )
    footer = "<div style='color:#666;margin-top:1rem'>Generated automatically.</div></body></html>"
    return header + "\n".join(rows) + footer

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
