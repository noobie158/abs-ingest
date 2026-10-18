"""Write the metadata.json that Audiobookshelf reads from inside a book folder."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Book
from .organizer import clean_title


def build_metadata(book: Book) -> dict:
    """Build the ABS `metadata.json` fields available from an identified book."""
    data: dict = {"title": book.title or clean_title("", book.series, book.number)}
    if book.author:
        data["authors"] = [book.author]
    if book.series:
        data["series"] = [f"{book.series} #{book.number}" if book.number else book.series]
    if book.asin:
        data["asin"] = book.asin
    return data


def write_metadata(folder: Path, book: Book) -> Path:
    """Serialize a book's metadata beside its audio files and return that file path."""
    target = folder / "metadata.json"
    target.write_text(
        json.dumps(build_metadata(book), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target
