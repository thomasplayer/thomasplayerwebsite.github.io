#!/usr/bin/env python3
"""
Simplified daily_news_digest.py

Keeps original features:
- fetch RSS feeds (tagged by section)
- consider items from last 24 hours
- score items, enforce per-section caps and overall MAX_ITEMS
- write digest.html, archive/digest-YYYYMMDDHHMMSS.html, and digest.log
- deterministic, no external AI
- renders local times in Europe/London
"""

from datetime import datetime, timezone, timedelta
import os
import math
import hashlib
import html
import re

# Prefer zoneinfo for explicit timezone handling
try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/London")
except Exception:
    LOCAL_TZ = datetime.now().astimezone().tzinfo

# -------- CONFIG ----------
RSS_FEEDS = [
    # News
    ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "News"),
    ("http://feeds.bbci.co.uk/news/world/rss.xml", "News"),
    ("http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/front_page/rss.xml", "News"),
    ("https://feeds.washingtonpost.com/rss/world", "News"),
    ("https://www.theguardian.com/world/rss", "News"),
    ("https://www.theguardian.com/uk-news/rss", "News"),
    ("https://www.lemonde.fr/rss/une.xml", "News"),
    ("https://www.oxfordmail.co.uk/news/rss/", "News"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "News"),
    ("https://www.newyorker.com/feed/news", "News"),

    # Politics
    ("https://www.theguardian.com/politics/rss", "Politics"),
    ("https://feeds.feedburner.com/guidofawkes", "Politics"),
    ("https://tribunemag.co.uk/feed/", "Politics"),
    ("https://theintercept.com/feed/?rss", "Politics"),
    ("https://www.foreignaffairs.com/rss.xml", "Politics"),

    # Culture
    ("http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/technology/rss.xml", "Culture"),
    ("https://www.theverge.com/rss/index.xml", "Culture"),
    ("https://screenrant.com/feed/", "Culture"),
    ("https://www.empireonline.com/rss/all.xml", "Culture"),
    ("https://www.themarginalian.org/rss/", "Culture"),
    ("https://aeon.co/feed", "Culture"),
    ("https://pudding.cool/rss.xml", "Culture"),

    # Science
    ("https://www.nature.com/nature.rss", "Science"),
    ("https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science", "Science"),
    ("https://www.chemistryworld.com/413.rss", "Science"),
    ("https://www.sciencedaily.com/rss/top/science.xml", "Science"),

    # Nature
    ("https://oxonbirding.blogspot.com/feeds/posts/default?alt=rss", "Nature"),
    ("https://tmbirding.blogspot.com/feeds/posts/default?alt=rss", "Nature"),
]
MAX_ITEMS = 100
SECTION_CAPS = {"News": 15}
DEFAULT_SECTION_CAP = 10
OUT_PATH = "digest.html"
ARCHIVE_DIR = "archive"
LOG_PATH = "digest.log"
HALF_LIFE_HOURS = 8.0

# lightweight priority and keyword boosts (kept, simplified)
SOURCE_PRIORITY = {
#    "bbc": 1.05,
#    "guardian": 1.05,
#    "nature": 1.1,
}
KEYWORD_BOOSTS = {
    "star wars": 1.5,
    "the simpsons": 1.5,
#    "oxford": 2.0,
#    "knitting": 2.0,
#    "bird": 2.0,
    "gluten": 1.5,
#    "climate": 2.0,
#    "energy": 1.6,
#    "ai": 2.0,
#    "economy": 1.4,
#    "ukraine": 1.8,
}

# ---------------- utilities ----------------
def safe_write(path, text):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
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

def uid_for(link, title=""):
    return hashlib.sha1((link or "" + (title or "")).encode("utf-8")).hexdigest()



def short_summary(snippet, max_chars=500):
    if not snippet:
        return ""

    # Replace paragraph-like breaks with a period
    s = re.sub(r"</p>|<br\s*/?>|\n+", ".", snippet, flags=re.IGNORECASE)
    # Remove any other HTML tags
    s = re.sub(r"<[^>]+>", " ", s)
    # Normalize whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Replace accidental multiple periods (except ellipses)
    # e.g., "Hello.." -> "Hello.", but "Hello..." stays "Hello..."
    s = re.sub(r"(?<!\.)\.\.(?!\.)", ".", s)
    # If already short enough, return
    if len(s) <= max_chars:
        return s
    # Try to cut at sentence boundary
    parts = re.split(r'(?<=[.!?])\s+', s)
    out = ""
    for p in parts:
        candidate = p if not out else out + " " + p
        if len(candidate) <= max_chars:
            out = candidate
        else:
            break
    # If no sentence fits, truncate cleanly at a word boundary
    if not out:
        out = s[:max_chars].rsplit(" ", 1)[0] + "..."
    # Final cleanup for double periods again (post-truncation)
    out = re.sub(r"(?<!\.)\.\.(?!\.)", ".", out)
    return out

