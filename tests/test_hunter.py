"""Tests for scan/hunter.py: orchestrator merge/diff/write + all-fail guard."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scan.hunter as hunter  # noqa: E402
from scan import sources_api as api  # noqa: E402
from scan import sources_scrape as scrape  # noqa: E402

ALL_SOURCE_NAMES = {
    "binance", "bybit", "okx",
    "indodax", "tokocrypto", "pintu", "pintu_promo",
    "cryptorank_drop", "airdrops_io", "defillama", "cryptorank_unlock",
}


def _fail_factory(errors, name, message="HTTP 403"):
    def _fail():
        errors[name] = message
        return []

    return _fail


def _patch_all_failing(monkeypatch):
    api.source_errors.clear()
    scrape.source_errors.clear()
    monkeypatch.setattr(
        api, "fetch_binance", _fail_factory(api.source_errors, "binance")
    )
    monkeypatch.setattr(
        api, "fetch_bybit", _fail_factory(api.source_errors, "bybit")
    )
    monkeypatch.setattr(
        api, "fetch_okx", _fail_factory(api.source_errors, "okx")
    )
    # NOTE: api.fetch_cryptorank_drops is retired from the hourly run
    # (free plan paywalls it); the website-table fetchers below replaced it.
    monkeypatch.setattr(
        scrape,
        "fetch_cryptorank_drophunting",
        _fail_factory(scrape.source_errors, "cryptorank_drop"),
    )
    monkeypatch.setattr(
        scrape,
        "fetch_airdrops_io",
        _fail_factory(scrape.source_errors, "airdrops_io"),
    )
    monkeypatch.setattr(
        scrape,
        "fetch_defillama_unlocks",
        _fail_factory(scrape.source_errors, "defillama"),
    )
    monkeypatch.setattr(
        scrape,
        "fetch_cryptorank_unlocks",
        _fail_factory(scrape.source_errors, "cryptorank_unlock"),
    )
    monkeypatch.setattr(
        scrape, "fetch_indodax", _fail_factory(scrape.source_errors, "indodax")
    )
    monkeypatch.setattr(
        scrape,
        "fetch_tokocrypto",
        _fail_factory(scrape.source_errors, "tokocrypto"),
    )
    monkeypatch.setattr(
        scrape, "fetch_pintu", _fail_factory(scrape.source_errors, "pintu")
    )
    monkeypatch.setattr(
        scrape,
        "fetch_pintu_promos",
        _fail_factory(scrape.source_errors, "pintu_promo"),
    )


def _old_item():
    return {
        "id": "abc123",
        "kategori": "listing",
        "exchange": "Binance",
        "judul": "Binance Will List XYZ",
        "ditemukan": "2026-09-30T10:00:00+08:00",
        "deadline": None,
        "reward": None,
        "cara_ikut": None,
        "url": "https://www.binance.com/en/support/announcement/xyz",
        "is_new": False,
    }


def _seed_old_data(data_dir):
    (data_dir / "listings.json").write_text(
        json.dumps([_old_item()], ensure_ascii=False)
    )
    (data_dir / ".snapshot.json").write_text(
        json.dumps({"abc123": _old_item()}, ensure_ascii=False)
    )


def test_all_sources_fail_keeps_old_data(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed_old_data(data_dir)
    _patch_all_failing(monkeypatch)

    before = (data_dir / "listings.json").read_text()
    result = hunter.run_scan(str(data_dir))

    assert result == "UNCHANGED"
    # old data files untouched — not overwritten with empty data
    assert (data_dir / "listings.json").read_text() == before
    assert not (data_dir / "airdrops.json").exists()
    assert not (data_dir / "campaigns.json").exists()
    assert not (data_dir / "unlocks.json").exists()
    # meta.json updated: every source marked offline
    meta = json.loads((data_dir / "meta.json").read_text())
    assert set(meta["sources"]) == ALL_SOURCE_NAMES
    assert all(s == "error" for s in meta["sources"].values())
    assert "last_scan" in meta


def test_source_status_mapping():
    assert hunter.source_status({"cryptorank": "need_key"}, "cryptorank") == "need_key"
    assert hunter.source_status({"cryptorank": "plan_limited"}, "cryptorank") == "plan_limited"
    assert hunter.source_status({"binance": "HTTP 403"}, "binance") == "error"
    assert hunter.source_status({}, "okx") == "ok"


def test_partial_success_writes_files_and_reports_changed(
    tmp_path, monkeypatch
):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _patch_all_failing(monkeypatch)

    fresh = dict(_old_item())
    fresh["id"] = "def456"
    fresh["judul"] = "Binance Will List ABC"
    fresh["is_new"] = True
    monkeypatch.setattr(api, "fetch_binance", lambda: [fresh])
    api.source_errors.pop("binance", None)

    result = hunter.run_scan(str(data_dir))

    assert result == "CHANGED"
    listings = json.loads((data_dir / "listings.json").read_text())
    assert len(listings) == 1
    assert listings[0]["id"] == "def456"
    assert listings[0]["is_new"] is True
    assert json.loads((data_dir / "airdrops.json").read_text()) == []
    assert json.loads((data_dir / "campaigns.json").read_text()) == []
    assert json.loads((data_dir / "unlocks.json").read_text()) == []
    meta = json.loads((data_dir / "meta.json").read_text())
    assert meta["sources"]["binance"] == "ok"
    assert meta["sources"]["bybit"] == "error"
    assert "unlocks" in meta["notes"]


def test_repeat_scan_with_same_data_reports_unchanged(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _patch_all_failing(monkeypatch)
    item = _old_item()
    monkeypatch.setattr(api, "fetch_binance", lambda: [dict(item)])
    api.source_errors.pop("binance", None)

    assert hunter.run_scan(str(data_dir)) == "CHANGED"  # first sighting
    assert hunter.run_scan(str(data_dir)) == "UNCHANGED"  # nothing new
    listings = json.loads((data_dir / "listings.json").read_text())
    assert listings[0]["is_new"] is False
    # first-seen timestamp preserved, not refreshed every scan
    assert listings[0]["ditemukan"] == "2026-09-30T10:00:00+08:00"
