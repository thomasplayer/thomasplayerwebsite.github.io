#!/usr/bin/env python3
"""
daily_news_digest.py

- Fetches RSS feeds (tagged by section).
- Considers items published in the last 24 hours only.
- Scores items by importance and selects top N unique stories.
- Enforces per-section caps: News=20, others=10; overall cap = MAX_ITEMS.
- Writes digest.html (current), archive/digest-YYYYMMDDHHMMSS.html, and digest.log.
- Deterministic. No external AI.
- Updated: local-time rendering (Europe/London) and larger headings, longer summaries.
"""

import os
import sys
import hashlib
import re
import html
import calendar
import math
import time
from datetime import datetime, timezone, timedelta

# Prefer zoneinfo for explicit timezone handling
try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/London")
except Exception:
    # fallback to system local tz if zoneinfo unavailable
    LOCAL_TZ = datetime.now().astimezone().tzinfo

# ---------------- CONFIG ----------------
# (feed_url, section)
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

    # Science
    ("https://www.nature.com/nature.rss", "Science"),
    ("https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science", "Science"),
    ("https://www.chemistryworld.com/413.rss", "Science"),

    # Nature
    ("https://oxonbirding.blogspot.com/feeds/posts/default?alt=rss", "Nature"),
]

MAX_ITEMS = 100
OUT_PATH = "digest.html"
ARCHIVE_DIR = "archive"
LOG_PATH = "digest.log"
# ----------------------------------------

# ---------- ranking knobs ----------
SOURCE_PRIORITY = {
    "reuters": 1.3,
    "new york times": 1.15,
    "nytimes": 1.15,
    "bbc": 1.05,
    "guardian": 1.05,
    "economist": 1.2,
    "wsj": 1.1,
    "wired": 1.0,
    "nature": 1.1,
}
KEYWORD_BOOSTS = {
    "climate": 2.0,
    "energy": 1.6,
    "ai": 2.0,
    "economy": 1.4,
    "ukraine": 1.8,
    "covid": 1.5,
}
WEIGHTS = {
    "source": 1.0,
    "recency": 1.6,
    "keyword": 2.0,
    "title_signal": 0.6,
    "summary_len": 0.25,
    "dup": 0.9,
}
HALF_LIFE_HOURS = 8.0
# per-section caps
SECTION_CAPS = {"News": 15}
DEFAULT_SECTION_CAP = 10

# ---------- utilities ----------
def safe_write(path, text):
    """
    Write `text` to `path`. If dirname is empty (current dir) skip makedirs.
    Returns True on success, False otherwise.
    """
    try:
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
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

def safe_log_write(lines):
    txt = "\n".join(lines) + "\n"
    try:
        dirname = os.path.dirname(LOG_PATH)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
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

def uid_for(link, title=""):
    return hashlib.sha1(((link or "") + (title or "")).encode("utf-8")).hexdigest()

def parse_struct_time(tp):
    """
    Accept a time.struct_time or tuple as returned by feedparser.
    Return a timezone-aware UTC datetime or None.
    """
    try:
        # If feedparser provided a struct_time-like object
        if hasattr(tp, "tm_year"):
            return datetime.fromtimestamp(int(calendar.timegm(tp)), tz=timezone.utc)
        # If it's a tuple/list
        if isinstance(tp, (tuple, list)):
            return datetime.fromtimestamp(int(calendar.timegm(tuple(tp))), tz=timezone.utc)
    except Exception:
        pass
    return None

# allow longer summaries up to 500 chars, prefer sentence boundaries
def short_summary_from_snippet(snippet, max_chars=500):
    if not snippet:
        return ""
    text = re.sub(r"<[^>]+>", " ", snippet)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    out = ""
    for s in sentences:
        if not out:
            candidate = s
        else:
            candidate = out + " " + s
        if len(candidate) <= max_chars:
            out = candidate
        else:
            break
    if not out:
        out = text[:max_chars].rsplit(" ", 1)[0]
        if len(out) < len(text):
            out = out + "..."
    return out

def timestamp_string():
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")

