"""Tests for scan/state.py: snapshot load/save + is_new diffing."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scan.state import diff_new, load_snapshot, save_snapshot


def test_diff_marks_only_truly_new(tmp_path):
    old = {"abc": {"id": "abc"}}
    new = [{"id": "abc"}, {"id": "def"}]
    out = diff_new(old, new)
    assert [i["is_new"] for i in out] == [False, True]


def test_load_missing_file_returns_empty(tmp_path):
    assert load_snapshot(str(tmp_path / "nope.json")) == {}


def test_save_then_load_roundtrip(tmp_path):
    path = str(tmp_path / "snap.json")
    items = [
        {"id": "abc", "judul": "one", "is_new": True},
        {"id": "def", "judul": "two", "is_new": False},
    ]
    save_snapshot(path, items)
    loaded = load_snapshot(path)
    assert set(loaded) == {"abc", "def"}
    assert loaded["abc"]["judul"] == "one"
    assert loaded["def"]["is_new"] is False


def test_diff_does_not_mutate_inputs():
    old = {"abc": {"id": "abc", "is_new": True}}
    new = [{"id": "abc"}, {"id": "def"}]
    diff_new(old, new)
    assert "is_new" not in new[0]
    assert old["abc"]["is_new"] is True


def test_load_invalid_json_returns_empty(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json")
    assert load_snapshot(str(path)) == {}
