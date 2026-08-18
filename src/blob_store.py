# blob_store.py — Vercel Blob storage client for EPUB delivery to XTe Ink
# Usage: imported by web_app.py
# Requires: requests
# Env vars: BLOB_READ_WRITE_TOKEN
#
# Gotchas:
# - Vercel Blob REST API, not the JS SDK (we're in Python)
# - PUT to upload, GET to list, POST /delete to remove
# - Files are publicly accessible via URL but OPDS feed is auth-protected
# - addRandomSuffix=false equivalent: x-add-random-suffix: 0

import os
import requests

BLOB_API = "https://blob.vercel-storage.com"


def _token():
    return os.environ.get("BLOB_READ_WRITE_TOKEN", "")


def is_configured():
    return bool(_token())


def upload(filepath, filename):
    """Upload a file to Vercel Blob. Returns blob URL."""
    token = _token()
    if not token:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN not set")

    pathname = f"books/{filename}"
    with open(filepath, "rb") as f:
        data = f.read()

    content_type = "application/octet-stream" if filename.endswith(".xtc") else "application/epub+zip"
    resp = requests.put(
        f"{BLOB_API}/{pathname}",
        headers={
            "authorization": f"Bearer {token}",
            "x-content-type": content_type,
            "x-add-random-suffix": "0",
        },
        data=data,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["url"]


def upload_bytes(data, filename):
    """Upload raw bytes to Vercel Blob. Returns blob URL."""
    token = _token()
    if not token:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN not set")

    pathname = f"books/{filename}"
    content_type = "application/octet-stream" if filename.endswith(".xtc") else "application/epub+zip"
    resp = requests.put(
        f"{BLOB_API}/{pathname}",
        headers={
            "authorization": f"Bearer {token}",
            "x-content-type": content_type,
            "x-add-random-suffix": "0",
        },
        data=data,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["url"]


def list_files():
    """List all files in the books/ prefix. Returns list of {url, pathname, size, uploadedAt}."""
    token = _token()
    if not token:
        return []

    resp = requests.get(
        BLOB_API,
        params={"prefix": "books/"},
        headers={"authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("blobs", [])


def delete(url):
    """Delete a file from Vercel Blob by URL."""
    token = _token()
    if not token:
        return

    resp = requests.post(
        f"{BLOB_API}/delete",
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        },
        json={"urls": [url]},
        timeout=30,
    )
    resp.raise_for_status()