# ---------- scoring helpers ----------
def _source_score(source_name):
    if not source_name:
        return 1.0
    s = source_name.lower()
    for k, v in SOURCE_PRIORITY.items():
        if k in s:
            return v
    return 1.0

def _recency_score(published_dt, now=None):
    if not published_dt:
        return 0.0
    now = now or datetime.now(timezone.utc)
    age_seconds = max(0.0, (now - published_dt).total_seconds())
    half_life = HALF_LIFE_HOURS * 3600.0
    return math.pow(2.0, -age_seconds / half_life)

def _keyword_score(text):
    if not text:
        return 0.0
    t = text.lower()
    score = 0.0
    for kw, boost in KEYWORD_BOOSTS.items():
        if kw in t:
            score += boost
    return score

def _title_signal(title):
    if not title:
        return 0.0
    if any(ch.isdigit() for ch in title):
        return 1.0
    if len(title.split()) <= 6:
        return 0.6
    return 0.0

def score_item(item, now=None, dup_count=1):
    now = now or datetime.now(timezone.utc)
    s_source = _source_score(item.get("source"))
    s_recency = _recency_score(item.get("published"), now=now)
    s_keyword = _keyword_score((item.get("title","") + " " + item.get("summary","")))
    s_title = _title_signal(item.get("title",""))
    s_summary_len = min(1.0, len(item.get("summary","")) / 500.0)  # normalized to 500
    s_dup = math.log1p(dup_count)
    score = (
        WEIGHTS["source"] * s_source +
        WEIGHTS["recency"] * s_recency +
        WEIGHTS["keyword"] * s_keyword +
        WEIGHTS["title_signal"] * s_title +
        WEIGHTS["summary_len"] * s_summary_len +
        WEIGHTS["dup"] * s_dup
    )
    return score

# ---------- HTML builder (News first, others alphabetical) ----------
def format_top_updated(now_utc):
    """
    Format the top 'Updated:' string using LOCAL_TZ in form:
    'Updated: AM Thursday 6 November 2025' (AM/PM then weekday then day month year)
    """
    try:
        local = now_utc.astimezone(LOCAL_TZ)
    except Exception:
        local = now_utc.astimezone()
    hour = local.hour
    ampm = "AM" if hour < 12 else "PM"
    weekday = local.strftime("%A")
    day = local.day
    month = local.strftime("%B")
    year = local.year
    return f"Updated: {ampm} {weekday} {day} {month} {year}"

def format_pub_local(pub_dt):
    """
    Convert published UTC datetime to local time string.
    Format: YYYY-MM-DD HH:MM ZZZ (e.g. 2025-11-06 10:11 GMT)
    """
    if not pub_dt:
        return ""
    try:
        local = pub_dt.astimezone(LOCAL_TZ)
    except Exception:
        local = pub_dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M %Z")

def build_html_digest(items_by_section, err_message=None):
    now_utc = datetime.now(timezone.utc)
    updated_label = format_top_updated(now_utc)

    # Prepare section ordering: News first, then Politics, then alphabetically
    keys = list(items_by_section.keys())
    others = sorted([k for k in keys if k not in ("News", "Politics")])
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
            summ = short_summary_from_snippet(it.get("summary",""), max_chars=500) or (t + ".")
            blocks.append(
                f"<article class='news-item'>"
                f"<h3 class='news-title'><a href='{link}' target='_blank' rel='noopener'>{t}</a></h3>"
                f"<div class='meta'>{src} · {pub_txt}</div>"
                f"<p class='summary'>{html.escape(summ)}</p>"
                f"</article>"
            )
        # include a section-body wrapper (CSS expects it)
        section_html = (
            f"<section class='section'>"
            f"<h2 class='section-title'>{html.escape(sec)}</h2>"
            f"<div class='section-body'>"
            + "\n".join(blocks) +
            f"</div></section>"
        )
        section_blocks.append(section_html)

    sections_block = "\n".join(section_blocks) if section_blocks else "<p>No items found.</p>"

    # archives listing (latest 10)
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

    # CSS tweaks: larger main heading and section headings; same monospace; centered container
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Daily News Digest</title>

  <!-- single stylesheet in site root -->
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <div class="container">
  <main class="content">
    <header class="digest-header">
      <h1>Daily News</h1>
      <div class="muted time">{html.escape(updated_label)}</div>
    </header>

    {error_block}

    <!-- sections_block should output one or more .digest-section blocks -->
    {sections_block}

    <!-- archives_html should be a simple list or block; keep it muted -->
    <div class="archive muted">
      {archives_html}
    </div>

    <footer class="muted" style="margin-top:18px;font-size:0.9rem">
      Generated automatically. Source list editable in <code>daily_news_digest.py</code>.
    </footer>

  </main>
  <aside class="sidebar">...</aside>
  </div>
