#!/usr/bin/env python3
"""
Newsbrief PK - news collector.

Reads RSS feeds from Pakistani news outlets, shortens each story to about
60 words, and writes everything to news.json for the reader page.

No installs needed (standard library only).

Run:            python3 pipeline.py
Better summaries: set ANTHROPIC_API_KEY and the script will use Claude to
                  write the 60-word summaries (English and Urdu). Without a
                  key it falls back to a simple "first sentences" cutter.
"""

import hashlib
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# ---------------------------------------------------------------------------
# FEEDS - edit this list freely. Check each URL opens in a browser; outlets
# sometimes change their feed addresses. A broken feed is skipped, not fatal.
# lang: "en" or "ur"      category: pakistan, world, business, sports,
#                                    entertainment, fashion
# ---------------------------------------------------------------------------
FEEDS = [
    # English
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/home", "lang": "en", "category": "pakistan"},
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/business", "lang": "en", "category": "business"},
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/sport", "lang": "en", "category": "sports"},
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/world", "lang": "en", "category": "world"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/home", "lang": "en", "category": "pakistan"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/business", "lang": "en", "category": "business"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/sports", "lang": "en", "category": "sports"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/entertainment", "lang": "en", "category": "entertainment"},
    {"source": "Geo News", "url": "https://www.geo.tv/rss/1/1", "lang": "en", "category": "pakistan"},
    {"source": "Business Recorder", "url": "https://www.brecorder.com/feeds/latest-news", "lang": "en", "category": "business"},
    # Urdu
    {"source": "BBC Urdu", "url": "https://feeds.bbci.co.uk/urdu/rss.xml", "lang": "ur", "category": "pakistan"},
    {"source": "Express News", "url": "https://www.express.pk/feed/", "lang": "ur", "category": "pakistan"},
]

MAX_WORDS = 60            # target summary length
MAX_PER_FEED = 12         # newest stories taken from each feed
KEEP_TOTAL = 300          # stories kept in news.json
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news.json")
USER_AGENT = "NewsbriefPK/0.1 (+news aggregator; links back to sources)"
CLAUDE_MODEL = "claude-haiku-5-5"

NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "atom": "http://www.w3.org/2005/Atom",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def clean_text(raw):
    """Strip HTML tags/entities and tidy whitespace."""
    if not raw:
        return ""
    text = re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text):
    # handles English full stops and the Urdu full stop (۔)
    parts = re.split(r"(?<=[.!?؟۔])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def shorten(text, max_words=MAX_WORDS):
    """Fallback summary: take whole sentences up to max_words."""
    words_total = text.split()
    if len(words_total) <= max_words:
        return text
    out, count = [], 0
    for sentence in split_sentences(text):
        n = len(sentence.split())
        if count + n > max_words:
            if not out:  # first sentence alone is too long: hard cut
                return " ".join(sentence.split()[:max_words]).rstrip(",;:") + "…"
            break
        out.append(sentence)
        count += n
    return " ".join(out) if out else " ".join(words_total[:max_words]) + "…"


def claude_summary(title, body, lang):
    """Ask Claude for a ~60 word summary. Returns None on any failure."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not body:
        return None
    language = "Urdu" if lang == "ur" else "English"
    prompt = (
        f"Summarize this news story in {language} in at most {MAX_WORDS} words, "
        "in your own words, as a neutral news brief. Use only facts stated in "
        "the text. Reply with the summary only.\n\n"
        f"Headline: {title}\n\nText: {body[:3000]}"
    )
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.load(r)
        text = data["content"][0]["text"].strip()
        return text or None
    except Exception as e:  # noqa: BLE001
        print(f"  ! summary API failed: {e}", file=sys.stderr)
        return None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def find_image(item):
    for tag in ("media:content", "media:thumbnail"):
        el = item.find(tag, NS)
        if el is not None and el.get("url"):
            return el.get("url")
    enc = item.find("enclosure")
    if enc is not None and (enc.get("type", "").startswith("image") or enc.get("url", "").lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
        return enc.get("url")
    # first <img> inside the description / content
    for tag in ("content:encoded", "description"):
        el = item.find(tag, NS if ":" in tag else None)
        if el is not None and el.text:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)', el.text)
            if m:
                return m.group(1)
    return None


def parse_date(item):
    for tag in ("pubDate", "dc:date"):
        el = item.find(tag, NS if ":" in tag else None)
        if el is not None and el.text:
            try:
                dt = parsedate_to_datetime(el.text.strip())
            except (TypeError, ValueError):
                try:
                    dt = datetime.fromisoformat(el.text.strip().replace("Z", "+00:00"))
                except ValueError:
                    continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def parse_feed(xml_bytes, feed):
    root = ET.fromstring(xml_bytes)
    items = root.findall(".//item")
    stories = []
    for item in items[:MAX_PER_FEED]:
        link_el = item.find("link")
        title_el = item.find("title")
        if link_el is None or title_el is None or not (link_el.text or "").strip():
            continue
        link = link_el.text.strip()
        title = clean_text(title_el.text)
        desc_el = item.find("content:encoded", NS)
        if desc_el is None or not desc_el.text:
            desc_el = item.find("description")
        body = clean_text(desc_el.text if desc_el is not None else "")
        stories.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "title": title,
            "body": body,
            "url": link,
            "image": find_image(item),
            "published": parse_date(item).isoformat(),
            "source": feed["source"],
            "lang": feed["lang"],
            "category": feed["category"],
        })
    return stories


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def load_existing():
    try:
        with open(OUT_FILE, encoding="utf-8") as f:
            return {s["id"]: s for s in json.load(f).get("stories", [])}
    except (OSError, ValueError, KeyError):
        return {}


def main():
    existing = load_existing()
    fresh = {}
    for feed in FEEDS:
        label = f'{feed["source"]} / {feed["category"]}'
        try:
            stories = parse_feed(fetch(feed["url"]), feed)
            print(f"ok   {label}: {len(stories)} stories")
        except Exception as e:  # noqa: BLE001
            print(f"SKIP {label}: {e}", file=sys.stderr)
            continue
        for s in stories:
            fresh.setdefault(s["id"], s)

    merged = dict(existing)
    new_count = 0
    for sid, s in fresh.items():
        if sid in merged:
            continue
        # summarise only stories we have not seen before (saves API cost)
        text = s["body"] or s["title"]
        summary = claude_summary(s["title"], text, s["lang"]) or shorten(text)
        merged[sid] = {
            "id": sid,
            "title": s["title"],
            "summary": summary,
            "url": s["url"],
            "image": s["image"],
            "published": s["published"],
            "source": s["source"],
            "lang": s["lang"],
            "category": s["category"],
        }
        new_count += 1

    stories = sorted(merged.values(), key=lambda s: s["published"], reverse=True)[:KEEP_TOTAL]
    if not stories:
        print("No stories collected and none saved; leaving news.json untouched.", file=sys.stderr)
        return 1
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "stories": stories},
                  f, ensure_ascii=False, indent=1)
    print(f"Saved {len(stories)} stories ({new_count} new) to {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
