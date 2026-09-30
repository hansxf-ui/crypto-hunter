"""API-based sources for the Crypto Hunter scanner.

Stdlib only (urllib). Each ``fetch_*`` returns NORMALIZED items (via
``scan.schema.normalize``) and NEVER raises: on any failure it returns []
and records the error in the module-level ``source_errors`` dict, so the
hourly cron never dies because one source is down.

Endpoint notes (verified 2026-09-30):
- Binance: brief named POST /bapi/composite/v1/public/content/fetch, but
  that returns 404. The working endpoint is GET
  /bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48
  (48 = new-listing announcements), response
  {"code":"000000","data":{"articles":[{"id","code","title",...}]}}.
  Article URL: https://www.binance.com/en/support/announcement/{code}
- Bybit: GET /v5/announcements/index?locale=en-US&type=new_crypto&limit=N,
  public, no auth. Response {"retCode":0,"result":{"list":[{title,url,...}]}}.
- OKX: GET /api/v5/support/announcements?annType=announcements-new-listings,
  public, no auth. Response {"code":"0","data":[{"details":[{title,url,...}]}]}.
- CryptoRank: GET /v2/drophunting/activities, requires sandbox API key via
  env CRYPTORANK_API_KEY. Without a key the fetch returns [] + "need_key".
"""
import json
import os
import urllib.parse
import urllib.request

from scan.schema import normalize

__all__ = [
    "source_errors",
    "fetch_binance",
    "fetch_bybit",
    "fetch_okx",
    "fetch_cryptorank_drops",
]

#: Fail-safe contract: never raise out of a fetch_*.
#: Any exception -> [] + an entry here keyed by source name.
source_errors: dict = {}

TIMEOUT = 30

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def _note(source: str, message: str) -> None:
    source_errors[source] = message


def _fetch_json(url: str, source: str, headers: dict | None = None):
    """GET url and parse JSON. Returns parsed object, or None on ANY failure.

    Never raises; records the failure in source_errors[source].
    """
    try:
        merged = dict(_HEADERS)
        merged.update(headers or {})
        req = urllib.request.Request(url, headers=merged)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - fail-safe contract
        _note(source, f"{type(exc).__name__}: {exc}")
        return None


def _safe_fetch(source: str, worker):
    """Run worker(); ANY exception -> [] + recorded. Never raises."""
    try:
        return worker()
    except Exception as exc:  # noqa: BLE001 - fail-safe contract
        _note(source, f"{type(exc).__name__}: {exc}")
        return []


def fetch_binance() -> list[dict]:
    """New-listing announcements from Binance (catalogId=48)."""

    def _work():
        query = urllib.parse.urlencode(
            {"catalogId": 48, "pageNo": 1, "pageSize": 20}
        )
        url = (
            "https://www.binance.com/bapi/composite/v1/public/cms/article/"
            f"catalog/list/query?{query}"
        )
        payload = _fetch_json(url, "binance")
        if payload is None:
            return []  # transport error already recorded by _fetch_json
        if not isinstance(payload, dict) or payload.get("code") != "000000":
            raise ValueError("unexpected response shape")
        articles = payload["data"]["articles"]
        if not isinstance(articles, list):
            raise ValueError("unexpected response shape")
        items = []
        for art in articles:
            if not isinstance(art, dict):
                continue
            code = str(art.get("code") or "").strip()
            item = normalize(
                {
                    "judul": art.get("title"),
                    "url": (
                        f"https://www.binance.com/en/support/announcement/{code}"
                        if code
                        else None
                    ),
                },
                "listing",
                "Binance",
            )
            if item:
                items.append(item)
        return items

    return _safe_fetch("binance", _work)


def fetch_bybit() -> list[dict]:
    """New-listing announcements from Bybit v5 (type=new_crypto)."""

    def _work():
        query = urllib.parse.urlencode(
            {"locale": "en-US", "type": "new_crypto", "limit": 20}
        )
        url = f"https://api.bybit.com/v5/announcements/index?{query}"
        payload = _fetch_json(url, "bybit")
        if payload is None:
            return []  # transport error already recorded by _fetch_json
        if not isinstance(payload, dict) or payload.get("retCode") != 0:
            raise ValueError("unexpected response shape")
        entries = payload["result"]["list"]
        if not isinstance(entries, list):
            raise ValueError("unexpected response shape")
        items = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item = normalize(
                {"judul": entry.get("title"), "url": entry.get("url")},
                "listing",
                "Bybit",
            )
            if item:
                items.append(item)
        return items

    return _safe_fetch("bybit", _work)


def fetch_okx() -> list[dict]:
    """New-listing announcements from OKX (public, no auth)."""

    def _work():
        query = urllib.parse.urlencode(
            {"annType": "announcements-new-listings"}
        )
        url = f"https://www.okx.com/api/v5/support/announcements?{query}"
        payload = _fetch_json(url, "okx")
        if payload is None:
            return []  # transport error already recorded by _fetch_json
        if not isinstance(payload, dict) or payload.get("code") != "0":
            raise ValueError("unexpected response shape")
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise ValueError("unexpected response shape")
        details = data[0].get("details")
        if not isinstance(details, list):
            raise ValueError("unexpected response shape")
        items = []
        for entry in details:
            if not isinstance(entry, dict):
                continue
            item = normalize(
                {"judul": entry.get("title"), "url": entry.get("url")},
                "listing",
                "OKX",
            )
            if item:
                items.append(item)
        return items

    return _safe_fetch("okx", _work)


def fetch_cryptorank_drops() -> list[dict]:
    """Drop-hunting / airdrop activities from CryptoRank (needs API key)."""

    def _work():
        key = os.environ.get("CRYPTORANK_API_KEY")
        if not key:
            _note("cryptorank", "need_key")
            return []
        query = urllib.parse.urlencode({"limit": 20})
        url = f"https://api.cryptorank.io/v2/drophunting/activities?{query}"
        payload = _fetch_json(url, "cryptorank", headers={"X-Api-Key": key})
        if payload is None:
            return []  # transport error already recorded by _fetch_json
        if not isinstance(payload, dict):
            raise ValueError("unexpected response shape")
        entries = payload.get("data")
        if not isinstance(entries, list):
            raise ValueError("unexpected response shape")
        items = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            slug = str(entry.get("slug") or "").strip()
            fallback_url = (
                f"https://cryptorank.io/drophunting/{slug}" if slug else None
            )
            item = normalize(
                {
                    "judul": entry.get("name") or entry.get("title"),
                    "url": entry.get("url") or fallback_url,
                    "reward": entry.get("rewards"),
                    "cara_ikut": entry.get("description"),
                },
                "airdrop",
                "CryptoRank",
            )
            if item:
                items.append(item)
        return items

    return _safe_fetch("cryptorank", _work)
