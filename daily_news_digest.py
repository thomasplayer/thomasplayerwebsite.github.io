#!/usr/bin/env python3
"""
daily_news_digest.py

- Fetches RSS feeds (tagged by section).
- Considers items published in the last 24 hours only.
- Scores items by importance and selects top N unique stories.
- Enforces per-section caps: News=20, others=10; overall cap = MAX_ITEMS.
- Writes digest.html (current), archive/digest-YYYYMMDDHHMMSS.html, and digest.log.
- Deterministic. No external AI.
"""

import os
import sys
import hashlib
import re
import html
import calendar
import math
from datetime import datetime, timezone, timedelta

# ---------------- CONFIG ----------------
# (feed_url, section)
RSS_FEEDS = [
    ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml","News"),
    ("http://feeds.bbci.co.uk/news/world/rss.xml","News"),
    ("https://www.theguardian.com/world/rss","News"),
    ("https://www.theguardian.com/uk/rss","News"),
    ("https://www.lemonde.fr/rss/une.xml","News"),
    ("https://www.france24.com/en/rss","News"),
    ("https://www.theguardian.com/politics/rss","Politics"),
    ("https://feeds.feedburner.com/guidofawkes","Politics"),
    ("https://tribunemag.co.uk/feed/","Politics"),
    ("https://theintercept.com/feed/?rss","Politics"),
    ("https://www.foreignaffairs.com/rss.xml","Politics"),
    ("https://www.nature.com/subjects/science.rss","Science"),
    ("https://www.scientificamerican.com/feed/rss/","Science"),
    ("https://www.chemistryworld.com/rss","Science"),
    ("https://www.audubon.org/rss.xml","Nature"),
    ("https://screenrant.com/feed/","Film"),
    ("https://www.empireonline.com/rss/all.xml","Film"),
]


MAX_ITEMS = 50
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
SECTION_CAPS = {"News": 20}
DEFAULT_SECTION_CAP = 10

# ---------- utilities ----------
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

# ---------- HTML builder (News first, others alphabetical) ----------
def build_html_digest(items_by_section, err_message=None):
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    # Prepare section ordering: News first then alphabetically
    keys = list(items_by_section.keys())
    others = sorted([k for k in keys if k != "News"])
    order = (["News"] if "News" in keys else []) + others

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
            pub_txt = pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if pub else ""
            summ = short_summary_from_snippet(it.get("summary","")) or (t + ".")
            blocks.append(
                f"<article class='news-item'><h3 class='news-title'><a href='{link}' target='_blank' rel='noopener'>{t}</a></h3>"
                f"<div class='meta'>{src} · {pub_txt}</div>"
                f"<p class='summary'>{html.escape(summ)}</p></article>"
            )
        section_blocks.append(f"<section class='section'><h2 class='section-title'>{html.escape(sec)}</h2>" + "\n".join(blocks) + "</section>")

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
                                    pub_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
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

        # ensure News appears first and others alphabetical in HTML builder (handled there)

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
