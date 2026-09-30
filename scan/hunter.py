"""Hourly orchestrator for the Crypto Hunter scanner.

Stdlib only. Runs every fetcher from Task 3 (API) and Task 4 (scrape),
merges the NORMALIZED items they return (no re-normalization here), diffs
against ``data/.snapshot.json``, and writes::

    data/listings.json    - Binance, Bybit, OKX, Indodax, Tokocrypto, Pintu
    data/airdrops.json    - CryptoRank drophunting
    data/campaigns.json   - Binance promotions + Bybit activities
    data/unlocks.json     - [] (no fetcher yet; see meta.json "notes")
    data/meta.json        - last_scan + per-source status

Prints CHANGED or UNCHANGED and exits 0. If EVERY source fails, existing
data files are left untouched and only meta.json is updated (still
UNCHANGED, still exit 0) — the hourly cron must never push empty data.

CLI: ``python3 scan/hunter.py [--data-dir DIR]``
"""
import argparse
import json
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scan import sources_api as api  # noqa: E402
from scan import sources_scrape as scrape  # noqa: E402
from scan.state import diff_new, load_snapshot, save_snapshot  # noqa: E402

__all__ = ["run_scan", "source_status", "main"]

CATEGORY_FILES = {
    "listings": "listings.json",
    "airdrops": "airdrops.json",
    "campaigns": "campaigns.json",
    "unlocks": "unlocks.json",
}

#: (meta source name, category, module, fetch attr). Built at call time so
#: tests can monkeypatch the fetch functions on the modules.
def _fetchers():
    return [
        ("binance", "listings", api, "fetch_binance"),
        ("bybit", "listings", api, "fetch_bybit"),
        ("okx", "listings", api, "fetch_okx"),
        ("indodax", "listings", scrape, "fetch_indodax"),
        ("tokocrypto", "listings", scrape, "fetch_tokocrypto"),
        ("pintu", "listings", scrape, "fetch_pintu"),
        # NOTE: the CryptoRank *API* fetcher (api.fetch_cryptorank_drops) is
        # retired from the hourly run: the free Sandbox plan 403s on the
        # drophunting/unlocks endpoints ("plan_limited"). The same data is
        # now collected from CryptoRank's public website tables below (no key
        # needed). Re-register the API fetcher if the plan is ever upgraded.
        ("cryptorank_drop", "airdrops", scrape, "fetch_cryptorank_drophunting"),
        ("airdrops_io", "airdrops", scrape, "fetch_airdrops_io"),
        ("defillama", "unlocks", scrape, "fetch_defillama_unlocks"),
        ("cryptorank_unlock", "unlocks", scrape, "fetch_cryptorank_unlocks"),
        ("campaigns", "campaigns", scrape, "fetch_campaigns"),
    ]


def source_status(errors: dict, name: str) -> str:
    """Map a source's error entry to ok|error|need_key|plan_limited."""
    if name not in errors:
        return "ok"
    msg = errors[name]
    if msg == "need_key":
        return "need_key"
    if msg == "plan_limited":
        return "plan_limited"
    return "error"


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def run_scan(data_dir: str) -> str:
    """Run one full scan cycle. Returns "CHANGED" or "UNCHANGED"."""
    os.makedirs(data_dir, exist_ok=True)  # save_snapshot won't create dirs

    by_category: dict = {cat: [] for cat in CATEGORY_FILES}
    for name, category, module, attr in _fetchers():
        items = getattr(module, attr)() or []
        by_category[category].extend(items)

    errors = {}
    errors.update(api.source_errors)
    errors.update(scrape.source_errors)
    statuses = {
        name: source_status(errors, name) for name, _, _, _ in _fetchers()
    }

    meta = {
        "last_scan": datetime.now().astimezone().isoformat(),
        "sources": statuses,
        "notes": "unlocks: DeFiLlama + CryptoRank website tables (free)",
    }

    all_failed = all(name in errors for name, _, _, _ in _fetchers())
    if all_failed:
        # Every source failed: keep the old data files, update meta only.
        _write_json(os.path.join(data_dir, "meta.json"), meta)
        return "UNCHANGED"

    merged = (
        by_category["listings"]
        + by_category["airdrops"]
        + by_category["campaigns"]
        + by_category["unlocks"]
    )
    old_snapshot = load_snapshot(os.path.join(data_dir, ".snapshot.json"))
    diffed = diff_new(old_snapshot, merged)

    # Preserve first-seen timestamps: "ditemukan" means discovered-at,
    # not last-seen-at.
    for item in diffed:
        if not item["is_new"]:
            old_item = old_snapshot.get(item["id"]) or {}
            if old_item.get("ditemukan"):
                item["ditemukan"] = old_item["ditemukan"]

    changed = {item["id"] for item in diffed} != set(old_snapshot)

    by_id = {item["id"]: item for item in diffed}
    _write_json(
        os.path.join(data_dir, CATEGORY_FILES["listings"]),
        [by_id[i["id"]] for i in by_category["listings"]],
    )
    _write_json(
        os.path.join(data_dir, CATEGORY_FILES["airdrops"]),
        [by_id[i["id"]] for i in by_category["airdrops"]],
    )
    _write_json(
        os.path.join(data_dir, CATEGORY_FILES["campaigns"]),
        [by_id[i["id"]] for i in by_category["campaigns"]],
    )
    _write_json(
        os.path.join(data_dir, CATEGORY_FILES["unlocks"]),
        [by_id[i["id"]] for i in by_category["unlocks"]],
    )
    _write_json(os.path.join(data_dir, "meta.json"), meta)
    save_snapshot(os.path.join(data_dir, ".snapshot.json"), diffed)

    return "CHANGED" if changed else "UNCHANGED"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crypto Hunter hourly scan")
    parser.add_argument(
        "--data-dir", default=os.path.join(REPO_ROOT, "data")
    )
    args = parser.parse_args(argv)
    try:
        result = run_scan(args.data_dir)
    except Exception as exc:  # noqa: BLE001 - cron must see a clean signal
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
