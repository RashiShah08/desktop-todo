"""Tech news headlines from a curated mix of sources.

Sources (all free, no API keys):
  Tools & new launches:
    • Hacker News "Show HN"        — new projects + tools the community is making
    • Product Hunt                 — daily new products
  Inventions & research:
    • Ars Technica                 — deep tech, science, engineering
    • MIT Technology Review        — cutting-edge research, future tech
    • IEEE Spectrum                — engineering, robotics, electronics
  Industry & market:
    • Hacker News Top              — top stories (broad CS/programming)
    • TechCrunch                   — startup / industry / funding
    • The Verge                    — consumer tech, AI
    • VentureBeat                  — AI + enterprise tech

Cached to cache/news.json for offline display."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False


from paths import user_root
CACHE_PATH = user_root() / "cache" / "news.json"
FETCH_TIMEOUT = 6   # seconds per HTTP request


@dataclass
class Headline:
    title: str
    url: str
    source: str
    timestamp: Optional[float] = None
    description: Optional[str] = None    # 1-2 sentence summary, plain text

    def to_dict(self):
        return asdict(self)


def _strip_html(s: str) -> str:
    """Crude but works for RSS summaries: tags out, entities decoded, whitespace collapsed."""
    if not s:
        return ""
    import re
    import html
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ─────────────────────────────────────────────────────────────────────
# Fetchers
# ─────────────────────────────────────────────────────────────────────

def _fetch_hn(limit: int = 5) -> list[Headline]:
    if not HAS_REQUESTS:
        return []
    try:
        r = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json",
                         timeout=FETCH_TIMEOUT)
        r.raise_for_status()
        ids = r.json()[:limit * 2]
        out = []
        for sid in ids:
            if len(out) >= limit:
                break
            try:
                ri = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                                  timeout=FETCH_TIMEOUT)
                item = ri.json()
            except (requests.RequestException, ValueError):
                continue
            if not item or item.get("type") != "story":
                continue
            url = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"
            ts = item.get("time")
            out.append(Headline(title=item["title"], url=url,
                                source="Hacker News", timestamp=ts))
        return out
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"[news] HN fetch failed: {e}", file=sys.stderr)
        return []


def _fetch_rss(url: str, source_name: str, limit: int = 5) -> list[Headline]:
    if not HAS_FEEDPARSER:
        return []
    try:
        feed = feedparser.parse(url)
        out = []
        import time
        for entry in feed.entries[:limit]:
            title = entry.get("title")
            link = entry.get("link")
            if not (title and link):
                continue
            ts = None
            for key in ("published_parsed", "updated_parsed"):
                pp = entry.get(key)
                if pp:
                    try:
                        ts = time.mktime(pp)
                        break
                    except (TypeError, OverflowError):
                        pass
            # Pull a description — try multiple field names that different feeds use
            raw_desc = ""
            for key in ("summary", "description"):
                v = entry.get(key)
                if v:
                    raw_desc = v
                    break
            if not raw_desc:
                content = entry.get("content")
                if content and isinstance(content, list) and content:
                    raw_desc = content[0].get("value", "") if isinstance(content[0], dict) else ""
            desc = _strip_html(raw_desc)
            if len(desc) > 260:
                desc = desc[:257].rstrip() + "…"
            out.append(Headline(title=title.strip(), url=link,
                                source=source_name, timestamp=ts,
                                description=desc or None))
        return out
    except Exception as e:
        print(f"[news] {source_name} fetch failed: {e}", file=sys.stderr)
        return []


# ─────────────────────────────────────────────────────────────────────
# Aggregate + cache
# ─────────────────────────────────────────────────────────────────────

SOURCES = [
    # (display name, fetch function, args)
    ("Show HN — new tools",       "_fetch_rss", "https://hnrss.org/show?points=10"),
    ("Product Hunt — launches",   "_fetch_rss", "https://www.producthunt.com/feed"),
    ("Ars Technica — research",   "_fetch_rss", "https://feeds.arstechnica.com/arstechnica/index"),
    ("MIT Tech Review — future",  "_fetch_rss", "https://www.technologyreview.com/feed/"),
    ("IEEE Spectrum — engineering", "_fetch_rss", "https://spectrum.ieee.org/feeds/feed.rss"),
    ("Hacker News — top",         "_fetch_hn",  None),
    ("TechCrunch — startups",     "_fetch_rss", "https://techcrunch.com/feed/"),
    ("The Verge — consumer tech", "_fetch_rss", "https://www.theverge.com/rss/index.xml"),
    ("VentureBeat — AI & enterprise", "_fetch_rss", "https://venturebeat.com/feed/"),
]


def fetch_all(per_source: int = 5) -> list[Headline]:
    """Fetch every source in parallel, dedupe by title, return one flat list
    sorted by recency (newest first). Sources with no timestamp fall to the
    bottom.

    Parallel fetch cuts the worst-case wait from ~54s (9 sources × 6s timeout
    sequential) down to ~6s (the slowest single source). Each future has its
    own timeout guard so a hung source can't stall the whole batch."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    items: list[Headline] = []
    seen_titles: set[str] = set()

    with ThreadPoolExecutor(max_workers=len(SOURCES) or 1) as ex:
        future_to_name: dict = {}
        for name, fn_name, arg in SOURCES:
            if fn_name == "_fetch_hn":
                fut = ex.submit(_fetch_hn, per_source)
            else:
                fut = ex.submit(_fetch_rss, arg, name, per_source)
            future_to_name[fut] = name

        for fut in as_completed(future_to_name, timeout=FETCH_TIMEOUT * 2 + 1):
            name = future_to_name[fut]
            try:
                got = fut.result()
            except Exception as e:
                print(f"[news] source '{name}' failed: {e}", file=sys.stderr)
                continue
            for h in got:
                key = h.title.strip().lower()
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                items.append(Headline(title=h.title, url=h.url,
                                      source=name, timestamp=h.timestamp))

    items.sort(key=lambda h: h.timestamp if h.timestamp else 0, reverse=True)
    return items


def save_cache(headlines: list[Headline]) -> datetime:
    """Persist headlines and return the timestamp used."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().replace(microsecond=0)
    payload = {
        "fetched_at": now.isoformat(),
        "headlines": [h.to_dict() for h in headlines],
    }
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[news] cache save failed: {e}", file=sys.stderr)
    return now


def load_cache() -> tuple[list[Headline], Optional[datetime]]:
    """Return (headlines, fetched_at) from cache. Empty list if no cache."""
    if not CACHE_PATH.exists():
        return [], None
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = [Headline(**h) for h in data.get("headlines", [])]
        ts = data.get("fetched_at")
        when = datetime.fromisoformat(ts) if ts else None
        return items, when
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"[news] cache load failed: {e}", file=sys.stderr)
        return [], None


def get_news(force_refresh: bool = False) -> tuple[list[Headline], Optional[datetime], bool]:
    """High-level: returns (headlines, fetched_at, was_fresh).
    - If cache is from today and not force_refresh: use cache (was_fresh=False)
    - Otherwise: fetch fresh, save cache, return (was_fresh=True)
    - If fresh fetch fails: fall back to cached data with was_fresh=False"""
    cached, cached_ts = load_cache()

    if not force_refresh and cached_ts and cached_ts.date() == date.today() and cached:
        return cached, cached_ts, False

    fresh = fetch_all()
    if fresh:
        ts = save_cache(fresh)
        return fresh, ts, True

    # Fetch failed → fall back to cache (could be from a prior day)
    return cached, cached_ts, False
