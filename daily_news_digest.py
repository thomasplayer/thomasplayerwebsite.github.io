#!/usr/bin/env python3
"""
Improved daily_news_digest.py

Goals:
- Preserve final HTML layout and semantics unchanged.
- Fix bugs (uid_for), improve reliability (timeouts, parallel fetch), and clarify scoring.
- Keep deterministic selection and stable tie-breakers.
- Keep original RSS_FEEDS list intact.
"""

from datetime import datetime, timezone, timedelta
import os
import math
import hashlib
import html
import re
<<<<<<< HEAD
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Set
=======
>>>>>>> parent of ca7692b (Update daily_news_digest.py new sorting algorithm jaccard)

# Prefer zoneinfo; fallback to system tz
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

# lightweight priority and keyword boosts
SOURCE_PRIORITY = {
    # example: "bbc": 1.05,
}
KEYWORD_BOOSTS = {
    "star wars": 1.5,
    "the simpsons": 1.5,
    "gluten": 1.5,
}

# network / parallel fetch settings
FEED_WORKERS = 8
FEED_FETCH_TIMEOUT = 12  # seconds per feed (future.result timeout); parse itself may block in thread

# minimal stopwords (deterministic)
STOPWORDS = {
    "the","a","an","and","or","of","in","on","for","to","with","by","from","is","are","was",
    "it","its","that","this","at","as","be","has","have","will","new","update"
}

# logging basic
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------- utilities ----------------
def safe_write(path: str, text: str) -> bool:
    """
    Create parent dir if needed. Return True if write succeeded.
    If writing to intended path fails, do not silently write to cwd; log and return False.
    """
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception as e:
        logging.error("safe_write failed for %s: %s", path, e)
        return False

