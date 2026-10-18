"""Remembered corrections: 'Azarinth Healer' -> author + series, so the next book is automatic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

from .parser import normalize


class Aliases:
    """Persist human-approved mappings from parsed names to author and series."""

    def __init__(self, path: Path):
        """Load the alias database stored at `path`, if it already exists."""
        self.path = Path(path)
        self.data: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        """Read YAML entries and normalize their lookup keys."""
        if not self.path.is_file():
            self.data = {}
            return
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.data = {normalize(k): v for k, v in (raw.get("aliases") or {}).items()}

    def get(self, base_name: str) -> Optional[dict]:
        """Return a complete alias for `base_name`, or None when no usable match exists."""
        entry = self.data.get(normalize(base_name))
        if entry and entry.get("author") and entry.get("series"):
            return entry
        return None

    def add(self, base_name: str, author: str, series: str) -> None:
        """Record or replace a normalized mapping, then persist the updated database."""
        self.data[normalize(base_name)] = {"author": author, "series": series}
        self.save()

    def save(self) -> None:
        """Write aliases to a temporary YAML file and atomically replace the database."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump({"aliases": self.data}, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
