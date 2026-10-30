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
    {"source": "The Express Tribune", "url":
