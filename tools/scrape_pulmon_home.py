#!/usr/bin/env python3
"""
One-shot snapshot of https://www.pulmonverdepdc.com/ homepage assets.
Downloads HTML (if missing) and all same-origin URLs found in HTML + linked CSS url(...).
Does not crawl other HTML pages (WordPress site is large). For offline use, open index-offline.html.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import subprocess

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.pulmonverdepdc.com/"
USER_AGENT = "Mozilla/5.0 (compatible; OASIS-PulmonArchive/1.0; +https://oasisweb4.com)"
HOSTS = {"www.pulmonverdepdc.com", "pulmonverdepdc.com"}

# Attributes that commonly hold asset URLs
ATTR_RE = re.compile(
    r"""(?:href|src|poster|data-src|data-lazy-src)\s*=\s*["']([^"']+)["']""",
    re.I,
)
SRCSET_RE = re.compile(r"srcset\s*=\s*[\"']([^\"']+)[\"']", re.I)
CSS_URL_RE = re.compile(r"""url\(\s*["']?([^)"']+)["']?\s*\)""", re.I)


def is_same_origin(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if p.netloc.lower() not in HOSTS:
        return False
    path = (p.path or "").lower()
    if path.endswith(".php"):
        return False
    return True


def normalize_fetch_url(url: str) -> str | None:
    """Return absolute URL to fetch, or None to skip."""
    if not url or url.startswith("#") or url.lower().startswith("javascript:"):
        return None
    if "{{" in url or "}}" in url:
        return None
    if url.startswith("mailto:"):
        return None
    abs_url = urljoin(BASE, url)
    if not is_same_origin(abs_url):
        return None
    # Strip fragment for fetch
    p = urlparse(abs_url)
    clean = p._replace(fragment="").geturl()
    return clean


def local_path_for_url(fetch_url: str) -> Path:
    p = urlparse(fetch_url)
    path = unquote(p.path or "/")
    if path.endswith("/") or not Path(path).suffix:
        if not path.endswith("/"):
            path = path + "/"
        path = path + "index.html"
    rel = path.lstrip("/")
    if not rel:
        rel = "index.html"
    return ROOT / rel


def fetch(url: str) -> tuple[bytes, str | None]:
    """Use curl so macOS/Python SSL trust store issues do not block downloads."""
    r = subprocess.run(
        [
            "curl",
            "-fsSL",
            "-A",
            USER_AGENT,
            "--max-time",
            "120",
            url,
        ],
        capture_output=True,
    )
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", errors="replace")[:300]
        raise RuntimeError(err or f"curl exit {r.returncode}")
    return r.stdout, None


def collect_urls_from_html(html: str) -> set[str]:
    out: set[str] = set()
    for m in ATTR_RE.finditer(html):
        u = normalize_fetch_url(m.group(1).strip())
        if u:
            out.add(u)
    for m in SRCSET_RE.finditer(html):
        parts = m.group(1).split(",")
        for part in parts:
            u0 = part.strip().split()[0] if part.strip() else ""
            u = normalize_fetch_url(u0)
            if u:
                out.add(u)
    return out


def collect_urls_from_css(css: str, base_url: str) -> set[str]:
    out: set[str] = set()
    for m in CSS_URL_RE.finditer(css):
        raw = m.group(1).strip()
        if raw.startswith("data:"):
            continue
        u = normalize_fetch_url(urljoin(base_url, raw))
        if u:
            out.add(u)
    return out


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    index_path = ROOT / "index.html"
    if not index_path.is_file():
        body, _ = fetch(BASE.rstrip("/") + "/")
        index_path.write_bytes(body)

    html = index_path.read_text(encoding="utf-8", errors="replace")
    pending: set[str] = collect_urls_from_html(html)
    done: set[str] = set()

    while pending:
        url = pending.pop()
        if url in done:
            continue
        done.add(url)

        dest = local_path_for_url(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            body, ctype = fetch(url)
        except Exception as e:
            print(f"SKIP {url} ({e})", file=sys.stderr)
            continue

        dest.write_bytes(body)
        print(f"OK {len(body)} {url} -> {dest.relative_to(ROOT)}")

        low = url.lower().split("?", 1)[0]
        if low.endswith(".css"):
            try:
                text = body.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            for u in collect_urls_from_css(text, url):
                if u not in done:
                    pending.add(u)

        time.sleep(0.05)

    # Offline HTML: drop site origin, then make paths relative for file:// viewing.
    offline = re.sub(
        r"https?://(?:www\.)?pulmonverdepdc\.com/",
        "",
        html,
        flags=re.I,
    )
    offline = re.sub(
        r'(\s(?:href|src|poster|action)\s*=\s*["\'])/(?!/)([^"\']+)',
        r"\1./\2",
        offline,
        flags=re.I,
    )
    offline = re.sub(
        r"url\(\s*/(?!/)([^)]+)\)",
        r"url(./\1)",
        offline,
        flags=re.I,
    )
    (ROOT / "index-offline.html").write_text(offline, encoding="utf-8")
    print(f"Wrote {ROOT / 'index-offline.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
