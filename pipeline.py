#!/usr/bin/env python3
"""
Newsbrief PK - news collector (version 2).

1. Reads RSS feeds from Pakistani news outlets.
2. Asks Claude to write a NEW headline and a ~60 word summary in its own words.
3. Saves everything to news.json for the reader page.
Cards show only "Source: <outlet>". No link and no copied text.

Needs the secret ANTHROPIC_API_KEY (set in GitHub: Settings > Secrets > Actions).
Without a key the script still runs but can only shorten the outlet's own text,
so add the key before you share the app with anyone.
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
# FEEDS - add or remove lines freely. A feed that fails is skipped (you will
# see SKIP in the run log). lang: "en" or "ur".
# category: pakistan, world, business, sports, entertainment, fashion
# ---------------------------------------------------------------------------
FEEDS = [
    # English
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/home", "lang": "en", "category": "pakistan"},
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/business", "lang": "en", "category": "business"},
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/sport", "lang": "en", "category": "sports"},
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/world", "lang": "en", "category": "world"},
    {"source": "Dawn", "url": "https://www.dawn.com/feeds/culture", "lang": "en", "category": "entertainment"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/home", "lang": "en", "category": "pakistan"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/business", "lang": "en", "category": "business"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/sports", "lang": "en", "category": "sports"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/entertainment", "lang": "en", "category": "entertainment"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/world", "lang": "en", "category": "world"},
    {"source": "The Express Tribune", "url": "https://tribune.com.pk/feed/life-style", "lang": "en", "category": "fashion"},
    {"source": "Geo News", "url": "https://www.geo.tv/rss/1/1", "lang": "en", "category": "pakistan"},
    {"source": "The News", "url": "https://www.thenews.com.pk/rss/1/1", "lang": "en", "category": "pakistan"},
    {"source": "ARY News", "url": "https://arynews.tv/feed/", "lang": "en", "category": "pakistan"},
    {"source": "Pakistan Today", "url": "https://www.pakistantoday.com.pk/feed/", "lang": "en", "category": "pakistan"},
    {"source": "Business Recorder", "url": "https://www.brecorder.com/feeds/latest-news", "lang": "en", "category": "business"},
    # Urdu
    {"source": "BBC Urdu", "url": "https://feeds.bbci.co.uk/urdu/rss.xml", "lang": "ur", "category": "pakistan"},
    {"source": "BBC Urdu", "url": "https://feeds.bbci.co.uk/urdu/world/rss.xml", "lang": "ur", "category": "world"},
    {"source": "Express News", "url": "https://www.express.pk/feed/", "lang": "ur", "category": "pakistan"},
    {"source": "Jang", "url": "https://jang.com.pk/rss/1/1", "lang": "ur", "category": "pakistan"},
]

MAX_WORDS = 60            # target summary length
MAX_PER_FEED = 12         # newest stories read from each feed
MAX_NEW_PER_RUN = 60      # stories rewritten per run (keeps cost small)
KEEP_TOTAL = 300          # stories kept in news.json
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news.json")
USER_AGENT = "NewsbriefPK/0.2 (news aggregator)"
CLAUDE_MODEL = "claude-haiku-5-5"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------
def clean_text(raw):
    if not raw:
        return ""
    text = re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text):
    parts = re.split(r"(?<=[.!?؟۔])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def shorten(text, max_words=MAX_WORDS):
    """Fallback only (used when there is no API key)."""
    words_total = text.split()
    if len(words_total) <= max_words:
        return text
    out, count = [], 0
    for sentence in split_sentences(text):
        n = len(sentence.split())
        if count + n > max_words:
            if not out:
                return " ".join(sentence.split()[:max_words]).rstrip(",;:") + "…"
            break
        out.append(sentence)
        count += n
    return " ".join(out) if out else " ".join(words_total[:max_words]) + "…"


# ---------------------------------------------------------------------------
# Claude rewrite
# ---------------------------------------------------------------------------
def parse_rewrite(text):
    """Pull {"headline", "summary"} out of the model reply. None if unusable."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    headline = str(data.get("headline", "")).strip()
    summary = str(data.get("summary", "")).strip()
    if not headline or not summary:
        return None
    if len(summary.split()) > MAX_WORDS + 20:   # far too long: reject
        return None
    return headline, summary


