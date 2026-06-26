#!/usr/bin/env python3
"""
Phase 1 of medium-research: discover candidate articles for a topic.

Sources:
  1. Medium RSS tag feeds (medium.com/feed/tag/<slug>) for slugs derived from the topic
  2. DuckDuckGo HTML search (site:medium.com <topic>)

Output: JSON to stdout with ranked candidates.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (compatible; medium-research/1.0)"
TIMEOUT = 20

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can",
    "this", "that", "these", "those", "i", "you", "we", "they", "it",
}


def http_get(url: str, timeout: int = TIMEOUT) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"WARN: fetch failed for {url}: {e}", file=sys.stderr)
        return None


def derive_slugs(topic: str) -> list[str]:
    """Generate plausible Medium tag slugs from a topic phrase."""
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", topic) if w.lower() not in STOPWORDS]
    if not words:
        return []
    candidates = set()
    candidates.add("-".join(words))
    for w in words:
        if len(w) >= 3:
            candidates.add(w)
    for i in range(len(words) - 1):
        candidates.add(f"{words[i]}-{words[i+1]}")
    if len(words) >= 3:
        for i in range(len(words) - 2):
            candidates.add(f"{words[i]}-{words[i+1]}-{words[i+2]}")
    return sorted(candidates)


def parse_pub_date(s: str) -> str | None:
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def fetch_rss_tag(slug: str) -> list[dict]:
    """Fetch Medium RSS feed for a tag. Returns [] for non-existent tags."""
    body = http_get(f"https://medium.com/feed/tag/{slug}")
    if not body:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    items = root.findall(".//item")
    if len(items) < 3:
        return []  # tag not real / too sparse
    out = []
    for it in items:
        link = (it.findtext("link") or "").split("?")[0]
        if not link:
            continue
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()[:400]
        out.append({
            "title": (it.findtext("title") or "").strip(),
            "url": link,
            "author": (it.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip(),
            "pub_date": parse_pub_date(it.findtext("pubDate") or ""),
            "description": desc,
            "source": f"rss-tag:{slug}",
        })
    return out


def _ddg_candidate(url: str, title: str = "") -> dict:
    return {
        "title": title,
        "url": url,
        "author": "",
        "pub_date": None,
        "description": "",
        "source": "ddg-search",
    }


def fetch_ddg(topic: str) -> list[dict]:
    """Search DuckDuckGo for Medium articles on the topic.

    DDG html.duckduckgo.com requires POST — a GET to /html/ returns the lite
    landing page with no results.
    """
    data = urllib.parse.urlencode({"q": f"site:medium.com {topic}"}).encode("utf-8")
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=data,
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            page = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"WARN: DDG fetch failed: {e}", file=sys.stderr)
        return []

    out: list[dict] = []
    seen: set[str] = set()
    # Standard DDG result form: /l/?uddg=<encoded-url> with title in result__a span
    for m in re.finditer(r'href="(/l/\?[^"]*uddg=[^"]+)"', page):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(m.group(1)).query)
        target = (qs.get("uddg") or [""])[0].split("?")[0]
        if not target or "medium.com" not in target or target in seen:
            continue
        seen.add(target)
        snippet = page[max(0, m.start() - 200): m.end() + 600]
        title_m = re.search(r'class="result__a"[^>]*>([^<]+)<', snippet)
        title = html.unescape(title_m.group(1).strip()) if title_m else ""
        out.append(_ddg_candidate(target, title))
    # Fallback for skins that emit direct medium.com hrefs (rarely fires; kept defensively)
    for m in re.finditer(r'href="(https?://[^"]*medium\.com/[^"?#]+)', page):
        target = m.group(1).split("?")[0]
        if target in seen:
            continue
        seen.add(target)
        out.append(_ddg_candidate(target))
    return out


def canonical_url(url: str) -> str:
    return url.split("?")[0].split("#")[0].rstrip("/")


def slug_word_count(source: str) -> int:
    if not source.startswith("rss-tag:"):
        return 0
    return source[len("rss-tag:"):].count("-") + 1


def topic_word_coverage(c: dict, topic_words: list[str]) -> int:
    haystack = f"{c['title'].lower()} {(c['description'] or '').lower()}"
    return sum(1 for w in topic_words if w in haystack)


def score_candidate(c: dict, topic_words: list[str], days: int) -> float:
    title = c["title"].lower()
    desc = (c["description"] or "").lower()
    score = sum(1 for w in topic_words if w in title) * 3.0
    score += sum(1 for w in topic_words if w in desc)

    if c["pub_date"]:
        try:
            age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(c["pub_date"])).days
            if age_days <= days:
                score += 5.0
            elif age_days <= 2 * days:
                score += 2.0
        except Exception:
            pass

    # Compound RSS slugs are far more specific signals than single-word ones —
    # 'claude-code-skills' is niche, 'best' could be wedding planning.
    sw = slug_word_count(c["source"])
    if sw >= 3:
        score += 3.0
    elif sw == 2:
        score += 2.0

    return score


def in_recency_window(c: dict, days: int) -> bool:
    """DDG-only entries lack dates and are kept; they're filtered later by score."""
    if not c["pub_date"]:
        return True
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(c["pub_date"])).days <= days
    except Exception:
        return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topic", required=True, help="Research topic")
    p.add_argument("--days", type=int, default=90, help="Recency window in days")
    p.add_argument("--top-n", type=int, default=5, help="Articles to mark for extraction")
    p.add_argument("--max-slugs", type=int, default=8, help="Max tag slugs to try")
    args = p.parse_args()

    topic_words = [w for w in re.findall(r"[a-z0-9]+", args.topic.lower()) if w not in STOPWORDS]

    slugs = derive_slugs(args.topic)[: args.max_slugs]

    # Fan out all RSS tag fetches + DDG search concurrently — they're independent
    # IO. Sequential, this took ~3s for an 8-slug topic; parallel ~500ms.
    with ThreadPoolExecutor(max_workers=len(slugs) + 1) as pool:
        rss_futures = [(slug, pool.submit(fetch_rss_tag, slug)) for slug in slugs]
        ddg_future = pool.submit(fetch_ddg, args.topic)
        ddg_results = ddg_future.result()
        rss_results: list[dict] = []
        used_slugs: list[str] = []
        for slug, fut in rss_futures:
            items = fut.result()
            if items:
                used_slugs.append(slug)
                rss_results.extend(items)

    # Merge by canonical URL — prefer RSS entries (have full metadata)
    by_url: dict[str, dict] = {}
    for c in rss_results + ddg_results:
        key = canonical_url(c["url"])
        existing = by_url.get(key)
        if existing is None or (existing["source"] == "ddg-search" and c["source"].startswith("rss-tag")):
            by_url[key] = c

    candidates = [c for c in by_url.values() if in_recency_window(c, args.days)]
    for c in candidates:
        c["score"] = round(score_candidate(c, topic_words, args.days), 2)
        c["topic_coverage"] = topic_word_coverage(c, topic_words)

    # Multi-word topics: require half the topic words in title/desc to filter
    # off-topic single-word RSS slugs. DDG hits exempt — they already matched.
    if len(topic_words) >= 3:
        min_coverage = max(2, len(topic_words) // 2)
        relevant = [c for c in candidates
                    if c["source"] == "ddg-search" or c["topic_coverage"] >= min_coverage]
        if relevant:
            candidates = relevant

    candidates.sort(key=lambda c: c["score"], reverse=True)

    selected = candidates[: args.top_n]
    other = candidates[args.top_n: args.top_n + 25]

    json.dump({
        "topic": args.topic,
        "days_window": args.days,
        "tag_slugs_used": used_slugs,
        "tag_slugs_attempted": slugs,
        "totals": {
            "rss_items": len(rss_results),
            "ddg_items": len(ddg_results),
            "deduped": len(by_url),
            "in_window": len(candidates),
        },
        "selected": selected,
        "other": other,
    }, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
