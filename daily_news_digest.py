#!/usr/bin/env python3

from datetime import datetime
import html
import feedparser
import re

FEEDS = [
    "https://www.theguardian.com/rss",
    "https://oxonbirding.blogspot.com/feeds/posts/default?alt=rss",
]

OUT_FILE = "digest.html"

ARCHIVE_DIR = "archive"

def gather_all_items(feed_urls):
    items = []
    for url in feed_urls:
        doc = feedparser.parse(url)
        feed_title = doc.feed.get("title") or url
        for entry in doc.entries:
            items.append({
                "feed": feed_title,
                "title": (entry.get("title") or "No title").strip(),
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

def build_html(items, err_message=None):
    """
    Build a simple HTML page that lists all items from all feeds in one long list.
    Each item is a dict with keys: 'feed', 'title', 'link', 'published', 'summary'.
    Requires: `import html, os` and `from datetime import datetime` at module level.
    """
    updated_label = f"Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"

    # Build the flat list of article blocks (preserve input order)
    blocks = []
    for it in items:
        title = html.escape((it.get("title") or "No title").strip())
        link = html.escape((it.get("link") or "").strip())
        feed = html.escape((it.get("feed") or "").strip())
        pub = html.escape(str(it.get("published") or ""))
        raw_summ = it.get("summary") or ""
        plain = strip_tags(raw_summ)
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
    html_text = build_html(items)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"Wrote {OUT_FILE} with {len(items)} items from {len(FEEDS)} feeds.")

if __name__ == "__main__":
    raise SystemExit(run())
