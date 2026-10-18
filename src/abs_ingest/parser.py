"""Read book number and a clean name out of messy folder / file names.

Examples this has to handle (none of them contain an author):

    All Jobs and Classes! I Just Wanted One Skill, Not Them All!, Book 4
    Azarinth Healer, Book 7
    Backstreet Evolutionist Book 5
    Book 6 Nameless Sovereign
    Chaos Walking Complete Chronological Collection      (box set, no number)
    The Stubborn Skill-Grinder in a Time Loop 5          (bare trailing number)
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .models import ParsedName

AUDIO_EXTS = {".m4b", ".m4a", ".mp3", ".flac", ".ogg", ".opus", ".aac", ".wma"}

_NOISE = [
    re.compile(r"\((?:un)?abridged\)", re.I),
    re.compile(r"\[[^\]]*\]"),
    re.compile(r"\b\d{2,3}\s?kbps\b", re.I),
]

_KEY = r"(?:book|vol(?:ume)?\.?|#)"
_NUM = r"(\d+(?:\.\d+)?)"

# "Book 6 Nameless Sovereign"
_START = re.compile(rf"^{_KEY}\s*{_NUM}\s*[:,\-–.]?\s*(.+)$", re.I)
# "Azarinth Healer, Book 7" / "Backstreet Evolutionist Book 5" / "X - Vol. 3"
_END_EXPLICIT = re.compile(rf"^(.+?)[\s,:\-–]+{_KEY}\s*{_NUM}\s*$", re.I)
# "The Stubborn Skill-Grinder in a Time Loop 5" (1-2 digits only: "Fahrenheit 451" stays whole)
_END_BARE = re.compile(r"^(.+?)\s+(\d{1,2})$")

_COLLECTION = re.compile(
    r"\b(collection|box(?:ed)?\s?set|omnibus|anthology|books?\s+\d+\s*(?:-|to)\s*\d+)\b",
    re.I,
)

_TRIM = " ,;:-–\t"


def clean_name(raw: str) -> str:
    """Remove file extensions and common release noise before parsing a name."""
    name = raw
    if Path(name).suffix.lower() in AUDIO_EXTS:
        name = Path(name).stem
    name = name.replace("_", " ")
    for pattern in _NOISE:
        name = pattern.sub(" ", name)
    return re.sub(r"\s+", " ", name).strip(_TRIM + " ")


def parse_name(raw: str) -> ParsedName:
    """Extract a clean base title, optional sequence number, and collection flag."""
    clean = clean_name(raw)
    is_collection = bool(_COLLECTION.search(clean))

    m = _START.match(clean)
    if m:
        return ParsedName(raw, clean, m.group(2).strip(_TRIM), m.group(1), "explicit", is_collection)

    m = _END_EXPLICIT.match(clean)
    if m:
        return ParsedName(raw, clean, m.group(1).strip(_TRIM), m.group(2), "explicit", is_collection)

    m = _END_BARE.match(clean)
    if m and not is_collection:
        return ParsedName(raw, clean, m.group(1).strip(_TRIM), m.group(2), "bare", is_collection)

    return ParsedName(raw, clean, clean, None, "", is_collection)


def normalize(text: str) -> str:
    """Lowercase, accents and punctuation removed - for comparing names."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
