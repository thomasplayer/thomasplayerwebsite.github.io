#!/usr/bin/env python3

from datetime import datetime, timezone
import html
import feedparser
import re
from email.utils import parsedate_to_datetime
import urllib.request, json


OUT_FILE = "digest.html"
ARCHIVE_DIR = "archive"



# FEEDS

FEEDS = [
    "https://www.theguardian.com/rss",
    "https://feeds.bbci.co.uk/news/uk/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.france24.com/en/rss",
    "https://lwlies.com/feed",
    "https://rogerebert.com/feed",
    "https://www.blog.filmjabber.com/rss/rss-reviews.php",
    "https://www.blog.filmjabber.com/rss/rss-updates.php",
    "https://theparisreview.org/blog/feed",
    "https://feeds.feedburner.com/mcsweeneys",
    "https://worldliteraturetoday.org/feed",
    "https://www.bookbrowse.com/rss/",
    "https://the-tls.co.uk/feed",
    "https://alittleblogofbooks.com/feed",
    "https://terribleminds.com/ramble/feed",
    "https://www.DailyWritingTips.com/feed/",
    "https://feeds.feedburner.com/GoinsWriter",
    "https://megdowell.com/feed",
    "https://novaramedia.com/feed/",
    "https://oxonbirding.blogspot.com/feeds/posts/default?alt=rss"
]