def claude_rewrite(title, body, lang):
    """Ask Claude for a new headline + summary. Returns (headline, summary) or None."""
    language = "Urdu" if lang == "ur" else "English"
    prompt = (
        f"You are a news editor. Write an original news brief in {language} from the "
        "source material below.\n"
        "Rules:\n"
        "- Write a NEW headline of at most 12 words, in your own words.\n"
        f"- Write a summary of at most {MAX_WORDS} words, in your own words. "
        "Do not copy phrases or sentences from the source.\n"
        "- Use only facts stated in the source. Do not add facts, guesses or opinions. "
        "If the source is thin, write a shorter summary.\n"
        "- Neutral tone.\n"
        'Reply with JSON only, exactly like: {"headline": "...", "summary": "..."}\n\n'
        f"SOURCE HEADLINE: {title}\n\nSOURCE TEXT: {body[:3000]}"
    )
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        return parse_rewrite(data["content"][0]["text"])
    except Exception as e:  # noqa: BLE001
        print(f"  ! rewrite failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# feeds
# ---------------------------------------------------------------------------
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


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


def find_image(item):
    for tag in ("media:content", "media:thumbnail"):
        el = item.find(tag, NS)
        if el is not None and el.get("url"):
            return el.get("url")
    enc = item.find("enclosure")
    if enc is not None and (enc.get("type", "").startswith("image")
                            or enc.get("url", "").lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
        return enc.get("url")
    for tag in ("content:encoded", "description"):
        el = item.find(tag, NS if ":" in tag else None)
        if el is not None and el.text:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)', el.text)
            if m:
                return m.group(1)
    return None


def parse_feed(xml_bytes, feed):
    root = ET.fromstring(xml_bytes)
    stories = []
    for item in root.findall(".//item")[:MAX_PER_FEED]:
        link_el = item.find("link")
        title_el = item.find("title")
        if link_el is None or title_el is None or not (link_el.text or "").strip():
            continue
        link = link_el.text.strip()
        desc_el = item.find("content:encoded", NS)
        if desc_el is None or not desc_el.text:
            desc_el = item.find("description")
        stories.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "title": clean_text(title_el.text),
            "body": clean_text(desc_el.text if desc_el is not None else ""),
            "image": find_image(item),
            "published": parse_date(item).isoformat(),
            "source": feed["source"],
            "lang": feed["lang"],
            "category": feed["category"],
        })
    return stories


def source_label(name, lang):
    return f"ذریعہ: {name}" if lang == "ur" else f"Source: {name}"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def load_existing():
    try:
        with open(OUT_FILE, encoding="utf-8") as f:
            stories = json.load(f).get("stories", [])
    except (OSError, ValueError):
        return {}
    # keep only stories Claude rewrote; older copied/placeholder ones are dropped
    return {s["id"]: s for s in stories if s.get("rewritten")}


def main():
    if not API_KEY:
        print("No ANTHROPIC_API_KEY set, so nothing was changed. Add the key under "
              "Settings > Secrets and variables > Actions, then run again.")
        return 0

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
    new_ids = [sid for sid in fresh if sid not in merged]
    new_ids.sort(key=lambda sid: fresh[sid]["published"], reverse=True)   # newest first
    done = 0
    for sid in new_ids:
        s = fresh[sid]
        if done >= MAX_NEW_PER_RUN:
            break                # the rest are picked up on the next run
        result = claude_rewrite(s["title"], s["body"] or s["title"], s["lang"])
        if not result:
            continue             # try again next run; never publish copied text
        headline, summary = result
        merged[sid] = {
            "rewritten": True,
            "id": sid,
            "title": headline,
            "summary": summary,
            "url": "",
            "image": s["image"],
            "published": s["published"],
            "source": source_label(s["source"], s["lang"]),
            "lang": s["lang"],
            "category": s["category"],
        }
        done += 1

    stories = sorted(merged.values(), key=lambda s: s["published"], reverse=True)[:KEEP_TOTAL]
    if not stories:
        print("No stories collected and none saved; leaving news.json untouched.", file=sys.stderr)
        return 1
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "stories": stories},
                  f, ensure_ascii=False, indent=1)
    print(f"Saved {len(stories)} stories ({done} new) to {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
