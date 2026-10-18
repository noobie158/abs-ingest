from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedName:
    """What could be read from a raw folder / file name."""

    raw: str
    clean: str  # noise removed, number still in place
    base: str  # noise removed AND book number removed (usually the series name)
    number: Optional[str] = None
    number_source: str = ""  # "explicit" ("Book 4") | "bare" ("... Loop 5") | ""
    is_collection: bool = False


@dataclass
class Candidate:
    """One result from an online lookup."""

    title: str
    author: str = ""
    series: Optional[str] = None
    sequence: Optional[str] = None
    asin: Optional[str] = None


@dataclass
class Book:
    """Final identification of an item, with a confidence score."""

    title: str = ""
    author: str = ""
    series: Optional[str] = None
    number: Optional[str] = None
    asin: Optional[str] = None
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    source: str = ""  # alias | lookup | tags | none

    @property
    def in_series(self) -> bool:
        """Whether both a series name and a sequence number are known."""
        return bool(self.series and self.number)
