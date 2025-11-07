#!/usr/bin/env python3
"""
Hardened daily_news_digest.py

Always writes:
 - docs/digest.html
 - digest.log

Defers risky imports. Writes minimal error page and log on any failure.
Exits with status 0 so CI can upload artifacts for debugging.
"""

import os
import sys
import hashlib
import re
import html
import calendar
from datetime import datetime, timezone

# Config
RSS_FEEDS = [
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "http://feeds.reuters.com/reuters/topNews",
    "https://www.theguardian.com/world/rss"
]
MAX_ITEMS = 10
OUT_PATH = "docs/digest.html"
LOG_PATH = "digest.log"

def safe_write(path, text):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception as e:
        # best-effort fallback: try writing to current directory
        try:
            with open(os.path.basename(path), "w", encoding="utf-8") as f:
                f.write(text)
            return True
        except Exception:
            return False

def make_error_html(message):
    now = datetime.now(timezone.utc).astimezone().isoformat()
    safe_msg = html.escape(message)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Digest Error</title></head><body>
<h1>Daily News Digest — Error</h1>
<p>Time: {html.escape(now)}</p>
<div style="color:#b00;background:#fee;padding:8px;border:1px solid #fbb">{safe_msg}</div>
<p>The script failed to generate the digest. See <code>digest.log</code> for details.</p>
</body></html>"""

def uid_for(link, title=""):
    return hashlib.sha1(((link or "") + (title or "")).encode("utf-8")).hexdigest()

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

def build_html_digest(items, err_message=None):
    now = datetime.now(timezone.utc).astimezone().isoformat()
    header = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Daily News Digest</title></hea
