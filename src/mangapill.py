# mangapill.py — MangaPill scraper for searching and downloading manga
# Usage: imported by web_app.py
# Requires: requests, beautifulsoup4
#
# Gotchas:
# - HTML scraping, no API, but clean and consistent structure.
# - Images on cdn.readdetectiveconan.com — set Referer to mangapill.com.
# - No Cloudflare protection as of 2025.
# - Chapters listed newest-first on manga page — reverse for volume ordering.
# - No explicit volume info — chapters are flat-listed.

import re
import time
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://mangapill.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://mangapill.com/",
}


def search_manga(query, limit=20):
    r = requests.get(f"{BASE}/search", params={"q": query}, headers=HEADERS, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    manga_data = {}
    for card in soup.select("a[href*='/manga/']"):
        href = card.get("href", "")
        slug_match = re.search(r"/manga/(\d+)/(.+)", href)
        if not slug_match:
            continue

        manga_id = slug_match.group(1)
        slug = slug_match.group(2)

        if manga_id not in manga_data:
            manga_data[manga_id] = {"id": manga_id, "slug": slug, "title": "", "cover_url": ""}

        img = card.find("img")
        if img and not manga_data[manga_id]["cover_url"]:
            manga_data[manga_id]["cover_url"] = img.get("src", "") or img.get("data-src", "")

        title_div = card.find("div", class_="leading-tight")
        text = title_div.get_text(strip=True) if title_div else card.get_text(strip=True)
        if text and len(text) > 2 and not manga_data[manga_id]["title"]:
            manga_data[manga_id]["title"] = text

    for data in manga_data.values():
        if not data["title"]:
            data["title"] = data["slug"].replace("-", " ").title()

        results.append({
            "id": data["id"],
            "slug": data["slug"],
            "title": data["title"],
            "status": "unknown",
            "year": None,
            "cover_url": data["cover_url"],
            "description": "",
        })

        if len(results) >= limit:
            break

    return results


def get_volumes(manga_id, slug):
    r = requests.get(f"{BASE}/manga/{manga_id}/{slug}", headers=HEADERS, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    chapters = []
    seen = set()

    for link in soup.select("a[href*='/chapters/']"):
        href = link.get("href", "")
        ch_match = re.search(r"chapter-(\d+(?:\.\d+)?)", href)
        if not ch_match:
            continue

        ch_num = ch_match.group(1)
        if ch_num in seen:
            continue
        seen.add(ch_num)

        chapters.append({
            "id": ch_num,
            "chapter": ch_num,
            "title": f"Chapter {ch_num}",
            "url": href if href.startswith("http") else BASE + href,
        })

    chapters.sort(key=lambda c: float(c["chapter"]) if c["chapter"].replace(".", "").isdigit() else 999)

    volumes = {"1": {"chapters": chapters, "chapter_count": len(chapters)}}
    return volumes


def _get_chapter_pages(chapter_url):
    r = requests.get(chapter_url, headers=HEADERS, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    pages = []

    for img in soup.select("chapter-page img, img[chapter-page]"):
        src = img.get("src", "") or img.get("data-src", "")
        if src:
            pages.append(src)

    if not pages:
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if re.search(r"(mangap|chapter|readdetectiveconan)", src, re.I):
                pages.append(src)

    if not pages:
        text = r.text
        pages = re.findall(r'"(https?://cdn\.[^"]+/file/mangap/[^"]+)"', text)

    return pages


def download_volume_as_cbz(manga_title, chapters, output_dir, progress=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_title = "".join(c for c in manga_title if c.isalnum() or c in " -_").strip()
    ch_first = chapters[0]["chapter"]
    ch_last = chapters[-1]["chapter"]
    cbz_name = f"{safe_title} Ch.{ch_first}-{ch_last}.cbz"
    cbz_path = output_dir / cbz_name

    if progress:
        progress(f"Downloading Ch.{ch_first}-{ch_last} ({len(chapters)} chapters)...")

    page_num = 0
    with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_STORED) as zf:
        for ci, chapter in enumerate(chapters):
            if progress:
                progress(f"  Chapter {chapter['chapter']} ({ci + 1}/{len(chapters)})")

            try:
                page_urls = _get_chapter_pages(chapter["url"])
            except Exception as e:
                if progress:
                    progress(f"  Skipping chapter {chapter['chapter']}: {e}")
                continue

            for pi, url in enumerate(page_urls):
                time.sleep(0.1)
                try:
                    img_r = requests.get(url, headers=HEADERS, timeout=30)
                    img_r.raise_for_status()
                    ext = url.rsplit(".", 1)[-1].split("?")[0]
                    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                        ext = "jpg"
                    zf.writestr(f"{page_num:05d}.{ext}", img_r.content)
                    page_num += 1
                except Exception as e:
                    if progress:
                        progress(f"  Page {pi} failed: {e}")

    if progress:
        size_mb = cbz_path.stat().st_size / (1024 * 1024)
        progress(f"  Saved: {cbz_name} ({size_mb:.1f} MB, {page_num} pages)")

    return cbz_path