def format_top_updated(now_utc):
    try:
        local = now_utc.astimezone(LOCAL_TZ)
    except Exception:
        local = now_utc.astimezone()
    ampm = "AM" if local.hour < 12 else "PM"
    return f"Updated: {ampm} {local.strftime('%A %-d %B %Y')}" if os.name != "nt" else f"Updated: {ampm} {local.strftime('%A %#d %B %Y')}"

def format_pub_local(pub_dt):
    if not pub_dt:
        return ""
    try:
        local = pub_dt.astimezone(LOCAL_TZ)
    except Exception:
        local = pub_dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M %Z")

# ---------------- scoring ----------------
def source_score(source):
    if not source:
        return 1.0
    s = source.lower()
    for k, v in SOURCE_PRIORITY.items():
        if k in s:
            return v
    return 1.0

def recency_score(published_dt, now=None):
    if not published_dt:
        return 0.0
    now = now or datetime.now(timezone.utc)
    age = max(0.0, (now - published_dt).total_seconds())
    half = HALF_LIFE_HOURS * 3600.0
    return math.pow(2.0, -age / half)

def keyword_score(text):
    if not text:
        return 0.0
    t = text.lower()
    s = 0.0
    for k, boost in KEYWORD_BOOSTS.items():
        if k in t:
            s += boost
    return s

def title_signal(title):
    if not title:
        return 0.0
    # if any(ch.isdigit() for ch in title):
        # return 1.0
    return 0.2 if len(title.split()) <= 8 else 0.0

def score_item(item, now=None, dup_count=1):
    now = now or datetime.now(timezone.utc)
    s = (1.0 * source_score(item.get("source"))
         + 1.6 * recency_score(item.get("published"), now=now)
         + 2.0 * keyword_score(item.get("title","") + " " + item.get("summary",""))
         + 0.6 * title_signal(item.get("title",""))
         + 0.25 * min(1.0, len(item.get("summary","")) / 500.0)
         + 0.9 * math.log1p(dup_count))
    return s

