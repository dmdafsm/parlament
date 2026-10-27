"""Polite HTTP client for the official sites: one client, fixed delay, raw cache under data/raw/."""

import hashlib
import re
import time
from pathlib import Path

import httpx

from parlament.config import Settings, settings

WAYBACK = "https://web.archive.org/web/2030id_/"


class FetchError(Exception):
    """A page could not be downloaded or is not available."""


class Fetcher:
    def __init__(self, conf: Settings | None = None, use_cache: bool = False):
        self.conf = conf or settings()
        self.use_cache = use_cache
        self.client = httpx.Client(
            headers={"User-Agent": self.conf.user_agent, "Accept-Language": "ro"},
            timeout=60,
            follow_redirects=True,
        )
        self._last = 0.0

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def cache_path(self, source: str, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.conf.data_dir / "raw" / source / f"{digest}.html"

    def get(self, source: str, url: str, encoding: str | None = None) -> str:
        """Download `url` (or reuse the raw copy with use_cache) and return decoded text."""
        path = self.cache_path(source, url)
        if self.use_cache and path.exists():
            return decode(path.read_bytes(), encoding)
        target = WAYBACK + url if self.conf.fetch_mode == "wayback" else url
        wait = self.conf.request_delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.client.get(target)
        except httpx.HTTPError as error:
            raise FetchError(f"{url}: {error}") from error
        finally:
            self._last = time.monotonic()
        if response.status_code == 429:
            raise FetchError(f"{url}: rate limited (HTTP 429); stop and retry later")
        if response.status_code != 200:
            raise FetchError(f"{url}: HTTP {response.status_code}")
        if (
            self.conf.fetch_mode == "wayback"
            and "web.archive.org" not in url
            and b"Wayback Machine" in response.content[:3000]
        ):
            raise FetchError(f"{url}: no archived copy")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return decode(response.content, encoding)


def decode(content: bytes, encoding: str | None = None) -> str:
    """cdep.ro serves ISO-8859-2 without a header charset; senat.ro serves UTF-8."""
    if encoding:
        return content.decode(encoding, errors="replace")
    head = content[:2000].lower()
    match = re.search(rb'charset=["\']?([a-z0-9_-]+)', head)
    if match and b"8859-2" not in match.group(1):
        return content.decode(match.group(1).decode(), errors="replace")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("iso-8859-2", errors="replace")
