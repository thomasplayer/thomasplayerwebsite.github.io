#!/usr/bin/env python3
"""
Hardened daily_news_digest.py

Always writes:
 - docs/digest.html
 - digest.log

Defers risky imports. Writes minimal error page and log on any failure.
Exits with status 0 so CI can upload artifacts for debugging.
"""

import os
import sys
import hashlib
import re
import html
import calendar
from datetime import datetime, timezone

# Config
RSS_FEEDS = [
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "http://feeds.reuters.com/reuters/topNews",
    "https://www.theguardian.com/world/rss"
]
MAX_ITEMS = 10
OUT_PATH = "docs/digest.html"
LOG_PATH = "digest.log"

def safe_write(path, text):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception as e:
        # best-effort fallback: try writing to current directory
        try:
            with open(os.path.basename(path), "w", encoding="utf-8") as f:
                f.write(text)
            return True
        except Exception:
            return False

def make_error_html(message):
    now = datetime.now(timezone.utc).astimezone().isoformat()
    safe_msg = html.escape(message)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Digest Error</title></head><body>
<h1>Daily News Digest — Error</h1>
<p>Time: {html.escape(now)}</p>
<div style="color:#b00;background:#fee;padding:8px;border:1px solid #fbb">{safe_msg}</div>
<p>The script failed to generate the digest. See <code>digest.log</code> for details.</p>
</body></html>"""

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
    header = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Daily News Digest</title></head><body><h1>Daily News Digest</h1><div>Last updated: {html.escape(now)}</div>"""
    if err_message:
        header += f'<div style="color:#b00;background:#fee;padding:8px;border:1px solid #fbb;margin:10px 0">{html.escape(err_message)}</div>'
    rows = []
    for it in items:
        t = html.escape(it.get("title","No title"))
        link = html.escape(it.get("link","#"))
        src = html.escape(it.get("source",""))
        pub = it.get("published")
        pub_txt = pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if pub else ""
        summ = short_summary_from_snippet(it.get("summary","")) or (t + ".")
        rows.append(f'<div style="padding:12px 0;border-bottom:1px solid #eee"><div style="font-weight:600"><a href="{link}" target="_blank" rel="noopener">{t}</a></div><div style="color:#777;font-size:.9rem">{src} · {pub_txt}</div><div style="margin-top:6px">{html.escape(summ)}</div></div>')
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

def run():
    log_lines = []
    items = []
    err = None

    # Defer import and guard
    try:
        import feedparser
        from feedparser.util import mktime_tz
    except Exception as e:
        err = f"ImportError: {type(e).__name__}: {e}"
        log_lines.append("ERROR: " + err)
        # write minimal files and return
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
                            pub_dt = datetime.fromtimestamp(int(mktime_tz(tp)), tz=timezone.utc)
                        except Exception:
                            try:
                                pub_dt = datetime.fromtimestamp(int(calendar.timegm(tp)), tz=timezone.utc)
                            except Exception:
                                pub_dt = datetime.fromtimestamp(0, tz=timezone.utc)
                    else:
                        pub_dt = None
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
                if a > b:
                    seen[u] = it
        items = sorted(list(seen.values()), key=lambda x: (x.get("published") or datetime.fromtimestamp(0, tz=timezone.utc)), reverse=True)[:MAX_ITEMS]

        html_body = build_html_digest(items)
        ok = safe_write(OUT_PATH, html_body)
        log_lines.append(f"wrote:{OUT_PATH} ok={ok}")
        log_lines.append(f"items:{len(items)}")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        log_lines.append("ERROR: " + err)
        # write error page
        safe_write(OUT_PATH, make_error_html(err))
    finally:
        safe_log_write(log_lines)
    return 0

if __name__ == "__main__":
    code = run()
    # ensure exit 0 so CI continues and artifacts upload
    try:
        sys.exit(code)
    except SystemExit:
        pass
    sys.exit(0)
