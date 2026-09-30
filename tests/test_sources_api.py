"""Tests for scan.sources_api — API sources (Task 3).

All HTTP is mocked (monkeypatched _fetch_json); no network in this suite.
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scan import sources_api
from scan.sources_api import (
    fetch_binance,
    fetch_bybit,
    fetch_okx,
    fetch_cryptorank_drops,
    source_errors,
)


@pytest.fixture(autouse=True)
def clean_errors():
    source_errors.clear()
    yield
    source_errors.clear()


def _mock_fetch(payload):
    def _fake(url, source, headers=None, data=None):
        return payload

    return _fake


# --- Binance -------------------------------------------------------------

BINANCE_OK = {
    "code": "000000",
    "data": {
        "articles": [
            {
                "id": 285916,
                "code": "1a94597986cf476f939609c02b87ee79",
                "title": "Binance Will List XYZ (XYZ/USDT)",
                "catalogId": 48,
            },
            {
                "id": 285915,
                "code": "172e44302d6143578e40acc48570a2e5",
                "title": "Binance Will List ABC (ABC/USDT)",
                "catalogId": 48,
            },
        ]
    },
}


def test_fetch_binance_parses_listing(monkeypatch):
    monkeypatch.setattr(sources_api, "_fetch_json", _mock_fetch(BINANCE_OK))
    items = fetch_binance()
    assert items and items[0]["kategori"] == "listing"
    assert items[0]["exchange"] == "Binance"
    assert items[0]["judul"] == "Binance Will List XYZ (XYZ/USDT)"
    assert "1a94597986cf476f939609c02b87ee79" in items[0]["url"]
    assert len(items) == 2


def test_fetch_binance_bad_shape_returns_empty(monkeypatch):
    monkeypatch.setattr(sources_api, "_fetch_json", _mock_fetch({"nope": 1}))
    assert fetch_binance() == []
    assert "binance" in source_errors


def test_fetch_binance_never_raises(monkeypatch):
    def _boom(url, source, headers=None, data=None):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(sources_api, "_fetch_json", _boom)
    assert fetch_binance() == []
    assert "binance" in source_errors


# --- Bybit ---------------------------------------------------------------

BYBIT_OK = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "total": 1,
        "list": [
            {
                "title": "New Listing: Arbitrum (ARB)",
                "description": "Bybit is excited to announce the listing of ARB",
                "type": {"title": "New Listings", "key": "new_crypto"},
                "tags": ["Spot", "Spot Listings"],
                "url": "https://announcements.bybit.com/en-US/article/arb--blt123/",
                "dateTimestamp": 1679045608000,
            }
        ],
    },
}


def test_fetch_bybit_parses_listing(monkeypatch):
    monkeypatch.setattr(sources_api, "_fetch_json", _mock_fetch(BYBIT_OK))
    items = fetch_bybit()
    assert items and items[0]["kategori"] == "listing"
    assert items[0]["exchange"] == "Bybit"
    assert items[0]["judul"] == "New Listing: Arbitrum (ARB)"


def test_fetch_bybit_retcode_error_returns_empty(monkeypatch):
    monkeypatch.setattr(
        sources_api, "_fetch_json", _mock_fetch({"retCode": 10001, "retMsg": "bad"})
    )
    assert fetch_bybit() == []
    assert "bybit" in source_errors


# --- OKX -----------------------------------------------------------------

OKX_OK = {
    "code": "0",
    "msg": "",
    "data": [
        {
            "details": [
                {
                    "annType": "announcements-new-listings",
                    "title": "OKX will launch GRVT/USD for spot trading",
                    "url": "https://www.okx.com/en-us/help/okx-will-launch-grvt-usd",
                    "pTime": "1785380409238",
                    "businessPTime": "1785380400000",
                }
            ],
            "totalPage": "123",
        }
    ],
}


def test_fetch_okx_parses_listing(monkeypatch):
    monkeypatch.setattr(sources_api, "_fetch_json", _mock_fetch(OKX_OK))
    items = fetch_okx()
    assert items and items[0]["kategori"] == "listing"
    assert items[0]["exchange"] == "OKX"
    assert items[0]["judul"] == "OKX will launch GRVT/USD for spot trading"


def test_fetch_okx_bad_shape_returns_empty(monkeypatch):
    monkeypatch.setattr(sources_api, "_fetch_json", _mock_fetch({"code": "1"}))
    assert fetch_okx() == []
    assert "okx" in source_errors


# --- CryptoRank ----------------------------------------------------------

CRYPTO_RANK_OK = {
    "data": [
        {"name": "Project X", "slug": "project-x", "status": "active"},
        {"name": "Project Y", "slug": "project-y", "status": "active"},
    ]
}


def test_cryptorank_without_key_returns_empty(monkeypatch):
    monkeypatch.delenv("CRYPTORANK_API_KEY", raising=False)
    assert fetch_cryptorank_drops() == []
    assert source_errors.get("cryptorank") == "need_key"


def test_cryptorank_parses_with_key(monkeypatch):
    monkeypatch.setenv("CRYPTORANK_API_KEY", "dummy-key")
    monkeypatch.setattr(sources_api, "_fetch_json", _mock_fetch(CRYPTO_RANK_OK))
    items = fetch_cryptorank_drops()
    assert items and items[0]["kategori"] == "airdrop"
    assert items[0]["exchange"] == "CryptoRank"
    assert items[0]["judul"] == "Project X"
    assert "project-x" in items[0]["url"]
    assert len(items) == 2


def test_cryptorank_never_raises(monkeypatch):
    monkeypatch.setenv("CRYPTORANK_API_KEY", "dummy-key")

    def _boom(url, source, headers=None, data=None):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(sources_api, "_fetch_json", _boom)
    assert fetch_cryptorank_drops() == []
    assert "cryptorank" in source_errors
