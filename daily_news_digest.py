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
import urllib.request, json
# CHANGED: fix import name and use Counter for trending keywords
from collections import Counter  # CHANGED: was `counter` originally

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
    ("https://www.theguardian.com/rss", "News"),
    ("https://feeds.skynews.com/feeds/rss/home.xml", "News"),
    ("https://www.telegraph.co.uk/rss.xml","News"),
    ("https://www.politics.co.uk/feed/","News"),
    ("https://www.mirror.co.uk/?service=rss","News"),
    ("https://theconversation.com/uk/articles.atom","News"),
    ("https://www.lemonde.fr/rss/une.xml", "News"),
    ("https://www.oxfordmail.co.uk/news/rss/", "News"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "News"),
    ("https://www.newyorker.com/feed/news", "News"),
    ("https://feeds.feedburner.com/guidofawkes", "News"),
    ("https://tribunemag.co.uk/feed/", "News"),
    ("https://theintercept.com/feed/?rss", "News"),
    ("https://www.foreignaffairs.com/rss.xml", "News"),

    # Culture
    ("https://www.theverge.com/rss/index.xml", "Culture"),
    ("https://www.empireonline.com/rss/all.xml", "Culture"),
    ("https://www.themarginalian.org/rss/", "Culture"),
    ("https://aeon.co/feed", "Culture"),
    ("https://pudding.cool/rss.xml", "Culture"),
    ("https://www.huffingtonpost.co.uk/","Culture"),

    # Science
    ("https://www.nature.com/nature.rss", "Science"),
    ("https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science", "Science"),
    ("https://www.chemistryworld.com/413.rss", "Science"),

    # Nature
    ("https://oxonbirding.blogspot.com/feeds/posts/default?alt=rss", "Nature"),
    ("https://tmbirding.blogspot.com/feeds/posts/default?alt=rss", "Nature"),
]
MAX_ITEMS = 100
SECTION_CAPS = {"News": 20}
DEFAULT_SECTION_CAP = 10
OUT_PATH = "digest.html"
ARCHIVE_DIR = "archive"
LOG_PATH = "digest.log"
HALF_LIFE_HOURS = 8.0

# Weather
OXFORD_LAT = 51.7520
OXFORD_LON = -1.2577
WEATHER_API_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

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

# ---------------- simple weather helper ----------------
# Uses Open-Meteo free API: current_weather + daily high/low for next 3 days.
# See: https://open-meteo.com/en/docs for API details. :contentReference[oaicite:1]{index=1}
WEATHERCODE_MAP = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 80: "Rain showers",
    81: "Moderate showers", 82: "Violent showers", 95: "Thunderstorm",
}

def format_temp(value):
    """Return a temperature string with °C, using en dash for negatives."""
    if value is None:
        return "N/A"
    val = round(value)
    # replace leading minus with en dash (U+2013)
    s = f"{val}".replace("-", "–")
    return f"{s}°C"