def uid_for(link: str, title: str = "") -> str:
    """
    Fixed UID creation. Deterministic SHA1 of concatenated link+title.
    """
    base = (link or "") + (title or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

<<<<<<< HEAD
def short_summary(snippet: str, max_chars: int = 500) -> str:
    if not snippet:
        return ""
=======


def short_summary(snippet, max_chars=500):
    if not snippet:
        return ""

    # Replace paragraph-like breaks with a period
>>>>>>> parent of ca7692b (Update daily_news_digest.py new sorting algorithm jaccard)
    s = re.sub(r"</p>|<br\s*/?>|\n+", ".", snippet, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(?<!\.)\.\.(?!\.)", ".", s)
    if len(s) <= max_chars:
        return s
    parts = re.split(r'(?<=[.!?])\s+', s)
    out = ""
    for p in parts:
        candidate = p if not out else out + " " + p
        if len(candidate) <= max_chars:
            out = candidate
        else:
            break
    if not out:
        out = s[:max_chars].rsplit(" ", 1)[0] + "..."
    out = re.sub(r"(?<!\.)\.\.(?!\.)", ".", out)
    return out

def format_top_updated(now_utc: datetime) -> str:
    try:
        local = now_utc.astimezone(LOCAL_TZ)
    except Exception:
        local = now_utc.astimezone()
    ampm = "AM" if local.hour < 12 else "PM"
    if os.name != "nt":
        return f"Updated: {ampm} {local.strftime('%A %-d %B %Y')}"
    else:
        return f"Updated: {ampm} {local.strftime('%A %#d %B %Y')}"

def format_pub_local(pub_dt: datetime) -> str:
    if not pub_dt:
        return ""
    try:
        local = pub_dt.astimezone(LOCAL_TZ)
    except Exception:
        local = pub_dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M %Z")

# ---------------- scoring ----------------
def source_score(source: str) -> float:
    if not source:
        return 1.0
    s = source.lower()
    for k, v in SOURCE_PRIORITY.items():
        if k in s:
            return v
    return 1.0

def recency_score(published_dt: datetime, now: datetime = None) -> float:
    if not published_dt:
        return 0.0
    now = now or datetime.now(timezone.utc)
    age = max(0.0, (now - published_dt).total_seconds())
    half = HALF_LIFE_HOURS * 3600.0
    return math.pow(2.0, -age / half)

def title_signal(title: str) -> float:
    if not title:
        return 0.0
    return 0.2 if len(title.split()) <= 8 else 0.0

# Improved keyword matching: use word-boundary regex for explicit boosts
def explicit_keyword_score(text: str, explicit_boosts: Dict[str, float]) -> float:
    if not text:
        return 0.0
    t = text.lower()
    s = 0.0
    for phrase, boost in explicit_boosts.items():
        # escape phrase for regex and require word boundaries where sensible
        pat = r"\b" + re.escape(phrase.lower()) + r"\b"
        if re.search(pat, t):
            s += boost
    return s

# ---------------- tokenizer + clustering ----------------
def tokenize(text: str) -> Set[str]:
    if not text:
        return set()
    t = text.lower()
    # keep apostrophes internal, remove other punctuation
    t = re.sub(r"[^0-9a-z'\s]", " ", t)
    toks = [w.strip("'") for w in t.split()]
    toks = [w for w in toks if w and w not in STOPWORDS and len(w) > 1]
    return set(toks)

def ngrams(tokens: List[str], n: int) -> List[str]:
    if n < 2:
        return []
    return [" ".join(tokens[i:i+n]) for i in range(len(tokens)-n+1)]

def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0

def cluster_items(items: List[Dict], jaccard_threshold: float = 0.35) -> Tuple[List[List[int]], List[Set[str]]]:
    # deterministic seed order: newest first; tie-break by uid
    sorted_idx = sorted(range(len(items)),
                        key=lambda i: ((items[i].get("published") or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
                                       items[i].get("uid","")),
                        reverse=True)
    clusters: List[List[int]] = []
    cluster_token_sets: List[Set[str]] = []
    for i in sorted_idx:
        it = items[i]
        # create token set that includes unigrams + bigrams (for phrase sensitivity)
        base_tokens = sorted(tokenize(it.get("title","") + " " + it.get("summary","")))
        toks_set = set(base_tokens)
        # include bigrams and trigrams into token set for improved phrase matching in clustering/trending
        for n in (2, 3):
            ng = ngrams(base_tokens, n)
            toks_set.update([g for g in ng if len(g) > 2])
        placed = False
        for ci, c_toks in enumerate(cluster_token_sets):
            if jaccard(toks_set, c_toks) >= jaccard_threshold:
                clusters[ci].append(i)
                cluster_token_sets[ci] = c_toks | toks_set
                placed = True
                break
        if not placed:
            clusters.append([i])
            cluster_token_sets.append(toks_set)
    return clusters, cluster_token_sets

def extract_trending_keywords(clusters: List[List[int]],
                              cluster_token_sets: List[Set[str]],
                              items: List[Dict],
                              top_cluster_count: int = 8,
                              top_k: int = 20) -> List[str]:
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
    # prefer multi-word tokens first (phrases), then single tokens, sorted by frequency and deterministically by token
    candidates = sorted(freq.items(), key=lambda x: (-x[1], -len(x[0].split()), x[0]))
    words = [t for t, c in candidates if len(t) > 2]
    return words[:top_k]

def keyword_match_score(item: Dict, trending_keywords: List[str], explicit_boosts: Dict[str, float]) -> float:
    t = (item.get("title","") + " " + item.get("summary","")).lower()
    s = 0.0
    for i, kw in enumerate(trending_keywords):
        # weight by position (earlier means more frequent)
        weight = (len(trending_keywords) - i) / max(1, len(trending_keywords))
        # word/phrase boundary check
        pat = r"\b" + re.escape(kw) + r"\b"
        if re.search(pat, t):
            s += 1.0 * weight
    s += explicit_keyword_score(t, explicit_boosts)
    return s

def compute_final_scores(items: List[Dict]) -> Tuple[List[List[int]], List[Dict], List[str]]:
    clusters, cluster_token_sets = cluster_items(items, jaccard_threshold=0.35)
    cluster_meta = []
    for ci, cl in enumerate(clusters):
        size = len(cl)
        # rep_idx: deterministic representative: newest published then uid
        rep_idx = sorted(cl, key=lambda i: ((items[i].get("published") or datetime.min.replace(tzinfo=timezone.utc)).timestamp(), items[i]["uid"]), reverse=True)[0]
        cluster_meta.append({"index": ci, "size": size, "rep_idx": rep_idx})
    trending = extract_trending_keywords(clusters, cluster_token_sets, items, top_cluster_count=8, top_k=25)

    uid_to_dup = {}
    for ci, cl in enumerate(clusters):
        for i in cl:
            uid = items[i]["uid"]
            uid_to_dup[uid] = uid_to_dup.get(uid, 0) + 1

    now = datetime.now(timezone.utc)
    for i, it in enumerate(items):
        dup_count = uid_to_dup.get(it["uid"], 1)
        # determine cluster size
        cluster_index = next((m["index"] for m in cluster_meta if i in clusters[m["index"]]), None)
        cluster_size = 0 if cluster_index is None else cluster_meta[cluster_index]["size"]
        cluster_factor = 1.0 + math.log1p(cluster_size) if cluster_size > 1 else 1.0
        base = (1.0 * source_score(it.get("source"))
                + 1.6 * recency_score(it.get("published"), now=now)
                + 0.6 * title_signal(it.get("title",""))
                + 0.25 * min(1.0, len(it.get("summary","")) / 500.0)
                + 0.9 * math.log1p(dup_count))
        kw_score = keyword_match_score(it, trending, KEYWORD_BOOSTS)
        it["final_score"] = base * cluster_factor + 2.0 * kw_score
        it["cluster_size"] = cluster_size
    return clusters, cluster_meta, trending

def select_items(items: List[Dict], max_items: int = MAX_ITEMS, headline_slots_preferred: int = 8) -> List[Dict]:
    # ensure UID and published defaults
    for it in items:
        if "uid" not in it:
            it["uid"] = uid_for(it.get("link",""), it.get("title",""))
        if "published" not in it or it["published"] is None:
            it["published"] = datetime.min.replace(tzinfo=timezone.utc)

    clusters, cluster_meta, trending = compute_final_scores(items)

    # headline clusters are those with size > 1 (multi-source corroboration)
    headline_clusters = [m for m in cluster_meta if m["size"] > 1]
    # deterministic sort: size desc, rep final_score desc, rep published desc, rep uid asc
    headline_clusters.sort(key=lambda m: (-m["size"],
                                          -items[m["rep_idx"]].get("final_score", 0.0),
                                          -int((items[m["rep_idx"]].get("published") or datetime.min).timestamp()),
                                          items[m["rep_idx"]]["uid"]))
    headline_slots = min(headline_slots_preferred, len(headline_clusters))

    selected: List[Dict] = []
    selected_uids: Set[str] = set()

    # pick headline representatives
    for m in headline_clusters[:headline_slots]:
        rep = items[m["rep_idx"]]
        selected.append(rep)
        selected_uids.add(rep["uid"])

    # remaining sorted by final_score desc, published desc, source asc, uid asc
    remaining = sorted([it for it in items if it["uid"] not in selected_uids],
                       key=lambda it: (-it.get("final_score", 0.0),
                                       -int((it.get("published") or datetime.min).timestamp()),
                                       it.get("source",""),
                                       it["uid"]))
    caps = SECTION_CAPS.copy()
    def get_cap(section: str) -> int:
        return caps.get(section, DEFAULT_SECTION_CAP)

    for it in remaining:
        sec = it.get("section","Misc") or "Misc"
        if sum(1 for s in selected if s.get("section","") == sec) >= get_cap(sec):
            continue
        selected.append(it)
        selected_uids.add(it["uid"])
        if len(selected) >= max_items:
            break

    return selected

# ---------------- HTML builder (preserve layout exactly) ----------------
# This function is intentionally left nearly identical to original to preserve final HTML.
def build_html_digest(items_by_section: Dict[str, List[Dict]], err_message: str = None) -> str:
    now_utc = datetime.now(timezone.utc)
    updated_label = format_top_updated(now_utc)

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
                        ts_str = f.removeprefix("digest-").removesuffix(".html")
                        dt = datetime.strptime(ts_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
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

<<<<<<< HEAD
# ---------------- feed fetching ----------------
def fetch_feed_entries(url: str, section: str) -> Tuple[str, str, List[Dict], str]:
    """
    Returns tuple (url, section, list_of_entries, error_message_or_empty)
    Each entry is a dict with title, link, summary, published (datetime or None), etc.
    """
    try:
        import feedparser
    except Exception as e:
        return url, section, [], f"ImportError: {type(e).__name__}: {e}"

    entries = []
    err = ""
    try:
        doc = feedparser.parse(url)
        # if parse had bozo exception, include message but continue if entries exist
        if getattr(doc, "bozo", False) and getattr(doc, "bozo_exception", None):
            logging.debug("feedparser bozo for %s: %s", url, doc.bozo_exception)
            # do not fail hard; surface error in logs
            err = f"ParseWarning: {doc.bozo_exception}"
        source = doc.feed.get("title") or url
        for e in doc.entries:
            link = (e.get("link") or "").strip()
            title = (e.get("title") or "").strip()
            # prefer summary then description
            summary = (e.get("summary") or e.get("description") or "").strip()
            tp = e.get("published_parsed") or e.get("updated_parsed")
            pub_dt = None
            if tp:
                try:
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
            entries.append({
                "title": title,
                "link": link,
                "summary": summary,
                "source": source,
                "published": pub_dt,
                "section": section
            })
    except Exception as ex:
        logging.exception("fetch_feed_entries failure for %s", url)
        err = f"{type(ex).__name__}: {ex}"
    return url, section, entries, err

=======
>>>>>>> parent of ca7692b (Update daily_news_digest.py new sorting algorithm jaccard)
# ---------------- main ----------------
def run() -> int:
    log_lines = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    log_lines.append(f"cutoff:{cutoff.isoformat()}")

    # parallel fetch of feeds with bounded workers
    feed_results = []
    with ThreadPoolExecutor(max_workers=FEED_WORKERS) as ex:
        futures = {ex.submit(fetch_feed_entries, url, section): (url, section) for url, section in RSS_FEEDS}
        for fut in as_completed(futures, timeout=None):
            url, section = futures[fut]
            try:
                res = fut.result(timeout=FEED_FETCH_TIMEOUT)
                feed_results.append(res)
            except Exception as e:
                msg = f"FeedFetchTimeout/Exception [{url}]: {type(e).__name__}: {e}"
                logging.warning(msg)
                log_lines.append(msg)

    items: List[Dict] = []
    # process feed results, applying cutoff immediately
    for url, section, entries, ferr in feed_results:
        if ferr:
            log_lines.append(f"FeedParseError [{url}]: {ferr}")
        for e in entries:
            pub_dt = e.get("published")
            if not pub_dt or pub_dt < cutoff:
                continue
            link = e.get("link","")
            title = e.get("title","")
            uid = uid_for(link, title)
            items.append({
                "uid": uid,
                "title": title,
                "link": link,
                "summary": e.get("summary",""),
                "source": e.get("source",""),
                "published": pub_dt,
                "section": section
            })

    if not items:
        log_lines.append("info: no items within 24 hours")

<<<<<<< HEAD
    # dedupe by uid: keep newest published; count duplicates
=======
    # dedupe by uid, keep newest instance and count duplicates
>>>>>>> parent of ca7692b (Update daily_news_digest.py new sorting algorithm jaccard)
    grouped = {}
    for it in items:
        u = it["uid"]
        if u not in grouped:
            grouped[u] = {"item": it, "count": 1}
        else:
            existing = grouped[u]["item"]
            grouped[u]["count"] += 1
            # keep later published
            if it.get("published") and existing.get("published") and it["published"] > existing["published"]:
                grouped[u]["item"] = it

<<<<<<< HEAD
    candidates = [info["item"] for uid, info in grouped.items()]
    selected = select_items(candidates, max_items=MAX_ITEMS)

    # assemble items_by_section preserving selection order
=======
    # score and sort
    scored = []
    for uid, info in grouped.items():
        it = info["item"]
        cnt = info["count"]
        sc = score_item(it, now=now, dup_count=cnt)
        scored.append((sc, it, cnt))
    scored.sort(key=lambda x: x[0], reverse=True)

    # select top with section caps and overall cap
>>>>>>> parent of ca7692b (Update daily_news_digest.py new sorting algorithm jaccard)
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
<<<<<<< HEAD
    log_lines.append(f"selected_items:{total_selected} total_candidates:{len(candidates)}")
=======
    log_lines.append(f"selected_items:{total_selected} total_candidates:{len(scored)}")
>>>>>>> parent of ca7692b (Update daily_news_digest.py new sorting algorithm jaccard)

    # archive copy (UTC timestamp)
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
