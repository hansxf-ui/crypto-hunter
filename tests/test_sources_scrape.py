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
    fetch_pintu_promos,
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


def test_indodax_skips_cloudflare_email_placeholder(monkeypatch):
    html = """
    <html><body>
    <a href="https://blog.indodax.com/listing-marscoin/">MarsCoin (MARSCOIN) Listing di INDODAX</a>
    <a href="/cdn-cgi/l/email-protection#abc123">[email&#160;protected]</a>
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


# --- Airdrop & unlock website sources (2026-09-30) ---------------------------

from scan.sources_scrape import (
    fetch_cryptorank_drophunting,
    fetch_airdrops_io,
    fetch_defillama_unlocks,
    fetch_cryptorank_unlocks,
)


CR_DROP_HTML = """
<html><head><title>Crypto Airdrops: Up-to-Date Airdrops List 2026 | CryptoRank.io</title></head>
<body><table><thead><tr><th>Name</th><th>Task Type</th><th>Updated Status</th>
<th>Reward Type</th><th>Raise/Funds</th><th>Moni Score</th></tr></thead>
<tbody>
<tr><td><button>*</button></td>
<td><a href="/drophunting/ekiden-activity1207"><p>Ekiden</p></a></td>
<td><p>Cost : $ 60 Time : 25 min Mainnet, Trading</p></td>
<td><p>Confirmed Sep 30, 2026</p></td>
<td><p>Points</p></td>
<td><p>$ 2.00M + 16</p></td>
<td><p>481</p></td></tr>
<tr><td><button>*</button></td>
<td><a href="/drophunting/ecash-drivechains-activity1307"><p>eCash.com ECX</p></a></td>
<td><p>Cost : $ 0 Time : 10 min Wallet</p></td>
<td><p>Confirmed Sep 30, 2026</p></td>
<td><p>Airdrop</p></td>
<td><p>$ 8.00M</p></td>
<td><p>134</p></td></tr>
</tbody></table></body></html>
"""

CR_404_HTML = """
<html><head><title>Page not found | CryptoRank.io</title></head>
<body><h1>Page not found</h1></body></html>
"""

AIO_HTML = """
<html><head><title>Crypto Airdrops 2026</title></head><body>
<article><div class="inside-article"><div class='air-wrapper temperature-70'>
<div class='droptemp'><span>70°</span></div>
<div class='air-content-front'>
<div class="card-status-row"><div class="status-indicator ongoing"><span class="status-dot"></span>Ongoing</div>
<div class="badge-confirmed">Confirmed</div></div>
<a href=https://airdrops.io/tastyco/><h3>TastyCo</h3></a>
<ul class='front-drop-list'><li class='est-value'>Actions: <span>Sign in, Complete Quests and Refer Users</span></li></ul>
</div></div></div></article>
<article><div class="inside-article"><div class='air-wrapper temperature-60'>
<div class='air-content-front'>
<div class="card-status-row"><div class="status-indicator upcoming"><span class="status-dot"></span>Upcoming</div></div>
<a href="https://airdrops.io/raycash/"><h3>Raycash</h3></a>
<ul class='front-drop-list'><li class='est-value'>Actions: <span>Join Waitlist, Follow on X</span></li></ul>
</div></div></div></article>
</body></html>
"""

LLAMA_HTML = """
<html><body><table><thead><tr><th>Name</th><th>Price</th><th>MCap</th>
<th>Unlocked Supply</th><th>Prev. Unlock Analysis</th><th>7d Price Change After Unlock</th>
<th>Next 24h Unlocks</th><th>Next Event</th></tr></thead>
<tr><td><a href="/unlocks/celo">Add to watchlist Celo</a></td><td>$0.10</td>
<td>$61.72m</td><td>60.54%</td><td></td><td>+10.83%</td><td>$157,927</td>
<td>$51,983 Cliff Unlock 0.084% of float 0 D 1 H 50 M 2 S</td></tr>
<tr><td><a href="/unlocks/canton">Add to watchlist Canton</a></td><td>$0.20</td>
<td>$10m</td><td>20%</td><td></td><td></td><td></td>
<td>$19.4m / week Weekly Unlock Rate 0.38% of float 0 D 10 H 55 M 44 S</td></tr>
<tr><td><a href="/unlocks/kwenta">Add to watchlist Kwenta</a></td><td>$1.00</td>
<td>$1m</td><td>50%</td><td></td><td></td><td></td>
<td>179.57 Cliff Unlock 0 D 10 H 55 M 44 S</td></tr>
<tr><td><a href="/unlocks/empty">Add to watchlist NoEvent</a></td><td>$1.00</td>
<td>$1m</td><td>100%</td><td></td><td></td><td></td><td></td></tr>
</table></body></html>
"""

CR_UNLOCK_HTML = """
<html><head><title>Cryptocurrency Vesting: Tokens Unlock | CryptoRank.io</title></head>
<body><table><thead><tr><th>Name</th><th>Price</th><th>Chg (24H)</th><th>Market Cap</th>
<th>Circ. Supply</th><th>Unlocked</th><th>Locked</th><th>Next Unlock</th><th>Date</th></tr></thead>
<tbody>
<tr><td></td>
<td><a href="/price/bware-labs/vesting"><p>Bware Labs INFRA</p></a></td>
<td>$ 0.04112</td><td>-25.2%</td><td>$ 205.91K</td><td>5.00M</td>
<td>82.4% 17.7% INFRA 82.42M INFRA 17.65M</td>
<td>1.00% of M. Cap ( $ 2.06K ) INFRA 50.15K Sep 30, 2026 Today</td></tr>
<tr><td></td>
<td><a href="/price/zora/vesting"><p>Zora ZORA</p></a></td>
<td>$ 0.01</td><td>+1%</td><td>$ 1M</td><td>1M</td>
<td>10% 90% ZORA 10M ZORA 90M</td>
<td><div class="styles_blurred__7MgwC" aria-hidden="true">13.0 % of M. Cap ( $ 1.25M ) GORA 15.00M Jun 24 2025</div></td></tr>
</tbody></table></body></html>
"""


def test_cryptorank_drophunting_parses_table(monkeypatch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(CR_DROP_HTML))
    items = fetch_cryptorank_drophunting()
    assert len(items) == 2
    assert items[0]["judul"] == "Ekiden"
    assert items[0]["url"] == "https://cryptorank.io/drophunting/ekiden-activity1207"
    assert items[0]["kategori"] == "airdrops"
    assert items[0]["exchange"] == "CryptoRank"
    assert items[0]["reward"] == "Points"
    assert "Confirmed Sep 30, 2026" in items[0]["cara_ikut"]
    assert "Raise $ 2.00M + 16" in items[0]["cara_ikut"]
    assert items[1]["judul"] == "eCash.com ECX"
    assert items[1]["deadline"] is None  # status date is an update, not a deadline


def test_cryptorank_drophunting_rejects_soft_404(monkeypatch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(CR_404_HTML))
    items = fetch_cryptorank_drophunting()
    assert items == []
    assert "cryptorank_drop" in source_errors


def test_airdrops_io_parses_cards(monkeypatch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(AIO_HTML))
    items = fetch_airdrops_io()
    assert len(items) == 2
    assert items[0]["judul"] == "TastyCo"
    assert items[0]["url"] == "https://airdrops.io/tastyco/"
    assert items[0]["exchange"] == "Airdrops.io"
    assert "Ongoing, Confirmed" in items[0]["cara_ikut"]
    assert "Sign in, Complete Quests and Refer Users" in items[0]["cara_ikut"]
    assert items[1]["judul"] == "Raycash"
    assert "Upcoming" in items[1]["cara_ikut"]


def test_defillama_unlocks_deadline_from_countdown(monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(LLAMA_HTML))
    before = datetime.now().astimezone()
    items = fetch_defillama_unlocks()
    after = datetime.now().astimezone()
    # Row without a parseable upcoming event is skipped.
    assert len(items) == 3
    it = items[0]
    assert it["judul"] == "Celo"
    assert it["url"] == "https://defillama.com/unlocks/celo"
    assert it["reward"] == "$51,983"
    assert "Cliff Unlock" in it["cara_ikut"]
    dl = datetime.fromisoformat(it["deadline"])
    expect = timedelta(hours=1, minutes=50, seconds=2)
    assert before + expect <= dl <= after + expect + timedelta(seconds=5)


def test_defillama_unlocks_weekly_and_valueless_formats(monkeypatch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(LLAMA_HTML))
    items = fetch_defillama_unlocks()
    by_name = {it["judul"]: it for it in items}
    weekly = by_name["Canton"]
    assert "Weekly Unlock" in weekly["cara_ikut"]
    assert weekly["reward"] == "$19.4m"
    assert "0.38% of float" in weekly["cara_ikut"]
    assert weekly["deadline"] is not None
    valueless = by_name["Kwenta"]
    assert valueless["reward"] is None
    assert "Cliff Unlock" in valueless["cara_ikut"]


def test_cryptorank_unlocks_parses_row(monkeypatch):
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(CR_UNLOCK_HTML))
    items = fetch_cryptorank_unlocks()
    # The blurred aria-hidden teaser row (Zora) is skipped: decoy data.
    assert len(items) == 1
    it = items[0]
    assert it["judul"] == "Bware Labs INFRA"
    assert it["url"] == "https://cryptorank.io/price/bware-labs/vesting"
    assert it["kategori"] == "unlocks"
    assert it["deadline"].startswith("2026-09-30")
    assert it["reward"] == "$2.06K"
    assert "INFRA 50.15K" in it["cara_ikut"]


def test_new_fetchers_never_raise(monkeypatch):
    def _boom(url, source):
        raise RuntimeError("net down")
    monkeypatch.setattr(sources_scrape, "_fetch_html", _boom)
    for fn, name in (
        (fetch_cryptorank_drophunting, "cryptorank_drop"),
        (fetch_airdrops_io, "airdrops_io"),
        (fetch_defillama_unlocks, "defillama"),
        (fetch_cryptorank_unlocks, "cryptorank_unlock"),
    ):
        assert fn() == []
        assert name in source_errors


# --- Pintu promos (Task 9: replaces dead Binance/Bybit campaign sources) ---

PINTU_PROMO_HTML = """
<html><body>
<article id="post-292653" class="blog-post row align-items-center post-292653 post type-post status-publish format-standard has-post-thumbnail hentry category-promo">
  <h2><a href="https://blog.pintu.co.id/id/posts/adu-analisa-chart-amd-september-2026">Siap Adu Analisa Chart AMD, Buktikan Analisamu &amp; Rebut Total Hadiah Rp2 Juta!</a></h2>
  <span>September 25, 2026</span>
  <p>Hi Teman Pintu, Chart Arena is here! Ikuti dan menangkan hadiah menarik.</p>
