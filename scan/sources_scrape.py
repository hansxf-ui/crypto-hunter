"""Scrape-based sources for the Crypto Hunter scanner.

Stdlib only (urllib + regex). Covers sources with no clean API: Indodax,
Tokocrypto and Pintu announcement pages, plus campaign/promo pages
(Binance promotions, Bybit activities).

Each ``fetch_*`` returns NORMALIZED items (via ``scan.schema.normalize``)
and NEVER raises: on any failure it returns [] and records the error in the
module-level ``source_errors`` dict.

Endpoint notes (verified 2026-09-30):
- Indodax: https://blog.indodax.com/category/pengumuman/ (WordPress
  category archive, plain HTML).
- Tokocrypto: https://support.tokocrypto.com/hc/en-us/sections/360011267552-New-Crypto-Listing
  (Zendesk section page, plain HTML).
- Pintu: https://pintu.co.id/blog/categories/informasi-pintu (blog
  category listing, plain HTML).
- Binance promotions: https://www.binance.com/en/promotions (scraped
  anchors; heavily JS-rendered, may legitimately yield []).
- Bybit campaigns: v5 announcements API type=latest_activities
  (same public API family as Task 3's new_crypto feed).

Parsing rule: anchors + nearby dates. No deep selector chains — each
source only filters links by host/path pattern.

Live-probe note (2026-09-30): from this sandbox, www.binance.com returns
403 and api.bybit.com now 403s too (the Bybit API worked for Task 3
earlier the same day — IP-based block, may lift). fetch_campaigns
degrades gracefully to [] + a recorded error in that case; no items are
invented.
"""
import json
import re
import urllib.parse
import urllib.request

from scan.schema import normalize

__all__ = [
    "source_errors",
    "fetch_indodax",
    "fetch_tokocrypto",
    "fetch_pintu",
    "fetch_campaigns",
]

#: Fail-safe contract: never raise out of a fetch_*.
#: Any exception -> [] + an entry here keyed by source name.
source_errors: dict = {}

TIMEOUT = 30
MAX_ITEMS = 25  # cap per source, keeps noise and payload bounded

INDODAX_URL = "https://blog.indodax.com/category/pengumuman/"
TOKO_URL = (
    "https://support.tokocrypto.com/hc/en-us/sections/"
    "360011267552-New-Crypto-Listing"
)
PINTU_URL = "https://pintu.co.id/blog/categories/informasi-pintu"
BINANCE_PROMO_URL = "https://www.binance.com/en/promotions"
BYBIT_ACTIVITIES_API = (
    "https://api.bybit.com/v5/announcements/index"
    "?locale=en-US&type=latest_activities&limit=20"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}

_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bhref=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_DATE_RE = re.compile(
    r"\b("
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?"
    r"|\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r"|[A-Za-z]+\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r")\b"
)
_DATE_WINDOW = 400  # chars around an anchor to hunt for a date

#: "Title Date Title Date" -> "Title Date": some cards repeat their whole
#: content inside one anchor.
_UNDOUBLE_RE = re.compile(r"^(.{15,}?)\s+\1$")
#: Trailing English "Month D, YYYY" card-meta date (Pintu glues it on).
_TRAILING_EN_DATE_RE = re.compile(r"\s+[A-Za-z]+\s+\d{1,2},\s*\d{4}$")
# Cloudflare email-obfuscation placeholder text (e.g. "[email protected]",
# possibly with raw HTML entities like "[email&#160;protected]")
# — link text, not a real announcement title.
_CF_EMAIL_RE = re.compile(r"\[\s*email[^\]]*protected\s*\]", re.IGNORECASE)

_ID_MONTHS = {
    "januari": "January",
    "februari": "February",
    "maret": "March",
    "april": "April",
    "mei": "May",
    "juni": "June",
    "juli": "July",
    "agustus": "August",
    "september": "September",
    "oktober": "October",
    "november": "November",
    "desember": "December",
}
_ID_MONTH_RE = re.compile(
    r"\b(" + "|".join(_ID_MONTHS) + r")\b", re.IGNORECASE
)


def _note(source: str, message: str) -> None:
    source_errors[source] = message


def _safe_fetch(source: str, worker):
    """Run worker(); ANY exception -> [] + recorded. Never raises."""
    try:
        return worker()
    except Exception as exc:  # noqa: BLE001 - fail-safe contract
        _note(source, f"{type(exc).__name__}: {exc}")
        return []


def _fetch_html(url: str, source: str) -> str | None:
    """GET url as text. Returns HTML string, or None on ANY failure."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
            raw = resp.read().decode("utf-8", errors="replace")
            return raw if raw.strip() else None
    except Exception as exc:  # noqa: BLE001 - fail-safe contract
        _note(source, f"{type(exc).__name__}: {exc}")
        return None


def _fetch_json(url: str, source: str):
    """GET url and parse JSON. Returns parsed object, or None on ANY failure."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - fail-safe contract
        _note(source, f"{type(exc).__name__}: {exc}")
        return None


def _clean_text(html_fragment: str) -> str:
    """Strip tags, unescape a few entities, collapse whitespace."""
    text = _TAG_RE.sub(" ", html_fragment)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return _WS_RE.sub(" ", text).strip()


def _en_months(date_text: str) -> str:
    """Map Indonesian month names to English so parse_deadline can read them."""
    return _ID_MONTH_RE.sub(
        lambda m: _ID_MONTHS[m.group(1).lower()], date_text
    )


