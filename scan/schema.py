"""Item schema + normalization for the Crypto Hunter scanner.

Stdlib only. Later tasks (snapshot diff, sources, orchestrator) consume
``normalize`` and ``make_id`` — the interfaces here are binding.
"""
import hashlib
from datetime import datetime, timezone

__all__ = ["normalize", "make_id", "parse_deadline"]

#: Fields every normalized item carries (spec section 4).
ITEM_FIELDS = (
    "id",
    "kategori",
    "exchange",
    "judul",
    "ditemukan",
    "deadline",
    "reward",
    "cara_ikut",
    "url",
    "is_new",
)


def _norm_text(value):
    """Collapse whitespace and lowercase for stable identity."""
    return " ".join(str(value).split()).lower()


def make_id(exchange: str, judul: str) -> str:
    """Return a stable id for an item.

    Derived from (exchange, judul) only, so the same event re-announced
    with a different URL keeps the same id and does not duplicate.
    """
    digest = hashlib.sha256(
        f"{_norm_text(exchange)}|{_norm_text(judul)}".encode("utf-8")
    ).hexdigest()
    return digest[:16]


def parse_deadline(s: str | None) -> str | None:
    """Parse a deadline string into ISO-8601, or None if unparseable.

    Understands ISO-8601, common English date spellings ("Oct 7, 2026"),
    and epoch seconds. Anything else (e.g. "segera hadir") -> None.
    """
    if s is None:
        return None
    text = str(s).strip()
    if not text:
        return None

    # 1. ISO-8601 (handles "2026-10-07T14:00:00+08:00", "2026-10-07", ...)
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        pass

    # 2. Common date spellings
    for fmt in (
        "%b %d, %Y",  # Oct 7, 2026
        "%B %d, %Y",  # October 7, 2026
        "%d %b %Y",  # 7 Oct 2026
        "%d %B %Y",  # 7 October 2026
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue

    # 3. Epoch seconds
    try:
        epoch = int(text)
    except ValueError:
        try:
            epoch = int(float(text))
        except ValueError:
            return None
    if epoch <= 0:
        return None
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _opt_str(value) -> str | None:
    """Optional string field: blank/empty -> None, else stripped."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize(raw: dict, kategori: str, exchange: str) -> dict | None:
    """Normalize one raw source item to the spec item schema.

    Required fields: ``judul`` and ``url`` (non-blank). Returns None when
    either is missing, so callers can drop the item.
    """
    if not isinstance(raw, dict):
        return None
    judul = _opt_str(raw.get("judul"))
    url = _opt_str(raw.get("url"))
    if not judul or not url:
        return None

    return {
        "id": make_id(exchange, judul),
        "kategori": kategori,
        "exchange": exchange,
        "judul": judul,
        "ditemukan": datetime.now().astimezone().isoformat(),
        "deadline": parse_deadline(raw.get("deadline")),
        "reward": _opt_str(raw.get("reward")),
        "cara_ikut": _opt_str(raw.get("cara_ikut")),
        "url": url,
        "is_new": True,
    }
