"""Download the pinned frontend assets into the web package (served locally: no third-party requests).

Beer CSS lists its CDN as a fallback source for the icon fonts; that fallback is removed so the strict
Content-Security-Policy (font-src 'self') holds. Hashes are of the files as written.
Run after changing a version below; commit the files together with the new hashes.
"""

import hashlib
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "parlament" / "web" / "static" / "vendor"
ASSETS = {
    # name: (url, sha256)
    "beer.min.css": (
        "https://cdn.jsdelivr.net/npm/beercss@5.0.3/dist/cdn/beer.min.css",
        "4a4b6e4883562436091f2c243f996843092d48c5329f020734cecb5ddf9a672f",
    ),
    "beer.min.js": (
        "https://cdn.jsdelivr.net/npm/beercss@5.0.3/dist/cdn/beer.min.js",
        "992306080b2ad5d0f21a812b473d3d8b26fe5b9a731e29035853d79a766f640f",
    ),
    "material-symbols-outlined.woff2": (
        "https://cdn.jsdelivr.net/npm/beercss@5.0.3/dist/cdn/material-symbols-outlined.woff2",
        "03b6140920800c51082ba3e8dfef47a8658e223878c64cc3ef1ac5f37d519e1a",
    ),
    "material-symbols-subset.woff2": (
        "https://cdn.jsdelivr.net/npm/beercss@5.0.3/dist/cdn/material-symbols-subset.woff2",
        "0946c928c4c95065ab04b8de7907829784d60b5025baee81348cf10f45c78be3",
    ),
    "htmx.min.js": (
        "https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js",
        "d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717",
    ),
}


def main(check_only: bool = False) -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in ASSETS.items():
        path = TARGET / name
        if not check_only:
            with urllib.request.urlopen(url, timeout=60) as response:
                content = response.read()
            if name.endswith(".css"):
                content = re.sub(rb',url\(https://cdn\.jsdelivr\.net/[^)]*\) format\("woff2"\)', b"", content)
            path.write_bytes(content)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected and digest != expected:
            print(f"FAIL: {name} sha256 {digest} != {expected}", file=sys.stderr)
            return 1
        print(f"{name} {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
