#!/usr/bin/env python3
"""Download the DVB Wandertipps GPX files and their public travel notes."""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://www.dvb.de"
INDEX = f"{BASE}/de-de/entdecken/wandertipps"
ROOT = Path(__file__).resolve().parents[1]
TRACK_DIR = ROOT / "tracks"
DATA_FILE = ROOT / "data" / "routes.json"


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "li", "br"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"[ \t]*\n[ \t]*", "\n", "".join(self.parts))


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "DVB-Wandertipps-Karte/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read(), response.headers.get_content_type()


def get_text(source: str) -> str:
    parser = TextExtractor()
    parser.feed(source)
    return re.sub(r"\n{2,}", "\n", parser.text()).strip()


def travel_info(text: str) -> tuple[str, str]:
    return_label = r"Rückfahr(?:t)?möglichkeit(?:en)?"
    stop = r"(?:Tariftipps|Download|Festes Schuhwerk|Die Tour|Bitte beachten|Tipp:|Die Wanderung)"
    start = re.search(rf"Erreichbarkeit(?: des Startpunktes)?\s*:\s*(.*?)(?=\s*{return_label}\s*:|\s*{stop})", text, re.S | re.I)
    back = re.search(rf"{return_label}\s*:\s*(.*?)(?=\s*{stop})", text, re.S | re.I)
    clean = lambda value: re.sub(r"\s+", " ", value).strip(" -\n") if value else "Nicht angegeben"
    return clean(start.group(1) if start else ""), clean(back.group(1) if back else "")


def main() -> int:
    index, _ = fetch(INDEX)
    page_html = index.decode("utf-8", errors="replace")
    hrefs = re.findall(r'href="(/de-de/entdecken/wandertipps/[^"?#]+)', page_html)
    urls = []
    for href in hrefs:
        url = urllib.parse.urljoin(BASE, html.unescape(href))
        if url != INDEX and url not in urls:
            urls.append(url)
    if len(urls) != 27:
        raise RuntimeError(f"Expected 27 tour pages, found {len(urls)}")

    TRACK_DIR.mkdir(exist_ok=True)
    DATA_FILE.parent.mkdir(exist_ok=True)
    routes = []
    for fallback_id, url in enumerate(urls, start=1):
        page, _ = fetch(url)
        source = page.decode("utf-8", errors="replace")
        text = get_text(source)
        title = re.search(r"Streifzug\s*(\d+)\s*:\s*(.+?)(?=\n|\|)", text, re.I)
        route_id = int(title.group(1)) if title else fallback_id
        name = title.group(2).strip() if title else re.search(r"<title>(.*?)\s*-\s*DVB", source, re.S).group(1).strip()
        name = re.sub(r"\s*(?:-\s*DVB)?\s*\"\s*$", "", name).strip()
        gpx = re.search(r'href="([^"]+\.gpx(?:\?[^"]*)?)"', source, re.I)
        if not gpx:
            raise RuntimeError(f"No GPX link found for {url}")
        gpx_url = urllib.parse.urljoin(BASE, html.unescape(gpx.group(1)))
        filename = f"{route_id:02d}.gpx"
        content, content_type = fetch(gpx_url)
        if b"<gpx" not in content[:2000].lower():
            raise RuntimeError(f"Invalid GPX response for {url} ({content_type})")
        (TRACK_DIR / filename).write_bytes(content)
        start, back = travel_info(text)
        routes.append({
            "id": route_id, "name": html.unescape(name), "page": url,
            "gpx": f"tracks/{filename}", "start": start, "return": back,
        })
        print(f"{route_id:02d}: {filename} – {name}")
        time.sleep(0.1)

    routes.sort(key=lambda route: route["id"])
    DATA_FILE.write_text(json.dumps(routes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(routes)} GPX tracks into {TRACK_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
