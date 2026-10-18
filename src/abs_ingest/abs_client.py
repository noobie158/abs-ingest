"""Talks to the Audiobookshelf REST API: book search (for identification) and library scan."""

from __future__ import annotations

import re
from typing import Optional

import requests

from .models import Candidate


class AbsError(Exception):
    """Raised when an Audiobookshelf request fails or returns an unexpected shape."""

    pass


def parse_result(raw: dict) -> Candidate:
    """Turn one /api/search/books result into a Candidate (tolerant of shape differences)."""
    series: Optional[str] = None
    sequence: Optional[str] = None

    s = raw.get("series")
    if isinstance(s, list) and s:
        first = s[0]
        if isinstance(first, dict):
            series = first.get("series") or first.get("name")
            seq = first.get("sequence")
            sequence = str(seq) if seq not in (None, "") else None
        elif isinstance(first, str):
            s = first
    if isinstance(s, str) and s:
        m = re.match(r"^(.*?)\s*#\s*(\d+(?:\.\d+)?)$", s)
        if m:
            series, sequence = m.group(1), m.group(2)
        else:
            series = s

    author = raw.get("author") or ""
    if isinstance(author, list):
        author = ", ".join(str(a) for a in author)

    return Candidate(
        title=str(raw.get("title") or "").strip(),
        author=str(author).strip(),
        series=series or None,
        sequence=sequence,
        asin=raw.get("asin") or None,
    )


class AbsClient:
    """HTTP client for ABS catalog searches and library scans."""

    def __init__(
        self,
        url: str,
        token: str,
        provider: str = "audible",
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ):
        """Configure the API base URL, provider, timeout, and bearer-authenticated session."""
        self.base = url.rstrip("/")
        self.provider = provider
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def search_books(self, title: str, author: Optional[str] = None) -> list[Candidate]:
        """Search the configured provider and normalize valid results into candidates."""
        params = {"title": title, "provider": self.provider}
        if author:
            params["author"] = author
        try:
            resp = self.session.get(
                f"{self.base}/api/search/books", params=params, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise AbsError(f"search failed for {title!r}: {exc}") from exc
        if not isinstance(data, list):
            raise AbsError(f"unexpected search response for {title!r}: {type(data).__name__}")
        return [parse_result(item) for item in data if isinstance(item, dict)]

    def scan_library(self, library_id: str, force: bool = False) -> None:
        """Ask ABS to rescan one library, optionally forcing a full scan."""
        try:
            resp = self.session.post(
                f"{self.base}/api/libraries/{library_id}/scan",
                params={"force": int(force)},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise AbsError(f"library scan failed: {exc}") from exc
