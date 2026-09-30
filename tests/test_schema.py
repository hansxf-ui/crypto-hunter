"""Tests for scan.schema — item schema + normalization (Task 1)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scan.schema import normalize, make_id, parse_deadline


def test_normalize_drops_item_missing_title():
    assert normalize({"url": "https://x"}, "listing", "Binance") is None


def test_normalize_drops_item_missing_url():
    assert normalize({"judul": "Will List XYZ"}, "listing", "Binance") is None


def test_normalize_returns_full_item_with_defaults():
    item = normalize(
        {"judul": "Will List XYZ", "url": "https://binance.com/x"},
        "listing",
        "Binance",
    )
    assert item is not None
    assert item["kategori"] == "listing"
    assert item["exchange"] == "Binance"
    assert item["judul"] == "Will List XYZ"
    assert item["url"] == "https://binance.com/x"
    assert item["deadline"] is None
    assert item["reward"] is None
    assert item["cara_ikut"] is None
    assert item["is_new"] is True
    assert "ditemukan" in item  # ISO-8601 timestamp


def test_normalize_sets_stable_id_internally():
    a = normalize(
        {"judul": "Will List XYZ", "url": "https://binance.com/a"},
        "listing",
        "Binance",
    )
    b = normalize(
        {"judul": "Will List XYZ", "url": "https://binance.com/b"},
        "listing",
        "Binance",
    )
    assert a["id"] == b["id"] == make_id("Binance", "Will List XYZ")


def test_normalize_passes_through_reward_and_deadline():
    item = normalize(
        {
            "judul": "Airdrop XYZ",
            "url": "https://x",
            "reward": "pool 100.000 XYZ",
            "deadline": "2026-10-07T14:00:00+08:00",
        },
        "airdrop",
        "CryptoRank",
    )
    assert item["reward"] == "pool 100.000 XYZ"
    assert item["deadline"] == "2026-10-07T14:00:00+08:00"


def test_parse_deadline_returns_none_for_garbage():
    assert parse_deadline("segera hadir") is None


def test_parse_deadline_none_in_none_out():
    assert parse_deadline(None) is None


def test_parse_deadline_iso_passthrough():
    assert parse_deadline("2026-10-07T14:00:00+08:00") == "2026-10-07T14:00:00+08:00"


def test_parse_deadline_english_date():
    out = parse_deadline("Oct 7, 2026")
    assert out is not None and out.startswith("2026-10-07")


def test_parse_deadline_epoch():
    out = parse_deadline("1791331200")  # 2026-10-07T00:00:00Z
    assert out is not None and out.startswith("2026-10-07")


def test_make_id_stable_across_url_change():
    assert make_id("Binance", "Will List XYZ") == make_id("Binance", "Will List XYZ")


def test_make_id_differs_per_exchange_and_title():
    assert make_id("Binance", "Will List XYZ") != make_id("Bybit", "Will List XYZ")
    assert make_id("Binance", "Will List XYZ") != make_id("Binance", "Will List ABC")
