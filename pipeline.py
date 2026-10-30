#!/usr/bin/env python3
"""
Newsbrief PK - news collector (version 3, works with a FREE Gemini key).

1. Reads RSS feeds from Pakistani news outlets.
2. Asks an AI model to write a NEW headline and a ~60 word summary in its own
   words (several stories per request, to stay inside free limits).
3. Saves everything to news.json for the reader page.
Cards show only "Source: <outlet>". No link and no copied text.

Keys (set in GitHub: Settings > Secrets and variables > Actions):
  GEMINI_API_KEY     free key from aistudio.google.com   (used first)
  ANTHROPIC_API_KEY  optional paid alternative
With no key the script changes nothing.
"""

import hashlib
import html
import json
import os
import re
import sys
import urllib.error
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
BATCH_SIZE = 8            # stories rewritten per AI request
MAX_NEW_PER_RUN = 24      # stories rewritten per run (the rest wait for next run)
KEEP_TOTAL = 300          # stories kept in news.json
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news.json")
USER_AGENT = "NewsbriefPK/0.3 (news aggregator)"

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"
CLAUDE_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = "claude-haiku-5-5"

NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class RateLimited(Exception):
    """The AI service said we used up the free allowance for now."""


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


# ---------------------------------------------------------------------------
# AI rewrite
# ---------------------------------------------------------------------------
def post_json(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(str(e))
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"HTTP {e.code} {detail}")


def call_model(prompt):
    """Send one prompt to the available AI service and return its text reply."""
    if GEMINI_KEY:
        data = post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            {"contents": [{"parts": [{"text": prompt}]}]},
            {"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"},
        )
        return data["candidates"][0]["content"]["parts"][0]["text"]
    data = post_json(
        "https://api.anthropic.com/v1/messages",
        {"model": CLAUDE_MODEL, "max_tokens": 4000,
         "messages": [{"role": "user", "content": prompt}]},
        {"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01",
         "content-type": "application/json"},
    )
    return data["content"][0]["text"]


def parse_batch(text, count):
    """Turn the model reply into {number: (headline, summary)}. Bad items are left out."""
    if not text:
        return {}
    m = re.search(r"\[.*\]", text, flags=re.S)
    if not m:
        return {}
    try:
        rows = json.loads(m.group(0))
    except ValueError:
        return {}
    out = {}
    for row in rows if isinstance(rows, list) else []:
        try:
            n = int(row.get("n"))
            headline = str(row.get("headline", "")).strip()
            summary = str(row.get("summary", "")).strip()
        except (AttributeError, TypeError, ValueError):
            continue
        if not (1 <= n <= count) or not headline or not summary:
            continue
        if len(summary.split()) > MAX_WORDS + 20:
            continue
        out[n] = (headline, summary)
    return out


def rewrite_batch(stories, lang):
    """Rewrite a list of same-language stories. Returns {index_in_list: (headline, summary)}."""
    language = "Urdu" if lang == "ur" else "English"
    items = "\n\n".join(
        f"[{i}] HEADLINE: {s['title']}\nTEXT: {(s['body'] or s['title'])[:1200]}"
        for i, s in enumerate(stories, 1)
    )
    prompt = (
        f"You are a news editor. For each numbered source story below, write an original "
        f"news brief in {language}.\n"
        "Rules for every story:\n"
        "- Write a NEW headline of at most 12 words, in your own words.\n"
        f"- Write a summary of at most {MAX_WORDS} words, in your own words. "
        "Do not copy phrases or sentences from the source.\n"
        "- Use only facts stated in the source. Do not add facts, guesses or opinions. "
        "If the source is thin, write a shorter summary.\n"
        "- Neutral tone.\n"
        'Reply with a JSON array only, one object per story, exactly like: '
        '[{"n": 1, "headline": "...", "summary": "..."}, {"n": 2, ...}]\n\n'
        f"{items}"
    )
    return parse_batch(call_model(prompt), len(stories))


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
    # keep only stories the AI rewrote; older copied/placeholder ones are dropped
    return {s["id"]: s for s in stories if s.get("rewritten")}


def main():
    if not (GEMINI_KEY or CLAUDE_KEY):
        print("No API key set, so nothing was changed. Add GEMINI_API_KEY under "
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
    todo = [fresh[sid] for sid in fresh if sid not in merged]
    todo.sort(key=lambda s: s["published"], reverse=True)          # newest first
    todo = todo[:MAX_NEW_PER_RUN]

    done = 0
    try:
        for lang in ("en", "ur"):
            group = [s for s in todo if s["lang"] == lang]
            for i in range(0, len(group), BATCH_SIZE):
                batch = group[i:i + BATCH_SIZE]
                try:
                    results = rewrite_batch(batch, lang)
                except RateLimited:
                    raise
                except Exception as e:  # noqa: BLE001
                    print(f"  ! batch failed, will retry next run: {e}", file=sys.stderr)
                    continue
                for n, (headline, summary) in results.items():
                    s = batch[n - 1]
                    merged[s["id"]] = {
                        "id": s["id"],
                        "rewritten": True,
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
    except RateLimited:
        print("Free allowance used up for now. The rest will be done on the next run.")

    stories = sorted(merged.values(), key=lambda s: s["published"], reverse=True)[:KEEP_TOTAL]
    if not stories:
        print("No stories written yet; leaving news.json untouched.")
        return 0
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "stories": stories},
                  f, ensure_ascii=False, indent=1)
    print(f"Saved {len(stories)} stories ({done} new) to {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
