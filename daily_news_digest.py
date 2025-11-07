#!/usr/bin/env python3
"""
daily_news_digest.py

- Fetches RSS feeds (with sections).
- Only considers items published after last_run.txt (ISO UTC).
- Scores items by importance and picks top N without duplicates.
- Writes digest.html, archive/digest-YYYYMMDDHHMMSS.html, last_run.txt, digest.log.
- Deterministic, no external AI.
"""

import os
import sys
import hashlib
import re
import html
import calendar
import math
from datetime import datetime, timezone, timedelta

# --------------- CONFIG ----------------
# (feed_url, section)
RSS_FEEDS = [
    ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml","News"),
    ("http://feeds.reuters.com/reuters/topNews","News"),
    ("https://www.theguardian.com/world/rss","News"),
    ("http://feeds.bbci.co.uk/news/world/rss.xml","News"),
    ("https://www.aljazeera.com/xml/rss/all.xml","News"),
    ("https://www.economist.com/sections/international/rss.xml","News"),
    ("https://www.wsj.com/xml/rss/3_7085.xml","Politics"),
    ("https://www.theatlantic.com/feed/all/","Politics"),
    ("https://www.nationalreview.com/feed/","Politics"),
    ("https://www.americanprogress.org/feed/","Politics"),
    ("https://reason.com/feed/","Politics"),
    ("https://www.politico.com/rss/politics08.xml","Politics"),
    ("https://www.foreignaffairs.com/rss.xml","Politics"),
    ("https://theintercept.com/feed/?rss","Politics"),
    ("https://www.foxnews.com/about/rss/","Politics"),
    ("https://www.npr.org/rss/rss.php?id=1001","Politics"),
    ("https://www.project-syndicate.org/feeds/latest","Politics"),
    ("https://www.nature.com/subjects/science.rss","Science"),
    ("https://www.scientificamerican.com/feed/rss/","Science"),
    ("https://www.wired.com/feed/rss","Technology"),
    ("https://www.nytimes.com/svc/collections/v1/publish/arts/rss.xml","Arts"),
    ("https://www.theguardian.com/artanddesign/rss","Arts"),
    ("https://hyperallergic.com/feed/","Arts"),
    ("https://lithub.com/feed/","Literature"),
    ("https://www.theparisreview.org/blog/feed/","Literature"),
    ("https://www.poetryfoundation.org/rss/articles.xml","Literature"),
    ("https://electricliterature.com/feed/","Literature"),
    ("https://ebird.org/news/feed/","Nature"),
    ("https://www.birdguides.com/feed/news/","Nature"),
    ("https://www.audubon.org/rss.xml","Nature"),
    ("https://blog.tincanknits.com/feed/","Crafts"),
    ("https://www.interweave.com/feed/","Crafts"),
    ("https://www.nytimes.com/svc/collections/v1/publish/entertainment/movies/rss.xml","Film"),
    ("https://www.empireonline.com/rss/all.xml","Film"),
    ("https://www.indiewire.com/feed/","Film"),
    ("https://screenrant.com/feed/","Film"),
]

MAX_ITEMS = 50
OUT_PATH = "digest.html"
ARCHIVE_DIR = "archive"
LOG_PATH = "digest.log"
LAST_RUN_PATH = "last_run.txt"   # ISO UTC timestamp of last successful run
# ----------------------------------------

# --------------- ranking knobs ----------------
SOURCE_PRIORITY = {
    "reuters": 1.3,
    "new york times": 1.15,
    "nytimes": 1.15,
    "bbc": 1.05,
    "guardian": 1.05,
    "economist": 1.2,
    "al jazeera": 1.0,
    "wsj": 1.1,
    "wired": 1.0,
    "nature": 1.1,
}
KEYWORD_BOOSTS = {
    "climate": 2.0,
    "ai": 2.0,
    "UK": 2.0,
    "gay": 1.5,
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
# ------------------------------------------------

def safe_write(path, text):
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

def uid_for(link, title=""):
    return hashlib.sha1(((link or "") + (title or "")).encode("utf-8")).hexdigest()

def parse_struct_time(tp):
    try:
        return datetime.fromtimestamp(int(calendar.timegm(tp)), tz=timezone.utc)
    except Exception:
        return None

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

def timestamp_string():
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")

# ---------- persistence: last_run ----------
def read_last_run():
    if not os.path.isfile(LAST_RUN_PATH):
        # default: 24 hours ago
        return datetime.now(timezone.utc) - timedelta(hours=24)
    try:
        s = open(LAST_RUN_PATH, "r", encoding="utf-8").read().strip()
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc) - timedelta(hours=24)

def write_last_run(ts=None):
    ts = ts or datetime.now(timezone.utc).astimezone().isoformat()
    try:
        with open(LAST_RUN_PATH, "w", encoding="utf-8") as f:
            f.write(ts)
        return True
    except Exception:
        return False

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
    s_summary_len = min(1.0, len(item.get("summary","")) / 300.0)
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

