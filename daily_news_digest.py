#!/usr/bin/env python3

from datetime import datetime
import html
import feedparser

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
        summ = (it.get("summary") or "").strip()
        summ_esc = html.escape(summ) if summ else ""
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
