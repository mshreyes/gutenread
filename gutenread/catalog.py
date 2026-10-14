"""Book catalogue (Gutendex) and plain-text download (Project Gutenberg)."""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import store

API = "https://gutendex.com/books"
USER_AGENT = "GutenRead/0.1 (speed-reading app; https://github.com/YOUR-USER/gutenread)"
MIN_GAP_SECONDS = 2.0   # Project Gutenberg robot policy: >= 2 s between requests

_lock = threading.Lock()
_last_request = 0.0


@dataclass
class Book:
    id: int
    title: str
    author: str
    text_url: str
    downloads: int = 0


def _open(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def _throttle() -> None:
    global _last_request
    with _lock:
        wait = _last_request + MIN_GAP_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _flip(name: str) -> str:
    """'Austen, Jane' -> 'Jane Austen'."""
    last, sep, first = name.partition(", ")
    return f"{first} {last}".strip() if sep else name


def pick_text_url(formats: dict) -> str | None:
    best = None
    for mime, url in formats.items():
        if not mime.startswith("text/plain") or url.endswith(".zip"):
            continue
        if "utf-8" in mime:
            return url
        best = best or url
    return best


def search(query: str = "", page_url: str | None = None, language: str = "en"):
    """Return (books, next_page_url). Empty query lists the most popular books."""
    if page_url:
        url = page_url
    else:
        params = {"languages": language}
        if query:
            params["search"] = query
        url = f"{API}?{urllib.parse.urlencode(params)}"
    with _open(url, timeout=20) as resp:
        data = json.load(resp)
    books = []
    for item in data.get("results", []):
        text_url = pick_text_url(item.get("formats", {}))
        if not text_url:
            continue
        authors = "; ".join(_flip(a["name"]) for a in item.get("authors", [])[:2])
        books.append(Book(item["id"], " ".join(item["title"].split()),
                          authors or "Unknown", text_url, item.get("download_count", 0)))
    return books, data.get("next")


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def fetch_text(book: Book) -> str:
    """Return the book's plain text, downloading once and caching afterwards."""
    path = store.CACHE_DIR / f"{book.id}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    _throttle()
    with _open(book.text_url, timeout=60) as resp:
        text = decode(resp.read())
    if "<html" in text[:300].lower():
        raise RuntimeError("The server returned a web page instead of the book.")
    try:
        store.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return text
