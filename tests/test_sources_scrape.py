"""Tests for scan.sources_scrape — scrape sources (Task 4).

All HTTP is mocked (monkeypatched _fetch_html/_fetch_json); no network in
this suite. Fixtures are small, hand-written HTML snippets that mimic the
real page structures (WordPress category, Zendesk section, Pintu blog).
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scan import sources_scrape
from scan.sources_scrape import (
    fetch_indodax,
    fetch_tokocrypto,
    fetch_pintu,
    fetch_campaigns,
    source_errors,
)


@pytest.fixture(autouse=True)
def clean_errors():
    source_errors.clear()
    yield
    source_errors.clear()


def _mock_html(html):
    def _fake(url, source):
        return html

    return _fake


def _mock_json(payload):
    def _fake(url, source):
        return payload

    return _fake


# --- Indodax (WordPress category page) -----------------------------------

INDODAX_HTML = """
<html><body>
<nav><a href="/category/pengumuman/">Pengumuman</a>
<a href="#top">Back to top</a></nav>
<article>
  <h2><a href="https://blog.indodax.com/listing-marscoin/">MarsCoin (MARSCOIN) Listing di INDODAX</a></h2>
  <span class="date">September 29, 2026</span>
</article>
<article>
  <h2><a href="https://blog.indodax.com/listing-pm/">PumpMeme (PM) Listing di INDODAX</a></h2>
  <span class="date">September 22, 2026</span>
</article>
<a href="https://blog.indodax.com/category/pengumuman/page/2/">Older posts</a>
</body></html>
"""


def test_fetch_indodax_parses_announcement_list(monkeypatch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(INDODAX_HTML))
    items = fetch_indodax()
    assert items and items[0]["exchange"] == "Indodax"
    assert items[0]["kategori"] == "listing"
    assert items[0]["judul"] == "MarsCoin (MARSCOIN) Listing di INDODAX"
    assert items[0]["url"] == "https://blog.indodax.com/listing-marscoin/"
    assert len(items) == 2
    # nav / pagination links are skipped
    assert all("/category/" not in i["url"] for i in items)


# --- Tokocrypto (Zendesk section page) -----------------------------------

TOKO_HTML = """
<html><body>
<ul class="article-list">
  <li><a href="/hc/en-us/articles/44123456-New-Listing-Alert-Aerodrome-AERO">
    New Listing Alert: Aerodrome ($AERO) is Now Available on Tokocrypto!</a>
    <span>Sep 28, 2026</span></li>
  <li><a href="/hc/en-us/articles/44123457-New-Asset-Listing-Katana-KAT">
    New Asset Listing: Katana Network ($KAT)</a></li>
</ul>
<a href="/hc/en-us">Help Center</a>
</body></html>
"""


def test_fetch_tokocrypto_parses_listing_section(monkeypatch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(TOKO_HTML))
    items = fetch_tokocrypto()
    assert items and items[0]["exchange"] == "Tokocrypto"
    assert items[0]["kategori"] == "listing"
    assert "Aerodrome" in items[0]["judul"]
    assert items[0]["url"].startswith("https://support.tokocrypto.com/hc/en-us/articles/")
    assert len(items) == 2


# --- Pintu (blog category page) ------------------------------------------

PINTU_HTML = """
<html><body>
<div class="posts">
  <a href="/blog/pintu-listing-2-token-baru-24sep26">
    <h3>Pintu Listing 2 Token Baru, 24 September 2026</h3></a>
  <div class="meta">September 24, 2026</div>
  <a href="/blog/pintu-listing-10-aset-tokenized-baru-17september2026">
    <h3>Pintu Listing 10 Aset Tokenized Baru, 17 September 2026</h3></a>
  <div class="meta">September 17, 2026</div>
  <a href="/blog/categories/informasi-pintu">Informasi Pintu</a>
</div>
</body></html>
"""


def test_fetch_pintu_parses_blog_category(monkeypatch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(PINTU_HTML))
    items = fetch_pintu()
    assert items and items[0]["exchange"] == "Pintu"
    assert items[0]["kategori"] == "listing"
    assert "24 September 2026" in items[0]["judul"]
    assert len(items) == 2


# --- Campaigns (Binance promo page + Bybit activities API) ----------------

BINANCE_PROMO_HTML = """
<html><body>
<div class="promo-list">
  <a href="https://www.binance.com/en/support/announcement/trade-xyz-win">
    Trade XYZ, Share 50,000 USDT in Rewards!</a>
  <a href="https://www.binance.com/en/support/announcement/learn-earn-abc">
    Learn &amp; Earn: Complete Courses, Earn ABC Rewards</a>
