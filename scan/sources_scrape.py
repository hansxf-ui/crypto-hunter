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
- CryptoRank drophunting: https://cryptorank.io/drophunting (public
  website table; the *API* paywalls this on the free plan, the website
  does not). Soft-404s return HTTP 200, so the <title> is checked.
- Airdrops.io: https://airdrops.io/ (WordPress article cards).
- DeFiLlama unlocks: https://defillama.com/unlocks (server-rendered
  table; ~9MB page, still fast enough). Next-unlock dates are countdowns
  ("0 D 1 H 50 M"), converted to absolute deadlines at fetch time.
- CryptoRank token unlocks: https://cryptorank.io/token-unlock (public
  website table with absolute dates).

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
from datetime import datetime, timedelta

from scan.schema import normalize

__all__ = [
    "source_errors",
    "fetch_indodax",
    "fetch_tokocrypto",
    "fetch_pintu",
    "fetch_campaigns",
    "fetch_cryptorank_drophunting",
    "fetch_airdrops_io",
    "fetch_defillama_unlocks",
    "fetch_cryptorank_unlocks",
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
CRYPTORANK_DROP_URL = "https://cryptorank.io/drophunting"
AIRDROPS_IO_URL = "https://airdrops.io/"
DEFILLAMA_UNLOCKS_URL = "https://defillama.com/unlocks"
CRYPTORANK_UNLOCK_URL = "https://cryptorank.io/token-unlock"
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


# ---------------------------------------------------------------------------
# Airdrop & unlock sources (free public website data, 2026-09-30)
# ---------------------------------------------------------------------------

#: DeFiLlama "Next Event" cells come in a few shapes:
#:   "$51,983 Cliff Unlock 0.084% of float 0 D 1 H 50 M 2 S"
#:   "$19.4m / week Weekly Unlock Rate 0.38% of float 0 D 10 H 55 M 44 S"
#:   "179.57 Cliff Unlock 0 D 10 H 55 M 44 S"          (no USD value)
#: The countdown is always trailing, so it is parsed first; kind/value are
#: extracted loosely from whatever precedes it.
_LLAMA_COUNTDOWN_RE = re.compile(r"(\d+)\s*D\s*(\d+)\s*H\s*(\d+)\s*M(?:\s*(\d+)\s*S)?")
_LLAMA_KIND_RE = re.compile(r"(Cliff|Weekly|Linear)\s+Unlock", re.IGNORECASE)
_LLAMA_VALUE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?\s*[kmb]?)", re.IGNORECASE)
_LLAMA_SHARE_RE = re.compile(r"([\d.]+\s*%\s*of\s*\w+)")

#: CryptoRank token-unlock cell: "1.00% of M. Cap ( $ 2.06K ) INFRA 50.15K Sep 30, 2026"
_CR_UNLOCK_RE = re.compile(
    r"([\d.]+\s*%\s*of\s*M\.\s*Cap)\s*"
    r"\(\s*\$\s*([\d.,]+\s*[KMB]?)\s*\)\s*"
    r"([A-Z0-9]+)\s+([\d.,]+\s*[KMB]?)\s*"
    r"([A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4})"
)

#: airdrops.io card: <a href=https://airdrops.io/{slug}/><h3>Name</h3></a>
#: (note: href is unquoted on the live site)
_AIO_NAME_RE = re.compile(
    r'<a[^>]+href=(?:"([^"]+)"|([^\s>]+))[^>]*>\s*<h3>(.*?)</h3>', re.S
)
_AIO_STATUS_RE = re.compile(
    r'class="status-indicator[^"]*"[^>]*>.*?</span>\s*([A-Za-z]+)', re.S
)
_AIO_ACTIONS_RE = re.compile(r"Actions:\s*<span>(.*?)</span>", re.S)


def fetch_cryptorank_drophunting():
    """Airdrop board from CryptoRank's public website table.

    Columns: Name | Task Type | Updated Status | Reward Type | Raise.
    CSS classes are hashed, so rows are located by table structure only;
    the expected header text is checked because bad paths return HTTP 200
    with a "Page not found" body. Shows the top 20 ("Show More" is
    client-side and needs the paid API).
    """
    def _work():
        src = "cryptorank_drop"
        html = _fetch_html(CRYPTORANK_DROP_URL, src)
        if not html:
            return []
        if "Reward Type" not in html:
            _note(src, "unexpected page (not the drophunting table)")
            return []
        body = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
        if not body:
            _note(src, "no table body found")
            return []
        items = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(tds) < 7:
                continue
            link_m = re.search(r'href="(/drophunting/[^"]+)"', tds[1])
            name = _clean_text(tds[1])
            if not link_m or not name:
                continue
            task = _clean_text(tds[2])
            status = _clean_text(tds[3])
            reward_type = _clean_text(tds[4])
            raised = _clean_text(tds[5])
            detail = " · ".join(p for p in (task, status) if p)
            if raised:
                detail = f"{detail} · Raise {raised}" if detail else f"Raise {raised}"
            item = normalize(
                {
                    "judul": name,
                    "url": "https://cryptorank.io" + link_m.group(1),
                    "reward": reward_type or None,
                    "cara_ikut": detail or None,
                },
                "airdrops",
                "CryptoRank",
            )
            if item:
                items.append(item)
        return _dedupe(items[:MAX_ITEMS])

    return _safe_fetch("cryptorank_drop", _work)