</article>
<article id="post-292057" class="blog-post row align-items-center post-292057 post type-post status-publish format-standard has-post-thumbnail hentry category-promo">
  <h2><a href="https://blog.pintu.co.id/id/posts/promo-earn-usdt-usdc-locked-90-september-2026">Promo Pintu Earn: Imbal Hasil USDT &amp; USDC Sampai Setara 4,5% per Tahun</a></h2>
  <span>September 14, 2026</span>
  <p>Dapatkan imbal hasil menarik untuk USDT dan USDC kamu.</p>
</article>
</body></html>
"""


def test_pintu_promos_parses_articles(monkeypatch):
    monkeypatch.setattr(
        sources_scrape, "_fetch_html", _mock_html(PINTU_PROMO_HTML)
    )
    # Same HTML for both pages -> dedupe collapses to 2 unique items.
    items = fetch_pintu_promos()
    assert len(items) == 2
    first = items[0]
    assert first["judul"] == (
        "Siap Adu Analisa Chart AMD, Buktikan Analisamu & Rebut "
        "Total Hadiah Rp2 Juta!"
    )
    assert first["url"] == (
        "https://blog.pintu.co.id/id/posts/adu-analisa-chart-amd-september-2026"
    )
    assert first["kategori"] == "campaign"
    assert first["exchange"] == "Pintu Promo"
    assert first["reward"] == "Rp2 Juta"
    assert first["deadline"] is None
    assert "Chart Arena is here" in first["cara_ikut"]
    second = items[1]
    assert "4,5% per Tahun" in second["judul"]
    assert second["reward"] is None  # no Rp mention in title/excerpt


def test_pintu_promos_reward_from_excerpt(monkeypatch):
    html = """
    <html><body><article>
      <h2><a href="https://blog.pintu.co.id/id/posts/x">Giveaway Tebak Skor</a></h2>
      <span>September 21, 2026</span>
      <p>Ikuti giveaway dan menangkan total hadiah senilai Rp6 Juta!</p>
    </article></body></html>
    """
    monkeypatch.setattr(sources_scrape, "_fetch_html", _mock_html(html))
    items = fetch_pintu_promos()
    assert len(items) == 1
    assert items[0]["reward"] == "Rp6 Juta"


def test_pintu_promos_partial_page_failure_keeps_data(monkeypatch):
    def _fake(url, source):
        return PINTU_PROMO_HTML if "page/2" not in url else None

    monkeypatch.setattr(sources_scrape, "_fetch_html", _fake)
    items = fetch_pintu_promos()
    assert len(items) == 2
    # Data delivered despite one page failing -> source not reported failed.
    assert "pintu_promo" not in source_errors


def test_pintu_promos_never_raise(monkeypatch):
    def _boom(url, source):
        raise RuntimeError("net down")

    monkeypatch.setattr(sources_scrape, "_fetch_html", _boom)
    assert fetch_pintu_promos() == []
    assert "pintu_promo" in source_errors
    monkeypatch.setattr(
        sources_scrape, "_fetch_html", _mock_html("<html>no articles</html>")
    )
    source_errors.clear()
    assert fetch_pintu_promos() == []