</body>
</html>"""



    return page

# ---------- main run logic ----------
def run():
    log_lines = []
    items = []
    err = None

    # cutoff = last 24 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    log_lines.append(f"cutoff:{cutoff.isoformat()}")

    # import feedparser late
    try:
        import feedparser
    except Exception as e:
        err = f"ImportError: {type(e).__name__}: {e}"
        log_lines.append("ERROR: " + err)
        safe_write(OUT_PATH, build_html_digest({} , err_message=err))
        safe_log_write(log_lines)
        return 0

    # collect items published within last 24 hours
    try:
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
                        pub_dt = parse_struct_time(tp)
                    else:
                        pub_dt = None
                        for k in ("published", "updated"):
                            v = e.get(k)
                            if v:
                                try:
                                    # attempt ISO parse
                                    pub_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                                    if pub_dt.tzinfo is None:
                                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                                    break
                                except Exception:
                                    # last-resort parse via feedparser's parsed time if available
                                    try:
                                        parsed = feedparser._parse_date(v)  # feedparser internal helper
                                        if parsed:
                                            pub_dt = parse_struct_time(parsed)
                                            break
                                    except Exception:
                                        pass
                    # require a publish timestamp and be within last 24 hours
                    if not pub_dt or pub_dt < cutoff:
                        continue
                    uid = uid_for(link, title)
                    items.append({
                        "uid": uid,
                        "title": title.strip(),
                        "link": link.strip(),
                        "summary": summary.strip(),
                        "source": source,
                        "published": pub_dt,
                        "section": section
                    })
            except Exception as e2:
                log_lines.append(f"FeedError [{url}]: {type(e2).__name__}: {e2}")

        if not items:
            log_lines.append("info: no items within 24 hours")

        # dedupe & group counts (within candidate set)
        grouped = {}
        for it in items:
            u = it["uid"]
            if u not in grouped:
                grouped[u] = {"item": it, "count": 1}
            else:
                existing = grouped[u]["item"]
                a = it.get("published")
                b = existing.get("published")
                if a and (not b or a > b):
                    grouped[u]["item"] = it
                grouped[u]["count"] += 1

        # score each grouped item
        now = datetime.now(timezone.utc)
        scored = []
        for uid, info in grouped.items():
            it = info["item"]
            count = info["count"]
            sc = score_item(it, now=now, dup_count=count)
            scored.append((sc, it, count))

        # sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # select top with per-section caps and overall MAX_ITEMS
        items_by_section = {}
        total_selected = 0
        for sc, it, count in scored:
            if total_selected >= MAX_ITEMS:
                break
            sec = it.get("section") or "Other"
            cap = SECTION_CAPS.get(sec, DEFAULT_SECTION_CAP)
            bucket = items_by_section.setdefault(sec, [])
            if len(bucket) >= cap:
                continue
            bucket.append(it)
            total_selected += 1

        # build HTML and write files
        html_page = build_html_digest(items_by_section)
        wrote = safe_write(OUT_PATH, html_page)
        log_lines.append(f"wrote:{OUT_PATH} ok={wrote}")
        log_lines.append(f"selected_items:{total_selected} total_candidates:{len(scored)}")

        # write archive
        ts = timestamp_string()
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        archive_name = f"digest-{ts}.html"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        wrote_archive = safe_write(archive_path, html_page)
        log_lines.append(f"archive:{archive_path} ok={wrote_archive}")

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        log_lines.append("ERROR: " + err)
        safe_write(OUT_PATH, build_html_digest({} , err_message=err))
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