def fetch_oxford_weather(days=4):
    """
    Returns an HTML snippet with current weather and short forecast for Oxford.
    Uses Open-Meteo (no API key).  Fails silently if network unavailable.
    """
    params = (
        f"?latitude={OXFORD_LAT}&longitude={OXFORD_LON}"
        f"&current_weather=true"
        f"&daily=temperature_2m_max,temperature_2m_min,weathercode"
        f"&timezone=Europe/London"
        f"&forecast_days={days}"
    )
    url = WEATHER_API_ENDPOINT + params
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.load(resp)

        cw = data.get("current_weather", {})
        daily = data.get("daily", {})

        # current
        cur_temp = cw.get("temperature")
        cur_wind_kmh = cw.get("windspeed")
        cur_wind_mph = cur_wind_kmh * 0.621371 if cur_wind_kmh is not None else None
        cur_code = cw.get("weathercode")
        cur_desc = WEATHERCODE_MAP.get(cur_code, str(cur_code) if cur_code is not None else "N/A")

        # build short daily rows
        rows = []
        dates = daily.get("time", [])[1:days]
        tmax = daily.get("temperature_2m_max", [])[1:days]
        tmin = daily.get("temperature_2m_min", [])[1:days]
        wcodes = daily.get("weathercode", [])[1:days]
        for d, hi, lo, wc in zip(dates, tmax, tmin, wcodes):
            try:
                weekday = datetime.strptime(d, "%Y-%m-%d").strftime("%a")
            except Exception:
                weekday = d
            desc = WEATHERCODE_MAP.get(wc, str(wc) if wc is not None else "")
            rows.append(
                f"<div class='wf-day'><strong>{html.escape(weekday)}</strong>: "
                f"{html.escape(desc)}, {html.escape(format_temp(lo))} / {html.escape(format_temp(hi))}</div>"
            )
            
        daily_html = "\n".join(rows)
        html_snippet = (
            "<div class='weather-forecast'>"
            "<h2 class='wf-title'>Oxford weather</h2>"
            f"<div class='wf-now'><strong>Today</strong>: "
            f"{html.escape(cur_desc)}, "
            f"{html.escape(format_temp(cur_temp))} ("
            f"{html.escape(str(round(cur_wind_mph)) + ' mph' if cur_wind_mph is not None else 'N/A')})</div>"
            f"<div class='wf-daily'>{daily_html}</div>"
            "</div>"
        )
        return html_snippet
    except Exception:
        return ""

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

    header_block = f"""
    <header class="digest-header">
      <h1>Daily News</h1>
      <div class="muted time">{html.escape(updated_label)}</div>
    </header>
    """

    # add call to fetch weather (non-fatal)
    try:
        weather_html = fetch_oxford_weather()
    except Exception:
        weather_html = ""

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

    {weather_html}

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

# ---------------- deterministic clustering + keyword promotion (ADDED) ----------------
STOPWORDS = {  # ADDED: stopwords for deterministic tokenizer
    "the","a","an","and","or","of","in","on","for","to","with","by","from","is","are","was",
    "it","its","that","this","at","as","be","has","have","will","new","update"
}  # ADDED

def tokenize(text):  # ADDED
    if not text:
        return set()
    t = text.lower()
    t = re.sub(r"[^0-9a-z'\s]", " ", t)
    toks = [w.strip("'") for w in t.split()]
    toks = [w for w in toks if w and w not in STOPWORDS and len(w) > 1]
    return set(toks)  # ADDED

def jaccard(a, b):  # ADDED
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0

def cluster_items(items, jaccard_threshold=0.35):  # ADDED
    sorted_idx = sorted(range(len(items)),
                        key=lambda i: (items[i].get("published") or datetime.min.replace(tzinfo=timezone.utc)),
                        reverse=True)
    clusters = []
    cluster_token_sets = []
    for i in sorted_idx:
        it = items[i]
        toks = tokenize(it.get("title","") + " " + it.get("summary",""))
        placed = False
        for ci, c_toks in enumerate(cluster_token_sets):
            if jaccard(toks, c_toks) >= jaccard_threshold:
                clusters[ci].append(i)
                cluster_token_sets[ci] = c_toks | toks
                placed = True
                break
        if not placed:
            clusters.append([i])
            cluster_token_sets.append(toks)
    return clusters, cluster_token_sets

def extract_trending_keywords(clusters, cluster_token_sets, items, top_cluster_count=8, top_k=20):  # ADDED
    cluster_info = []
    for idx, cl in enumerate(clusters):
        top_pubs = sorted([items[i].get("published") or datetime.min.replace(tzinfo=timezone.utc) for i in cl], reverse=True)
        cluster_info.append((len(cl), top_pubs[0], idx))
    cluster_info.sort(key=lambda x: (-x[0], -x[1].timestamp()))
    chosen = [ci for _,_,ci in cluster_info[:top_cluster_count]]
    freq = Counter()
    for ci in chosen:
        toks = cluster_token_sets[ci]
        freq.update(toks)
    candidates = [t for t,c in freq.most_common() if len(t) > 2]
    return candidates[:top_k]

def keyword_match_score(item, trending_keywords, explicit_boosts):  # ADDED
    t = (item.get("title","") + " " + item.get("summary","")).lower()
    s = 0.0
    for i, kw in enumerate(trending_keywords):
        weight = (len(trending_keywords) - i) / max(1, len(trending_keywords))
        if kw in t:
            s += 1.0 * weight
    for k, boost in explicit_boosts.items():
        if k in t:
            s += boost
    return s