</div>
</body></html>
"""

BYBIT_ACTIVITIES_OK = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "total": 1,
        "list": [
            {
                "title": "Wall Street Blue-Chip Options Challenge: Share 70,000 USDT!",
                "url": "https://announcements.bybit.com/en/article/wall-street--art5e3a/",
                "dateTimestamp": 1759000000000,
            }
        ],
    },
}


def test_fetch_campaigns_combines_binance_and_bybit(monkeypatch):
    monkeypatch.setattr(
        sources_scrape, "_fetch_html", _mock_html(BINANCE_PROMO_HTML)
    )
    monkeypatch.setattr(
        sources_scrape, "_fetch_json", _mock_json(BYBIT_ACTIVITIES_OK)
    )
    items = fetch_campaigns()
    assert items
    by_exchange = {i["exchange"] for i in items}
    assert by_exchange == {"Binance", "Bybit"}
    assert all(i["kategori"] == "campaign" for i in items)
    assert len(items) == 3


def test_malformed_bybit_timestamp_does_not_kill_batch(monkeypatch):
    payload = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "total": 2,
            "list": [
                {
                    "title": "Good Entry",
                    "url": "https://announcements.bybit.com/en/article/good--art1/",
                    "dateTimestamp": 1759000000000,
                },
                {
                    "title": "Bad Timestamp Entry",
                    "url": "https://announcements.bybit.com/en/article/bad--art2/",
                    "dateTimestamp": "not-a-number",
                },
            ],
        },
    }
    monkeypatch.setattr(
        sources_scrape, "_fetch_html", _mock_html(BINANCE_PROMO_HTML)
    )
    monkeypatch.setattr(sources_scrape, "_fetch_json", _mock_json(payload))
    items = fetch_campaigns()
    bybit = [i for i in items if i["exchange"] == "Bybit"]
    assert len(bybit) == 2
    bad = next(i for i in bybit if i["judul"] == "Bad Timestamp Entry")
    assert bad["deadline"] is None
    good = next(i for i in bybit if i["judul"] == "Good Entry")
    assert good["deadline"] is not None


def test_campaign_items_clear_stale_error(monkeypatch):
    def _binance_403(url, source):
        # mimic the real _fetch_html: record the transport error, return None
        sources_scrape._note(source, "HTTPError: HTTP Error 403")
        return None

    monkeypatch.setattr(sources_scrape, "_fetch_html", _binance_403)
    monkeypatch.setattr(
        sources_scrape, "_fetch_json", _mock_json(BYBIT_ACTIVITIES_OK)
    )
    items = fetch_campaigns()
    assert items  # Bybit delivered data despite the Binance 403
    assert "campaigns" not in source_errors


# --- Fail-safe contract ---------------------------------------------------

ALL_FETCHES = [
    ("indodax", fetch_indodax),
    ("tokocrypto", fetch_tokocrypto),
    ("pintu", fetch_pintu),
    ("campaigns", fetch_campaigns),
]


@pytest.mark.parametrize("name,fetch", ALL_FETCHES)
def test_fetch_never_raises_on_transport_error(monkeypatch, name, fetch):
    def _boom(url, source):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(sources_scrape, "_fetch_html", _boom)
    monkeypatch.setattr(sources_scrape, "_fetch_json", _boom)
    assert fetch() == []
    assert name in source_errors


@pytest.mark.parametrize("name,fetch", ALL_FETCHES)
def test_fetch_empty_html_returns_empty(monkeypatch, name, fetch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(""))
    monkeypatch.setattr(sources_scrape, "_fetch_json", _mock_json(None))
    assert fetch() == []


def test_skips_nav_noise_and_dedupes(monkeypatch):
    html = """
    <html><body>
    <a href="#">empty</a>
    <a href="javascript:void(0)">js</a>
    <a href="https://blog.indodax.com/listing-marscoin/">MarsCoin (MARSCOIN) Listing di INDODAX</a>
    <a href="https://blog.indodax.com/listing-marscoin/">MarsCoin (MARSCOIN) Listing di INDODAX</a>
    <a href="https://blog.indodax.com/listing-marscoin/">MarsCoin (MARSCOIN) Listing di INDODAX</a>
    </body></html>
    """
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(html))
    items = fetch_indodax()
    assert len(items) == 1


def test_indodax_skips_read_more_and_newsroom(monkeypatch):
    html = """
    <html><body>
    <a href="https://blog.indodax.com/newsroom-latest-stories">Informasi Terbaru</a>
    <a href="https://blog.indodax.com/listing-marscoin/">MarsCoin (MARSCOIN) Listing di INDODAX</a>
    <a href="https://blog.indodax.com/listing-marscoin/">Baca Selengkapnya »</a>
    </body></html>
    """
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(html))
    items = fetch_indodax()
    assert len(items) == 1
    assert items[0]["judul"] == "MarsCoin (MARSCOIN) Listing di INDODAX"


def test_pintu_tidies_doubled_card_text(monkeypatch):
    html = """
    <html><body>
    <a href="/blog/pintu-listing-2-token-baru-24sep26">Pintu Listing 2 Token Baru, 24 September 2026 September 24, 2026 Pintu Listing 2 Token Baru, 24 September 2026 September 24, 2026</a>
    </body></html>
    """
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(html))
    items = fetch_pintu()
    assert len(items) == 1
    assert items[0]["judul"] == "Pintu Listing 2 Token Baru, 24 September 2026"