_LIVE_TITLE_RE = re.compile(
    r"""
    (?:                         # ending phrases
        live
        |latest\s+updates?
        |live\s+updates?
        |breaking\s+live
        |live\s+blog
        |live\s+coverage
    )
    \s*$                        # must be at end of title
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

def parse_date_safe(s):
    """
    Return a timezone-aware datetime (UTC) for string s, or
    datetime.min with tzinfo=UTC if s is missing / invalid.
    """
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = parsedate_to_datetime(s)
        # parsedate_to_datetime sometimes returns naive datetimes — make them UTC-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        # fallback: try ISO parse (handles "YYYY-MM-DDTHH:MM:SSZ")
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)


def is_live_title(title: str) -> bool:
    if not title:
        return False
    t = title.strip()
    # Remove trailing separators like " - ", " | ", " – "
    t = re.sub(r"[\s\-\|\u2013\u2014]+$", "", t)
    return bool(_LIVE_TITLE_RE.search(t))

def gather_all_items(feed_urls):
    items = []
    for url in feed_urls:
        doc = feedparser.parse(url)
        feed_title = doc.feed.get("title") or url
        for entry in doc.entries:
            title = (entry.get("title") or "No title").strip()
            if is_live_title(title):
                continue
            items.append({
                "feed": feed_title,
                "title": title,
                "link": (entry.get("link") or "").strip(),
                "published": entry.get("published") or entry.get("updated") or "",
                "summary": (entry.get("summary") or entry.get("description") or "").strip(),
            })
    return items

def strip_tags(html_text: str) -> str:
    """Remove tags and script/style blocks, then unescape HTML entities."""
    if not html_text:
        return ""
    # Remove script/style blocks
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html_text)
    # Remove remaining tags
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    # Collapse whitespace and unescape entities
    text = re.sub(r"\s+", " ", text).strip()
    return html.unescape(text)

def remove_continue_reading(text: str) -> str:
    """
    Remove 'Continue reading...' (case-insensitive),
    including trailing dots or whitespace.
    """
    if not text:
        return ""
    # Remove variations like:
    # Continue reading...
    # Continue reading
    # Continue reading…
    cleaned = re.sub(
        r'Continue reading\s*\.{0,3}',
        '',
        text,
        flags=re.IGNORECASE
    )
    return cleaned.strip()

def truncate_keep_sentence(text: str, max_words: int = 100, max_overrun_words: int = 40) -> str:
    """
    Truncate `text` aiming for at most `max_words` words.
    If the truncation point falls mid-sentence, extend forward to the next sentence end
    ('.', '!', '?') so the summary ends at a sentence boundary — but only up to
    `max_overrun_words` extra words. If no sentence end is found in that window,
    cut at the last full word within max_words and append '...'.

    Returns trimmed text (no extra escaping).
    """
    if not text:
        return ""
    # collapse whitespace
    s = re.sub(r"\s+", " ", text).strip()
    words = s.split()
    if len(words) <= max_words:
        return s

    # candidate by hard word cut
    head_words = words[:max_words]
    head_text = " ".join(head_words)

    # If head_text already ends with a sentence terminator, use it.
    if re.search(r"[\.!?][\"']?\s*$", head_text):
        return head_text

    # Otherwise look ahead up to max_overrun_words for a sentence end
    lookahead_end = min(len(words), max_words + max_overrun_words)
    tail_words = words[max_words:lookahead_end]
    # rebuild the remainder text and search for sentence end punctuation
    remainder = " " + " ".join(tail_words) if tail_words else ""
    # find the first sentence terminator in the remainder (prefer earlier)
    m = re.search(r"([\.!?][\"']?)(?=\s|$)", remainder)
    if m:
        # include up to the match end
        end_index = m.end()
        # remainder starts with a leading space, so slice accordingly
        extended = head_text + remainder[:end_index]
        return extended.strip()

    # fallback: hard cut at max_words and append ellipsis
    return (head_text.rstrip() + "...")





# WEATHER

# Weather: add these near your other top-level constants/imports
OXFORD_LAT = 51.7520
OXFORD_LON = -1.2577
WEATHER_API_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

# weather helpers (copy exactly)
WEATHERCODE_MAP = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 80: "Rain showers",
    81: "Moderate showers", 82: "Violent showers", 95: "Thunderstorm",
}

def format_temp(value):
    if value is None:
        return "N/A"
    val = round(value)
    s = f"{val}".replace("-", "–")
    return f"{s}°C"

def fetch_oxford_weather(days=4):
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

        cur_temp = cw.get("temperature")
        cur_wind_kmh = cw.get("windspeed")
        cur_wind_mph = cur_wind_kmh * 0.621371 if cur_wind_kmh is not None else None
        cur_code = cw.get("weathercode")
        cur_desc = WEATHERCODE_MAP.get(cur_code, str(cur_code) if cur_code is not None else "N/A")

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







def build_html(items, err_message=None):
    """
    Build a simple HTML page that lists all items from all feeds in one long list.
    Each item is a dict with keys: 'feed', 'title', 'link', 'published', 'summary'.
    Requires: `import html, os` and `from datetime import datetime` at module level.
    """
    updated_label = f"Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"

    try:
        weather_html = fetch_oxford_weather()
    except Exception:
        weather_html = ""

    # Build the flat list of article blocks (preserve input order)
    blocks = []
    for it in items:
        title = html.escape((it.get("title") or "No title").strip())
        link = html.escape((it.get("link") or "").strip())
        feed = html.escape((it.get("feed") or "").strip())
        pub = html.escape(str(it.get("published") or ""))
        raw_summ = it.get("summary") or ""
        plain = strip_tags(raw_summ)
        plain = remove_continue_reading(plain)
        plain_trunc = truncate_keep_sentence(plain, max_words=100, max_overrun_words=40)
        summ_esc = html.escape(plain_trunc) if plain_trunc else ""
        blocks.append(
            "<article class='news-item'>"
            f"<h3 class='news-title'><a href='{link}' target='_blank' rel='noopener'>{title}</a></h3>"
            f"<div class='meta'>{feed}" + (f" | {pub}" if pub else "") + "</div>"
            f"<p class='summary'>{summ_esc}</p>"
            "</article>"
        )

    sections_block = "\n".join(blocks) if blocks else "<p>No items found.</p>"

    # Optional archive block (only if archive dir present)
    archives_html = ""
    try:
        if os.path.isdir(ARCHIVE_DIR):
            files = [f for f in os.listdir(ARCHIVE_DIR) if f.startswith("digest-") and f.endswith(".html")]
            files.sort(reverse=True)
            if files:
                links = [f"<li><a href='{html.escape(os.path.join(ARCHIVE_DIR, f))}'>{html.escape(f)}</a></li>" for f in files[:10]]
                archives_html = f"<h4>Archive</h4><ul class='archive'>{''.join(links)}</ul>"
    except Exception:
        archives_html = ""

    error_block = f"<div class='error'>{html.escape(err_message)}</div>" if err_message else ""

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Feeds Digest</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>

  <header class="digest-header">
    <h1>Feeds Digest</h1>
    <div class="muted time">{html.escape(updated_label)}</div>
  </header>

  <main>
    {weather_html}

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

def run():
    items = gather_all_items(FEEDS)
    # Sort all items globally, newest first (use parse_date_safe so all keys are aware datetimes)
    items.sort(
        key=lambda it: parse_date_safe(it.get("published")),
        reverse=True
    )
    html_text = build_html(items)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"Wrote {OUT_FILE} with {len(items)} items from {len(FEEDS)} feeds.")

if __name__ == "__main__":
    raise SystemExit(run())