def compute_final_scores(items):  # ADDED
    clusters, cluster_token_sets = cluster_items(items, jaccard_threshold=0.35)
    cluster_meta = []
    for ci, cl in enumerate(clusters):
        size = len(cl)
        rep_idx = sorted(cl, key=lambda i: (items[i].get("published") or datetime.min.replace(tzinfo=timezone.utc), items[i]["uid"]), reverse=True)[0]
        cluster_meta.append({"index": ci, "size": size, "rep_idx": rep_idx})
    trending = extract_trending_keywords(clusters, cluster_token_sets, items, top_cluster_count=8, top_k=25)

    uid_to_dup = {}
    for ci, cl in enumerate(clusters):
        for i in cl:
            uid = items[i]["uid"]
            uid_to_dup[uid] = uid_to_dup.get(uid, 0) + 1

    for i, it in enumerate(items):
        dup_count = uid_to_dup.get(it["uid"], 1)
        cluster_index = next((m["index"] for m in cluster_meta if i in clusters[m["index"]]), None)
        cluster_size = 0 if cluster_index is None else cluster_meta[cluster_index]["size"]
        cluster_factor = 1.0 + math.log1p(cluster_size) if cluster_size > 1 else 1.0
        base = (1.0 * source_score(it.get("source"))
                + 1.6 * recency_score(it.get("published"))
                + 0.6 * title_signal(it.get("title",""))
                + 0.25 * min(1.0, len(it.get("summary","")) / 500.0)
                + 0.9 * math.log1p(dup_count))
        kw_score = keyword_match_score(it, trending, KEYWORD_BOOSTS)
        it["final_score"] = base * cluster_factor + 2.0 * kw_score
        it["cluster_size"] = cluster_size
    return clusters, cluster_meta, trending

def select_items(items, max_items=MAX_ITEMS, headline_slots_preferred=8):  # ADDED
    for it in items:
        if "uid" not in it:
            it["uid"] = uid_for(it.get("link",""), it.get("title",""))
        if "published" not in it or it["published"] is None:
            it["published"] = datetime.min.replace(tzinfo=timezone.utc)

    clusters, cluster_meta, trending = compute_final_scores(items)

    headline_clusters = [m for m in cluster_meta if m["size"] > 1]
    headline_clusters.sort(key=lambda m: (-m["size"], -items[m["rep_idx"]]["final_score"], -int((items[m["rep_idx"]].get("published") or datetime.min).timestamp()), items[m["rep_idx"]]["uid"]))
    headline_slots = min(headline_slots_preferred, len(headline_clusters))

    selected = []
    selected_uids = set()

    for m in headline_clusters[:headline_slots]:
        rep = items[m["rep_idx"]]
        selected.append(rep)
        selected_uids.add(rep["uid"])

    remaining = sorted([it for it in items if it["uid"] not in selected_uids],
                       key=lambda it: (-it.get("final_score", 0.0), -int((it.get("published") or datetime.min).timestamp()), it.get("source",""), it["uid"]))

    caps = SECTION_CAPS.copy()
    def get_cap(section):
        return caps.get(section, DEFAULT_SECTION_CAP)

    for it in remaining:
        sec = it.get("section","Misc") or "Misc"
        if sum(1 for s in selected if s.get("section","") == sec) >= get_cap(sec):
            continue
        selected.append(it)
        if len(selected) >= max_items:
            break

    return selected

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

    # dedupe by uid, keep newest instance and count duplicates (unchanged)
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

    # CHANGED: replaced original scoring/sorting block with clustering-based selection (call select_items)
    # ADDED: build candidates list for selection
    candidates = [info["item"] for uid, info in grouped.items()]  # ADDED
    selected = select_items(candidates, max_items=MAX_ITEMS)  # ADDED: use new deterministic selection pipeline

    # ADDED: assemble items_by_section from selected items (respecting caps already enforced)
    items_by_section = {}
    total_selected = 0
    for it in selected:
        sec = it.get("section") or "Other"
        bucket = items_by_section.setdefault(sec, [])
        bucket.append(it)
        total_selected += 1

    html_page = build_html_digest(items_by_section)
    ok = safe_write(OUT_PATH, html_page)
    log_lines.append(f"wrote:{OUT_PATH} ok={ok}")
    log_lines.append(f"selected_items:{total_selected} total_candidates:{len(candidates)}")  # CHANGED: log updated to reflect new flow

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
