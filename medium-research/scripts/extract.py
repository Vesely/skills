#!/usr/bin/env python3
"""
Phase 2 of medium-research: extract one Medium article via freedium-mirror.cfd.

Bypasses the member-only paywall using the Freedium mirror. Returns clean text
plus metadata as JSON.

Usage:
    extract.py --url <medium-url> [--save-body <path>]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (compatible; medium-research/1.0)"
MIRROR = "https://freedium-mirror.cfd"
TIMEOUT = 30
MIN_HTML_BYTES = 5000  # Freedium error pages are ~2KB; real articles >>5KB


def http_get(url: str, timeout: int = TIMEOUT) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"WARN: fetch failed: {e}", file=sys.stderr)
        return None


def strip_html(fragment: str) -> str:
    """Strip tags + entities from an HTML fragment, collapse whitespace."""
    fragment = re.sub(r"<script[^>]*>.*?</script>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<style[^>]*>.*?</style>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<!--.*?-->", " ", fragment, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def first_match(pattern: str, source: str, group: int = 1, flags=0) -> str | None:
    m = re.search(pattern, source, flags)
    return m.group(group) if m else None


def parse_freedium(page: str) -> dict:
    """Parse a Freedium-rendered Medium article page.

    Freedium structure (observed):
        <h1 class="pt-6 ... font-bold ...">TITLE</h1>
        <h2 class="pt-1 ... font-medium ...">SUBTITLE</h2>
        <div class="mt-8 main-content">... ARTICLE BODY ...</div>
        <title>TITLE | by AUTHOR - Freedium</title>
        Plain text markers: "Free: Yes/No", "<Month> <D>, <YYYY>", "~N min read"
    """
    result: dict = {
        "title": None, "subtitle": None, "author": None, "date": None,
        "paywall": None, "read_min": None, "body": "", "word_count": 0,
    }

    title_html = first_match(r'<h1[^>]*pt-6[^>]*>(.*?)</h1>', page, flags=re.S)
    if title_html:
        result["title"] = strip_html(title_html)

    subtitle_html = first_match(r'<h2[^>]*pt-1[^>]*>(.*?)</h2>', page, flags=re.S)
    if subtitle_html:
        result["subtitle"] = strip_html(subtitle_html)

    page_title = first_match(r'<title>(.*?)</title>', page, flags=re.S)
    if page_title:
        m = re.search(r"\| by\s+(.+?)\s*-\s*Freedium", strip_html(page_title))
        if m:
            result["author"] = m.group(1).strip()

    # Body: find the main-content div, then walk div depth to find its close.
    main_open = re.search(r'<div[^>]*class="[^"]*main-content[^"]*"[^>]*>', page)
    if main_open:
        depth = 1
        start = main_open.end()
        end_idx = start
        for m in re.finditer(r"<(/?)div\b[^>]*>", page[start:]):
            if m.group(1) == "":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    end_idx = start + m.start()
                    break
        body_html = page[start:end_idx]
        # Insert newlines for block elements before the final tag-strip flattens
        # everything into a single line. Order matters: do <pre> first so its
        # contents survive the later tag strip.
        body_html = re.sub(r"<pre[^>]*>(.*?)</pre>",
                           lambda m: "\n```\n" + m.group(1) + "\n```\n",
                           body_html, flags=re.S | re.I)
        body_html = re.sub(r"</p>|</h[1-6]>", "\n\n", body_html, flags=re.I)
        body_html = re.sub(r"<br\s*/?>|</li>", "\n", body_html, flags=re.I)
        result["body"] = strip_html(body_html)
        result["word_count"] = len(result["body"].split())

    plain = strip_html(page)
    if (m := re.search(r"~(\d+)\s*min read", plain)):
        result["read_min"] = int(m.group(1))
    if (m := re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
        plain,
    )):
        result["date"] = m.group(0)
    if "Free: No" in plain:
        result["paywall"] = True
    elif "Free: Yes" in plain:
        result["paywall"] = False

    return result


def write_body(path: str, parsed: dict, source_url: str) -> None:
    """Write a markdown-ish body file with a metadata header."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if parsed["title"]:
            f.write(f"# {parsed['title']}\n\n")
        if parsed["subtitle"]:
            f.write(f"_{parsed['subtitle']}_\n\n")
        meta = []
        if parsed["author"]: meta.append(f"by {parsed['author']}")
        if parsed["date"]: meta.append(parsed["date"])
        if parsed["read_min"]: meta.append(f"{parsed['read_min']} min read")
        if parsed["paywall"] is True: meta.append("paywalled")
        if meta:
            f.write(" · ".join(meta) + "\n\n")
        f.write(f"Source: {source_url}\n\n---\n\n")
        f.write(parsed["body"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="Original Medium article URL")
    p.add_argument("--save-body", help="Optional path to save full body text as markdown-ish")
    args = p.parse_args()

    medium_url = args.url.split("?")[0]
    page = http_get(f"{MIRROR}/{medium_url}")
    if not page or len(page) < MIN_HTML_BYTES:
        json.dump({
            "extraction_failed": True,
            "url": medium_url,
            "reason": f"http_fetch_failed_or_short ({len(page) if page else 0} bytes)",
        }, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)

    parsed = parse_freedium(page)
    parsed["url"] = medium_url
    parsed["extraction_failed"] = False

    if not parsed["body"] or parsed["word_count"] < 100:
        parsed["extraction_failed"] = True
        parsed["reason"] = "body_extraction_failed_or_short"

    if args.save_body and parsed["body"]:
        try:
            write_body(args.save_body, parsed, medium_url)
            parsed["body_path"] = args.save_body
        except Exception as e:
            parsed["body_path_error"] = str(e)

    json.dump(parsed, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