def fetch_airdrops_io():
    """Airdrop cards from airdrops.io front page (WordPress, server-rendered).

    Each <article> card carries: status (Ongoing/Ended), an optional
    "Confirmed" badge, the project name + canonical detail link, and the
    "Actions" line (how to participate). Only articles with the
    ``air-wrapper`` card markup are kept; the /visit/ redirect buttons are
    ignored in favour of the canonical detail link.
    """
    def _work():
        src = "airdrops_io"
        html = _fetch_html(AIRDROPS_IO_URL, src)
        if not html:
            return []
        if "air-wrapper" not in html:
            _note(src, "unexpected page (no airdrop cards found)")
            return []
        items = []
        for art in re.findall(r"<article[^>]*>(.*?)</article>", html, re.S):
            if "air-wrapper" not in art:
                continue
            name_m = _AIO_NAME_RE.search(art)
            if not name_m:
                continue
            url = name_m.group(1) or name_m.group(2)
            name = _clean_text(name_m.group(3))
            if not url or not name or not url.startswith("https://airdrops.io/"):
                continue
            status_m = _AIO_STATUS_RE.search(art)
            status = status_m.group(1) if status_m else ""
            if "badge-confirmed" in art and status:
                status = f"{status}, Confirmed"
            actions_m = _AIO_ACTIONS_RE.search(art)
            actions = _clean_text(actions_m.group(1)) if actions_m else ""
            detail = f"{status} — {actions}" if status and actions else (status or actions)
            item = normalize(
                {
                    "judul": name,
                    "url": url,
                    "cara_ikut": detail or None,
                },
                "airdrops",
                "Airdrops.io",
            )
            if item:
                items.append(item)
        return _dedupe(items[:MAX_ITEMS])

    return _safe_fetch("airdrops_io", _work)


def fetch_defillama_unlocks():
    """Upcoming token unlocks from DeFiLlama's server-rendered table.

    The "Next Event" column only gives a countdown ("0 D 1 H 50 M"),
    so the deadline is computed as fetch time + countdown. Rows without a
    parseable upcoming event are skipped (nothing to count down to).
    """
    def _work():
        src = "defillama"
        html = _fetch_html(DEFILLAMA_UNLOCKS_URL, src)
        if not html:
            return []
        tbl = re.search(r"<table.*?</table>", html, re.S)
        if not tbl or "Next Event" not in tbl.group(0):
            _note(src, "unexpected page (no unlocks table found)")
            return []
        now = datetime.now().astimezone()
        items = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl.group(0), re.S):
            if "<td" not in row:
                continue
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(tds) < 8:
                continue
            link_m = re.search(r'href="(/unlocks/[^"]+)"', tds[0])
            name = re.sub(r"(?i)^add to watchlist\s*", "", _clean_text(tds[0])).strip()
            event_text = _clean_text(tds[7])
            cd = _LLAMA_COUNTDOWN_RE.search(event_text)
            if not link_m or not name or not cd:
                continue
            d, h, mi, s = cd.groups()
            deadline = (
                now + timedelta(days=int(d), hours=int(h),
                                minutes=int(mi), seconds=int(s or 0))
            ).isoformat()
            kind_m = _LLAMA_KIND_RE.search(event_text)
            value_m = _LLAMA_VALUE_RE.search(event_text)
            share_m = _LLAMA_SHARE_RE.search(event_text)
            detail = kind_m.group(0) if kind_m else "Unlock"
            if share_m:
                detail += f" · {share_m.group(1).strip()}"
            item = normalize(
                {
                    "judul": name,
                    "url": "https://defillama.com" + link_m.group(1),
                    "deadline": deadline,
                    "reward": f"${value_m.group(1).strip()}" if value_m else None,
                    "cara_ikut": detail,
                },
                "unlocks",
                "DeFiLlama",
            )
            if item:
                items.append(item)
        return _dedupe(items[:MAX_ITEMS])

    return _safe_fetch("defillama", _work)


def fetch_cryptorank_unlocks():
    """Upcoming token unlocks from CryptoRank's public website table.

    The "Next Unlock" cell packs amount, USD value and an absolute date
    ("1.00% of M. Cap ( $ 2.06K ) INFRA 50.15K Sep 30, 2026"), parsed by
    regex. Same soft-404 caveat as the drophunting page: bad paths return
    HTTP 200, so the expected header text is checked. Cells marked
    ``styles_blurred`` (aria-hidden teaser decoys for non-members) and rows
    whose date is already past are skipped — this feed is upcoming unlocks.
    """
    def _work():
        src = "cryptorank_unlock"
        html = _fetch_html(CRYPTORANK_UNLOCK_URL, src)
        if not html:
            return []
        if "Next Unlock" not in html:
            _note(src, "unexpected page (not the unlock table)")
            return []
        body = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
        if not body:
            _note(src, "no table body found")
            return []
        today = datetime.now().astimezone().date()
        items = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(tds) < 8:
                continue
            if "styles_blurred" in tds[7]:
                continue  # aria-hidden teaser decoy, not real data
            link_m = re.search(r'href="(/price/[^"]+/vesting)"', tds[1])
            name = _clean_text(tds[1])
            m = _CR_UNLOCK_RE.search(_clean_text(tds[7]))
            if not link_m or not name or not m:
                continue
            pct, usd, symbol, amount, date = m.groups()
            try:
                day = datetime.strptime(
                    date.strip().replace(",", ""), "%b %d %Y"
                ).date()
            except ValueError:
                continue
            if day < today:
                continue  # not an upcoming unlock
            item = normalize(
                {
                    "judul": name,
                    "url": "https://cryptorank.io" + link_m.group(1),
                    "deadline": day.isoformat(),
                    "reward": f"${usd.strip()}",
                    "cara_ikut": f"{symbol} {amount.strip()} · {pct.strip()}",
                },
                "unlocks",
                "CryptoRank",
            )
            if item:
                items.append(item)
        return _dedupe(items[:MAX_ITEMS])

    return _safe_fetch("cryptorank_unlock", _work)
