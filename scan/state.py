"""Snapshot persistence + is_new diffing for the Crypto Hunter scanner.

Stdlib only. Task 5's orchestrator consumes ``load_snapshot``,
``diff_new`` and ``save_snapshot`` — these interfaces are binding.

Snapshots are plain JSON files mapping item id -> item (Task 1's
``normalize`` output is fully JSON-serializable). All three functions are
fail-safe: a missing or corrupt snapshot degrades to an empty dict rather
than crashing the hourly scan.
"""
import json

__all__ = ["load_snapshot", "diff_new", "save_snapshot"]


def load_snapshot(path: str) -> dict:
    """Load a snapshot file, returning {id: item}.

    A missing file, unreadable file, invalid JSON, or JSON that is not a
    dict all yield {} so the scanner can start fresh.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def diff_new(old: dict, new: list) -> list:
    """Mark each item in ``new`` with ``is_new``.

    Items whose ``id`` already exists in ``old`` get ``is_new=False``;
    genuinely new ids get ``is_new=True``. Inputs are not mutated — a
    shallow copy of each item is returned, preserving order.
    """
    out = []
    for item in new:
        marked = dict(item)
        marked["is_new"] = item.get("id") not in old
        out.append(marked)
    return out


def save_snapshot(path: str, items: list) -> None:
    """Persist ``items`` as a snapshot file mapping id -> item.

    Items without an ``id`` cannot be keyed and are skipped.
    """
    snapshot = {item["id"]: item for item in items if item.get("id")}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