# ---------- HTML builder (simple centered layout with sections) ----------
def build_html_digest(items_by_section, err_message=None):
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    # items_by_section: dict section -> list of items already sorted by score
    sections_html = []
    for sec in sorted(items_by_section.keys()):
        sec_items = items_by_section[sec]
        if not sec_items:
            continue
        blocks = []
        for i, it in enumerate(sec_items, start=1):
            t = html.escape(it.get("title","No title"))
            link = html.escape(it.get("link","#"))
            src = html.escape(it.get("source",""))
            pub = it.get("published")
            pub_txt = pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if pub else ""
            summ = short_summary_from_snippet(it.get("summary","")) or (t + ".")
            blocks.append(
                f"<article class='news-item'><h3 class='news-title'><a href='{link}' target='_blank' rel='noopener'>{t}</a></h3>"
                f"<div class='meta'>{src} · {pub_txt}</div>"
                f"<p class='summary'>{html.escape(summ)}</p></article>"
            )
        sections_html.append(f"<section class='section'><h2 class='section-title'>{html.escape(sec)}</h2>" + "\n".join(blocks) + "</section>")

    sections_block = "\n".join(sections_html) if sections_html else "<p>No items found.</p>"

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

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily News Digest</title>
<style>
:root {{ --fg:#111; --muted:#666; --maxw:1000px; --pad:28px; }}
html,body{{margin:0;padding:0;height:100%;background:#fff;color:var(--fg);font-family:ui-monospace,monospace;}}
.container{{max-width:var(--maxw);margin:36px auto;padding:var(--pad);box-sizing:border-box;}}
.header{{margin-bottom:12px;}} .header h1{{margin:0;font-size:20px}} .header .time{{color:var(--muted);font-size:0.95rem;margin-top:6px}}
.error{{color:#b00;background:#fee;padding:8px;border:1px solid #fbb;margin:10px 0}}
.section{{margin-top:18px}} .section-title{{margin:0 0 8px 0;font-size:1.1rem}}
.news-item{{padding:10px 0;border-bottom:1px solid #eee}} .news-title{{margin:0;font-size:1.02rem}}
.news-title a{{color:var(--fg);text-decoration:underline;text-underline-offset:2px}} .meta{{color:var(--muted);font-size:0.9rem;margin-top:6px}}
.summary{{margin-top:8px;color:#222}} .archive{{margin-top:14px;padding-left:1rem;color:var(--muted)}}
@media(max-width:800px){{ .container{{padding:18px;margin:18px}} }}
</style>
</head>
<body>
  <div class="container">
    <div class="header"><h1>Daily News</h1><div class="time">Last updated: {html.escape(now_iso)}</div></div>
    {error_block}
    {sections_block}
    {archives_html}
    <footer style="margin-top:18px;color:var(--muted);font-size:0.9rem">Generated automatically. Source list editable in <code>daily_news_digest.py</code>.</footer>
  </div>
</body>
</html>"""
    return page

# ---------- main run logic ----------
def run():
    log_lines = []
    items = []
    err = None
    last_run = read_last_run()

    # import feedparser late
    try:
        import feedparser
    except Exception as e:
        err = f"ImportError: {type(e).__name__}: {e}"
        log_lines.append("ERROR: " + err)
        safe_write(OUT_PATH, make_error_html(err))
        safe_log_write(log_lines)
        return 0

    # collect all items published after last_run
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
                                    pub_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                                    break
                                except Exception:
                                    pass
                    # include only items strictly newer than last_run if published available
                    if pub_dt and pub_dt <= last_run:
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
            log_lines.append("info: no new items since last_run")
        # dedupe by uid and count duplicates (if same uid seen multiple times in this collection)
        grouped = {}
        for it in items:
            u = it["uid"]
            if u not in grouped:
                grouped[u] = {"item": it, "count": 1}
            else:
                existing = grouped[u]["item"]
                # prefer the newer published value if present
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

        # sort by score descending and pick top N
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:MAX_ITEMS]
        
        # group selected items by section with per-section caps (News=20, others=10)
        items_by_section = {}
        caps = {"News": 20}
        default_cap = 10
        total_selected = 0
        
        for score, it, count in top:
            # stop if we've reached the overall MAX_ITEMS
            if total_selected >= MAX_ITEMS:
                break
            sec = it.get("section") or "Other"
            cap = caps.get(sec, default_cap)
            bucket = items_by_section.setdefault(sec, [])
            if len(bucket) >= cap:
                # this section is full; skip this item
                continue
            bucket.append(it)
            total_selected += 1

        # build HTML and write files
        html_page = build_html_digest(items_by_section)
        wrote = safe_write(OUT_PATH, html_page)
        log_lines.append(f"wrote:{OUT_PATH} ok={wrote}")
        log_lines.append(f"selected_items:{len(top)} total_candidates:{len(scored)}")

        # write archive
        ts = timestamp_string()
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        archive_name = f"digest-{ts}.html"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        wrote_archive = safe_write(archive_path, html_page)
        log_lines.append(f"archive:{archive_path} ok={wrote_archive}")

        # update last_run ONLY if run succeeded (write ISO UTC)
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        wrote_lr = write_last_run(now_iso)
        log_lines.append(f"last_run_written:{wrote_lr} value:{now_iso}")

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
