# mangadex.py — MangaDex API wrapper for searching and downloading manga
# Usage: imported by web_app.py, not run directly
# Requires: requests
#
# Gotchas:
# - MangaDex rate limit is 5 req/sec — respect it with sleeps between page downloads.
# - Multiple scanlation groups may upload the same chapter — we pick the first match per chapter number.
# - Some manga have no english translations — filter with availableTranslatedLanguage.
# - Volume can be None for bonus/extra chapters — group these under "Extras".
# - Cover art URL format: https://uploads.mangadex.org/covers/{mangaId}/{fileName}.256.jpg

import io
import time
import zipfile
from pathlib import Path

import requests

API = "https://api.mangadex.org"
COVERS = "https://uploads.mangadex.org/covers"


def search_manga(query, limit=20, unfiltered=False):
    """Search MangaDex for manga by title. Returns list of results with cover URLs.
    Filters out doujinshi and sorts official manga first.
    When unfiltered=True, includes pornographic content rating."""
    ratings = ["safe", "suggestive", "erotica"]
    if unfiltered:
        ratings.append("pornographic")
    r = requests.get(f"{API}/manga", params={
        "title": query,
        "limit": limit,
        "includes[]": "cover_art",
        "availableTranslatedLanguage[]": "en",
        "order[relevance]": "desc",
        "contentRating[]": ratings,
    }, timeout=10)
    r.raise_for_status()
    data = r.json()

    results = []
    for manga in data.get("data", []):
        attrs = manga["attributes"]
        title = attrs["title"]
        display_title = title.get("en") or title.get("ja-ro") or title.get("ja") or next(iter(title.values()), "Unknown")

        tags = {t["attributes"]["name"].get("en", "") for t in attrs.get("tags", [])}
        is_doujinshi = "Doujinshi" in tags

        cover_file = None
        for rel in manga.get("relationships", []):
            if rel["type"] == "cover_art" and "attributes" in rel:
                cover_file = rel["attributes"]["fileName"]
                break

        cover_url = f"{COVERS}/{manga['id']}/{cover_file}.256.jpg" if cover_file else None

        results.append({
            "id": manga["id"],
            "title": display_title,
            "status": attrs.get("status", "unknown"),
            "year": attrs.get("year"),
            "cover_url": cover_url,
            "description": (attrs.get("description", {}).get("en") or "")[:200],
            "doujinshi": is_doujinshi,
        })

    # Sort: official manga first, then doujinshi
    results.sort(key=lambda x: (x["doujinshi"], x["title"]))
    return results


def get_volumes(manga_id, unfiltered=False):
    """Get available volumes for a manga (english translations only).
    Returns dict of volume_number -> {chapters: [...], chapter_count: N}
    """
    ratings = ["safe", "suggestive", "erotica"]
    if unfiltered:
        ratings.append("pornographic")
    chapters_by_num = {}
    offset = 0
    limit = 500

    while True:
        r = requests.get(f"{API}/manga/{manga_id}/feed", params={
            "translatedLanguage[]": "en",
            "order[volume]": "asc",
            "order[chapter]": "asc",
            "limit": limit,
            "offset": offset,
            "includes[]": "scanlation_group",
            "contentRating[]": ratings,
        }, timeout=15)
        r.raise_for_status()
        data = r.json()

        for ch in data.get("data", []):
            attrs = ch["attributes"]
            ch_num = attrs.get("chapter")
            if ch_num is None:
                continue
            if ch_num in chapters_by_num:
                continue
            # Skip external-only chapters (e.g. hosted on viz.com) — no downloadable pages
            if attrs.get("externalUrl") and attrs.get("pages", 0) == 0:
                continue
            chapters_by_num[ch_num] = {
                "id": ch["id"],
                "chapter": ch_num,
                "volume": attrs.get("volume") or "Extras",
                "title": attrs.get("title") or f"Chapter {ch_num}",
                "pages": attrs.get("pages", 0),
            }

        if offset + limit >= data.get("total", 0):
            break
        offset += limit
        time.sleep(0.3)

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


def _download_chapter_pages(chapter_id):
    """Get page URLs for a chapter from the at-home API."""
    r = requests.get(f"{API}/at-home/server/{chapter_id}", timeout=10)
    r.raise_for_status()
    data = r.json()

    base_url = data["baseUrl"]
    ch = data["chapter"]
    pages = []
    for filename in ch["data"]:
        pages.append(f"{base_url}/data/{ch['hash']}/{filename}")
    return pages


def download_volume_as_cbz(manga_id, manga_title, volume_num, chapters, output_dir, progress=None):
    """Download all pages for a volume's chapters and pack into a CBZ file.

    Args:
        manga_id: MangaDex manga UUID
        manga_title: display title for filename
        volume_num: volume number string
        chapters: list of chapter dicts from get_volumes()
        output_dir: Path to save the CBZ
        progress: optional callback(message_string)

    Returns: Path to the created CBZ file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_title = "".join(c for c in manga_title if c.isalnum() or c in " -_").strip()
    vol_label = f"Vol.{volume_num}" if volume_num != "Extras" else "Extras"
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
                page_urls = _download_chapter_pages(chapter["id"])
            except Exception as e:
                if progress:
                    progress(f"  Skipping chapter {chapter['chapter']}: {e}")
                continue

            for pi, url in enumerate(page_urls):
                time.sleep(0.15)
                try:
                    img_r = requests.get(url, timeout=30)
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