# ---------------- HTML builder (preserve layout) ----------------
def build_html_digest(items_by_section, err_message=None):
    now_utc = datetime.now(timezone.utc)
    updated_label = format_top_updated(now_utc)

    # order: News, Politics, then alphabetical
    keys = list(items_by_section.keys())
    others = sorted(k for k in keys if k not in ("News", "Politics"))
    order = []
    if "News" in keys:
        order.append("News")
    if "Politics" in keys:
        order.append("Politics")
    order += others

    section_blocks = []
    for sec in order:
        sec_items = items_by_section.get(sec, [])
        if not sec_items:
            continue
        blocks = []
        for it in sec_items:
            t = html.escape(it.get("title","No title"))
            link = html.escape(it.get("link","#"))
            src = html.escape(it.get("source",""))
            pub = it.get("published")
            pub_txt = format_pub_local(pub) if pub else ""
            summ = short_summary(it.get("summary",""), max_chars=500) or (t + ".")
            blocks.append(
                "<article class='news-item'>"
                f"<h3 class='news-title'><a href='{link}' target='_blank' rel='noopener'>{t}</a></h3>"
                f"<p class='summary'>{html.escape(summ)}</p>"
                f"<div class='meta'>{src} | {html.escape(pub_txt)}</div>"
                "</article>"
            )
        section_html = (
            f"<section class='section'>"
            f"<h2 class='section-title'>{html.escape(sec)}</h2>"
            f"<div class='section-body'>"
            + "\n".join(blocks) +
            f"</div></section>"
        )
        section_blocks.append(section_html)

    sections_block = "\n".join(section_blocks) if section_blocks else "<p>No items found.</p>"

    # archives listing (latest 10) -- formatted link text from filename: HH:MM:SS DD Month YYYY (local Europe/London)
    archives_html = ""
    try:
        if os.path.isdir(ARCHIVE_DIR):
            files = [f for f in os.listdir(ARCHIVE_DIR) if f.startswith("digest-") and f.endswith(".html")]
            files.sort(reverse=True)
            if files:
                links = []
                for f in files[:10]:
                    display_time = None
                    try:
                        # filename pattern: digest-YYYYMMDDHHMMSS.html
                        ts_str = f.removeprefix("digest-").removesuffix(".html")
                        dt = datetime.strptime(ts_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                        # convert to local timezone for display
                        try:
                            local_dt = dt.astimezone(LOCAL_TZ)
                        except Exception:
                            local_dt = dt.astimezone()
                        display_time = local_dt.strftime("%H:%M:%S %d %B %Y")
                    except Exception:
                        display_time = None
                    link_href = html.escape(os.path.join(ARCHIVE_DIR, f))
                    link_text = html.escape(display_time if display_time else f)
                    links.append(f"<li><a href='{link_href}'>{link_text}</a></li>")
                archives_html = f"<h4>Archive</h4><ul class='archive'>{''.join(links)}</ul>"
    except Exception:
        archives_html = ""

    error_block = f"<div class='error'>{html.escape(err_message)}</div>" if err_message else ""

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Daily News Digest</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>

    <header class="digest-header">
      <h1>Daily News</h1>
      <div class="muted time">{html.escape(updated_label)}</div>
    </header>
<main>
    {error_block}

    {sections_block}

    <div class="archive muted">
      {archives_html}
    </div>

    <footer class="muted" style="margin-top:18px;font-size:0.9rem">
      Generated automatically.
    </footer>
  </main>
</body>
</html>"""
    return page

# ---------------- main ----------------
def run():
    log_lines = []
    items = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    log_lines.append(f"cutoff:{cutoff.isoformat()}")

    try:
        import feedparser
    except Exception as e:
        err = f"ImportError: {type(e).__name__}: {e}"
        log_lines.append("ERROR: " + err)
        safe_write(OUT_PATH, build_html_digest({}, err_message=err))
        safe_write(LOG_PATH, "\n".join(log_lines) + "\n")
        return 1

    # collect items from feeds
    for url, section in RSS_FEEDS:
        try:
            doc = feedparser.parse(url)
            source = doc.feed.get("title") or url
            for e in doc.entries:
                link = (e.get("link") or "").strip()
                title = (e.get("title") or "").strip()
                summary = (e.get("summary") or e.get("description") or "").strip()
                # Use feedparser's parsed time when present, else try ISO8601 if available
                tp = e.get("published_parsed") or e.get("updated_parsed")
                pub_dt = None
                if tp:
                    try:
                        # feedparser gives struct_time-like
                        import calendar
                        pub_dt = datetime.fromtimestamp(calendar.timegm(tp), tz=timezone.utc)
                    except Exception:
                        pub_dt = None
                else:
                    v = e.get("published") or e.get("updated")
                    if v:
                        try:
                            pub_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                            if pub_dt.tzinfo is None:
                                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            pub_dt = None
                if not pub_dt or pub_dt < cutoff:
                    continue
                uid = uid_for(link, title)
                items.append({
                    "uid": uid,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "source": source,
                    "published": pub_dt,
                    "section": section
                })
        except Exception as fe:
            log_lines.append(f"FeedError [{url}]: {type(fe).__name__}: {fe}")

    if not items:
        log_lines.append("info: no items within 24 hours")

    # dedupe by uid, keep newest instance and count duplicates
    grouped = {}
    for it in items:
        u = it["uid"]
        if u not in grouped:
            grouped[u] = {"item": it, "count": 1}
        else:
            existing = grouped[u]["item"]
            grouped[u]["count"] += 1
            # keep the later published one
            if it.get("published") and existing.get("published") and it["published"] > existing["published"]:
                grouped[u]["item"] = it

    # score and sort
    scored = []
    for uid, info in grouped.items():
        it = info["item"]
        cnt = info["count"]
        sc = score_item(it, now=now, dup_count=cnt)
        scored.append((sc, it, cnt))
    scored.sort(key=lambda x: x[0], reverse=True)

    # select top with section caps and overall cap
    items_by_section = {}
    total_selected = 0
    for sc, it, cnt in scored:
        if total_selected >= MAX_ITEMS:
            break
        sec = it.get("section") or "Other"
        cap = SECTION_CAPS.get(sec, DEFAULT_SECTION_CAP)
        bucket = items_by_section.setdefault(sec, [])
        if len(bucket) >= cap:
            continue
        bucket.append(it)
        total_selected += 1

    html_page = build_html_digest(items_by_section)
    ok = safe_write(OUT_PATH, html_page)
    log_lines.append(f"wrote:{OUT_PATH} ok={ok}")
    log_lines.append(f"selected_items:{total_selected} total_candidates:{len(scored)}")

    # archive
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    archive_path = os.path.join(ARCHIVE_DIR, f"digest-{ts}.html")
    ok2 = safe_write(archive_path, html_page)
    log_lines.append(f"archive:{archive_path} ok={ok2}")

    # write log
    safe_write(LOG_PATH, "\n".join(log_lines) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