def _undoubled(text: str) -> str:
    """Collapse "X X" card duplication to a single X."""
    match = _UNDOUBLE_RE.match(text)
    return match.group(1) if match else text


def _strip_trailing_en_date(text: str) -> str:
    """Drop one trailing English-format meta date glued onto a title."""
    return _TRAILING_EN_DATE_RE.sub("", text).strip()


def _anchors(html: str, base_url: str):
    """Yield (abs_url, text, date_hint) for plausible content anchors.

    Skips empty/js/fragment links; hunts for a date string in a window
    around each anchor.
    """
    for match in _ANCHOR_RE.finditer(html):
        href = match.group(1).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        text = _undoubled(_clean_text(match.group(2)))
        if len(text) < 4:
            continue
        if _CF_EMAIL_RE.search(text):
            continue  # Cloudflare email placeholder, not a real title
        abs_url = urllib.parse.urljoin(base_url, href)
        start = max(0, match.start() - _DATE_WINDOW)
        end = min(len(html), match.end() + _DATE_WINDOW)
        date_match = _DATE_RE.search(html[start:end])
        date_hint = (
            _en_months(date_match.group(1)) if date_match else None
        )
        yield abs_url, text, date_hint


def _dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    return out


def _scrape_list(url: str, source: str, kategori: str, exchange: str,
                 link_ok, tidy=None) -> list[dict]:
    """Generic anchor-scraper: fetch page, keep links passing link_ok().

    ``tidy`` optionally rewrites anchor text before normalize()
    (per-source cleanup, e.g. glued card-meta dates).
    """
    html = _fetch_html(url, source)
    if html is None:
        return []  # transport error already recorded by _fetch_html
    items = []
    for abs_url, text, date_hint in _anchors(html, url):
        if not link_ok(abs_url, text):
            continue
        if tidy:
            text = tidy(text)
        item = normalize(
            {"judul": text, "url": abs_url, "deadline": date_hint},
            kategori,
            exchange,
        )
        if item:
            items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    return _dedupe(items)


def _same_host(url: str, host: str) -> bool:
    try:
        return urllib.parse.urlparse(url).netloc.lower() == host.lower()
    except ValueError:
        return False


def _not_nav(path: str) -> bool:
    lowered = path.lower()
    return not any(
        token in lowered
        for token in ("/category/", "/author/", "/tag/", "/page/", "#")
    )


def fetch_indodax() -> list[dict]:
    """Listing announcements from the Indodax blog (pengumuman category)."""

    def _work():
        def _ok(url: str, text: str) -> bool:
            if not _same_host(url, "blog.indodax.com"):
                return False
            path = urllib.parse.urlparse(url).path.lower()
            if "newsroom" in path:
                return False
            if text.lower().startswith("baca selengkapnya"):
                return False
            return len(text) >= 8 and _not_nav(path)

        return _scrape_list(INDODAX_URL, "indodax", "listing", "Indodax", _ok)

    return _safe_fetch("indodax", _work)


def fetch_tokocrypto() -> list[dict]:
    """New-listing articles from the Tokocrypto support section."""

    def _work():
        def _ok(url: str, text: str) -> bool:
            path = urllib.parse.urlparse(url).path.lower()
            return "/articles/" in path and len(text) >= 8

        return _scrape_list(TOKO_URL, "tokocrypto", "listing", "Tokocrypto", _ok)

    return _safe_fetch("tokocrypto", _work)


def fetch_pintu() -> list[dict]:
    """Announcement posts from the Pintu blog (informasi-pintu category)."""

    def _work():
        def _ok(url: str, text: str) -> bool:
            if not _same_host(url, "pintu.co.id"):
                return False
            path = urllib.parse.urlparse(url).path.lower()
            return (
                path.startswith("/blog/")
                and "categories" not in path
                and len(text) >= 8
            )

        def _tidy(text: str) -> str:
            # Pintu cards glue "Title MetaDate" twice inside one anchor.
            return _strip_trailing_en_date(text)

        return _scrape_list(PINTU_URL, "pintu", "listing", "Pintu", _ok,
                            tidy=_tidy)

    return _safe_fetch("pintu", _work)


def fetch_campaigns() -> list[dict]:
    """Campaigns: Binance promotions page + Bybit activities feed."""

    def _work():
        items: list[dict] = []

        def _ok(url: str, text: str) -> bool:
            return _same_host(url, "www.binance.com") and len(text) >= 8

        items.extend(
            _scrape_list(
                BINANCE_PROMO_URL, "campaigns", "campaign", "Binance", _ok
            )
        )

        payload = _fetch_json(BYBIT_ACTIVITIES_API, "campaigns")
        if isinstance(payload, dict) and payload.get("retCode") == 0:
            try:
                entries = payload["result"]["list"]
            except (KeyError, TypeError):
                entries = None
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    ts = entry.get("dateTimestamp")
                    deadline = None
                    if ts:
                        try:
                            deadline = str(int(ts) // 1000)
                        except (TypeError, ValueError):
                            deadline = None
                    item = normalize(
                        {
                            "judul": entry.get("title"),
                            "url": entry.get("url"),
                            "deadline": deadline,
                        },
                        "campaign",
                        "Bybit",
                    )
                    if item:
                        items.append(item)
        if items:
            # One sub-source (e.g. Binance 403) may have recorded a "campaigns"
            # error while the other still delivered items: don't report the
            # category as failed when we actually have data.
            source_errors.pop("campaigns", None)
        return _dedupe(items)

    return _safe_fetch("campaigns", _work)
