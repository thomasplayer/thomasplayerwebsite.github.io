#!/usr/bin/env python3
"""
daily_news_digest.py - fixed for feedparser v6+ and robust logging/artifact creation.
"""

from datetime import datetime, timezone
import os
import hashlib
import re
import html
import feedparser
from feedparser.util import mktime_tz   # safe location for mktime_tz
import calendar

# --- CONFIGURE ---
RSS_FEEDS = [
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "http://feeds.reuters.com/reuters/topNews",
    "https://www.theguardian.com/world/rss"
]
MAX_ITEMS = 10
OUT_PATH = "docs/digest.html"
LOG_PATH = "digest.log"

# --- Utilities ---
def uid_for(link, title=""):
    s = (link or "") + (title or "")
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def parse_published(entry):
    # feedparser returns a time.struct_time in published_parsed
    tp = entry.get("published_parsed") or entry.get("updated_parsed")
    if tp:
        try:
            # feedparser.util.mktime_tz -> seconds since epoch (UTC)
            return datetime.fromtimestamp(int(mktime_tz(tp)), tz=timezone.utc)
        except Exception:
            # fallback to calendar.timegm which expects a 9-tuple struct_time (UTC)
            try:
                return datetime.fromtimestamp(int(calendar.timegm(tp)), tz=timezone.utc)
            except Exception:
                return datetime.fromtimestamp(0, tz=timezone.utc)
    # fallback: string fields
    for k in ("published", "updated"):
        v = entry.get(k)
        if v:
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except Exception:
                pass
    return datetime.fromtimestamp(0, tz=timezone.utc)

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

# --- Fetch & normalize ---
def fetch_rss(feeds):
    items = []
    for url in feeds:
        d = feedparser.parse(url)
        source = d.feed.get("title") or url
        for e in d.entries:
            link = e.get("link") or ""
            title = e.get("title") or ""
            summary = e.get("summary") or e.get("description") or ""
            published_dt = parse_published(e)
            items.append({
                "uid": uid_for(link, title),
                "title": title.strip(),
                "link": link.strip(),
                "summary": summary.strip(),
                "source": source,
                "published": published_dt
            })
    return items

def dedupe_and_rank(items, max_items=MAX_ITEMS):
    seen = {}
    for it in items:
        if it["uid"] not in seen:
            seen[it["uid"]] = it
        else:
            if it["published"] > seen[it["uid"]]["published"]:
                seen[it["uid"]] = it
    lst = list(seen.values())
    lst.sort(key=lambda x: x["published"], reverse=True)
    return lst[:max_items]

def build_html_digest(items, err_message=None):
    now = datetime.now(timezone.utc).astimezone().isoformat()
    header = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily News Digest</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,"Helvetica Neue",Arial;max-width:800px;margin:2rem auto;color:#111;padding:0 1rem}}
h1{{font-size:1.25rem;margin-bottom:.25rem}}
.time{{color:#666;font-size:.9rem;margin-bottom:1rem}}
.article{{padding:12px 0;border-bottom:1px solid #eee}}
.title{{font-weight:600;font-size:1rem;margin:0}}
.meta{{color:#777;font-size:.85rem;margin-top:6px}}
.summary{{color:#333;margin-top:6px}}
.footer{{color:#666;font-size:.9rem;margin-top:1.25rem}}
a{{color:inherit;text-decoration:none}}
a:hover{{text-decoration:underline}}
.error{{color:#b00;background:#fee;padding:8px;border:1px solid #fbb;margin-bottom:1rem}}
</style>
</head>
<body>
<h1>Daily News Digest</h1>
<div class="time">Last updated: {html.escape(now)}</div>
"""
    if err_message:
        header += f'<div class="error">Error generating digest: {html.escape(err_message)}</div>\n'
    rows = []
    for it in items:
        t = html.escape(it["title"] or "No title")
        link = html.escape(it["link"] or "#")
        src = html.escape(it.get("source", ""))
        pub = it["published"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        summ = short_summary_from_snippet(it.get("summary","")) or (t + ".")
        summ = html.escape(summ)
        rows.append(f"""
  <div class="article">
    <div class="title"><a href="{link}" target="_blank" rel="noopener">{t}</a></div>
    <div class="meta">{src} · {pub}</div>
    <div class="summary">{summ}</div>
  </div>
""")
    footer = """
<div class="footer">Generated automatically. Source list editable in <code>daily_news_digest.py</code>.</div>
</body>
</html>"""
    return header + "\n".join(rows) + footer

def write_site_page(html_body, out_path=OUT_PATH):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_body)
    return os.path.abspath(out_path)

def write_log(msg_lines, path=LOG_PATH):
    try:
        with open(path, "w", encoding="utf-8") as f:
            for line in msg_lines:
                f.write(line + "\n"
