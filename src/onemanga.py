# onemanga.py — 1manga.co scraper for searching and downloading manga
# Usage: imported by web_app.py
# Requires: requests, beautifulsoup4
#
# Gotchas:
# - Pure HTML scraping, no API.
# - Image CDN at imgx.mghcdn.com — set Referer header to 1manga.co.
# - HTML only shows first few images; rest loaded by JS. Use sequential
#   numbering (1.jpg, 2.jpg, ...) and download until 404.
# - Manga slugs have internal IDs appended (e.g., "oyasumi-punpun_101").
# - Chapter text includes volume info (e.g., "#147-Vol.13 chapter 147").

import re
import time
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://1manga.co"
CDN = "https://imgx.mghcdn.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://1manga.co/",
}


def search_manga(query, limit=20):
    r = requests.get(f"{BASE}/search", params={
        "q": query,
        "order": "POPULAR",
        "genre": "all",
    }, headers=HEADERS, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    seen = set()

    manga_data = {}
    for link in soup.find_all("a", href=re.compile(r"/manga/")):
        href = link.get("href", "")
        slug_match = re.search(r"/manga/([\w-]+)", href)
        if not slug_match:
            continue
        slug = slug_match.group(1)

        if slug not in manga_data:
            manga_data[slug] = {"title": "", "cover_url": "", "slug": slug}

        text = link.get_text(strip=True)
        if text and len(text) >= 2 and not manga_data[slug]["title"]:
            manga_data[slug]["title"] = text

        img = link.find("img")
        if img and not manga_data[slug]["cover_url"]:
            cover = img.get("src", "") or img.get("data-src", "")
            if cover and not cover.startswith("http"):
                cover = BASE + cover
            manga_data[slug]["cover_url"] = cover

    for slug, data in manga_data.items():
        if not data["title"]:
            data["title"] = slug.rsplit("_", 1)[0].replace("-", " ").title()

        results.append({
            "id": slug,
            "slug": slug,
            "title": data["title"],
            "status": "unknown",
            "year": None,
            "cover_url": data["cover_url"],
            "description": "",
        })

        if len(results) >= limit:
            break

    return results


def get_volumes(slug):
    r = requests.get(f"{BASE}/manga/{slug}", headers=HEADERS, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    chapters_by_num = {}
    vol_map = {}

    for link in soup.find_all("a", href=re.compile(r"/chapter/")):
        href = link.get("href", "")
        text = link.get_text(strip=True)

        ch_match = re.search(r"chapter-(\d+(?:\.\d+)?)", href)
        if not ch_match:
            continue

        ch_num = ch_match.group(1)
        if ch_num in chapters_by_num:
            continue

        vol_match = re.search(r"Vol\.(\d+)", text)
        vol = vol_match.group(1) if vol_match else "1"

        manga_name = slug.rsplit("_", 1)[0]

        chapters_by_num[ch_num] = {
            "id": ch_num,
            "chapter": ch_num,
            "volume": vol,
            "title": f"Chapter {ch_num}",
            "manga_name": manga_name,
            "slug": slug,
        }

    volumes = {}
    for ch in chapters_by_num.values():
        vol = ch["volume"]
        if vol not in volumes:
            volumes[vol] = {"chapters": [], "chapter_count": 0}
        volumes[vol]["chapters"].append(ch)
        volumes[vol]["chapter_count"] += 1

    for vol in volumes.values():
        vol["chapters"].sort(key=lambda c: float(c["chapter"]) if c["chapter"].replace(".", "").isdigit() else 999)

    return volumes


def _get_chapter_pages(chapter):
    manga_name = chapter["manga_name"]
    ch_num = chapter["chapter"]

    pages = []
    for p in range(1, 200):
        url = f"{CDN}/{manga_name}/{ch_num}/{p}.jpg"
        try:
            r = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                pages.append(url)
            else:
                break
        except:
            break

    if not pages:
        for ext in ("png", "webp"):
            test_url = f"{CDN}/{manga_name}/{ch_num}/1.{ext}"
            try:
                r = requests.head(test_url, headers=HEADERS, timeout=10)
                if r.status_code == 200:
                    for p in range(1, 200):
                        url = f"{CDN}/{manga_name}/{ch_num}/{p}.{ext}"
                        r2 = requests.head(url, headers=HEADERS, timeout=10)
                        if r2.status_code == 200:
                            pages.append(url)
                        else:
                            break
                    break
            except:
                continue

    return pages


def download_volume_as_cbz(manga_title, volume_num, chapters, output_dir, progress=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_title = "".join(c for c in manga_title if c.isalnum() or c in " -_").strip()
    vol_label = f"Vol.{volume_num}" if volume_num != "1" else f"Ch.{chapters[0]['chapter']}-{chapters[-1]['chapter']}"
    cbz_name = f"{safe_title} {vol_label}.cbz"
    cbz_path = output_dir / cbz_name

    if progress:
        progress(f"Downloading {vol_label} ({len(chapters)} chapters)...")

    page_num = 0
    with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_STORED) as zf:
        for ci, chapter in enumerate(chapters):
            if progress:
                progress(f"  Chapter {chapter['chapter']} ({ci + 1}/{len(chapters)})")

            try:
                page_urls = _get_chapter_pages(chapter)
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
                    zf.writestr(f"{page_num:05d}.{ext}", img_r.content)
                    page_num += 1
                except Exception as e:
                    if progress:
                        progress(f"  Page {pi} failed: {e}")

    if progress:
        size_mb = cbz_path.stat().st_size / (1024 * 1024)
        progress(f"  Saved: {cbz_name} ({size_mb:.1f} MB, {page_num} pages)")

    return cbz_path
