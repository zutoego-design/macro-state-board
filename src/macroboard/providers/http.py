"""HTTP plumbing: retries, caching, browser-like headers.

Every provider in this package is key-less, so the only robustness needed is
a realistic User-Agent, a couple of retries with backoff, and a disk cache so
a rebuild does not hammer anybody.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


class FetchError(RuntimeError):
    pass


def _cache_path(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:110]
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    d = config.CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.{digest}.bin"


def get(url: str, *, cache_name: str | None = None, max_age_h: float = 0.0,
        timeout: float = 60.0, retries: int = 3, headers: dict | None = None) -> bytes:
    cpath = _cache_path(cache_name or url)
    if max_age_h > 0 and cpath.exists():
        if (time.time() - cpath.stat().st_mtime) / 3600.0 <= max_age_h:
            return cpath.read_bytes()

    hdrs = dict(HEADERS)
    if headers:
        hdrs.update(headers)

    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            cpath.write_bytes(raw)
            return raw
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (400, 403, 404):     # not transient
                break
            time.sleep(1.2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise FetchError(f"GET failed: {url} :: {last}")


def get_json(url: str, **kw) -> dict:
    return json.loads(get(url, **kw).decode("utf-8"))


def get_text(url: str, **kw) -> str:
    raw = get(url, **kw)
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")
