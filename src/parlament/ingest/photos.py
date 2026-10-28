"""Official MP photos, downloaded once and resized, so the site serves small images from its own domain."""

import io
import time
from pathlib import Path

import httpx
import psycopg
from PIL import Image, UnidentifiedImageError

from parlament import db
from parlament.config import settings
from parlament.fetch import BlockedError, Fetcher, is_bot_check

SIZES = {"mic": 128, "mare": 480}


def photo_path(member_id: str, size: str) -> Path:
    return settings().data_dir / "photos" / size / f"{member_id}.jpg"


def resize(content: bytes, width: int) -> bytes:
    with Image.open(io.BytesIO(content)) as image:
        image = image.convert("RGB")
        if image.width > width:
            image = image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, "JPEG", quality=82, optimize=True, progressive=True)
        return out.getvalue()


def ingest(conn: psycopg.Connection, fetcher: Fetcher, refresh: bool = False) -> int:
    log = db.log_start(conn, "photos", "photos")
    count, errors = 0, []
    for row in conn.execute("SELECT id, photo_url FROM members WHERE photo_url IS NOT NULL").fetchall():
        if not refresh and all(photo_path(row["id"], size).exists() for size in SIZES):
            continue
        time.sleep(fetcher.conf.request_delay)  # same pace as page requests
        try:
            response = fetcher.client.get(row["photo_url"])
            response.raise_for_status()
            if is_bot_check(response.content):
                raise BlockedError(f"{row['photo_url']}: the site showed a bot check (CAPTCHA)")
            for size, width in SIZES.items():
                path = photo_path(row["id"], size)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(resize(response.content, width))
        except (httpx.HTTPError, UnidentifiedImageError, OSError) as error:  # one bad photo must not stop the run
            errors.append(f"{row['id']}: {error}")
            continue
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
