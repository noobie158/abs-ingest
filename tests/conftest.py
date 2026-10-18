from __future__ import annotations

import pytest

from abs_ingest.aliases import Aliases
from abs_ingest.config import Config
from abs_ingest.models import Candidate
from abs_ingest.pipeline import Pipeline


class FakeClient:
    """Stands in for Audiobookshelf: canned search results, records scans."""

    def __init__(self, results=None, fail_search=False):
        self.results = results or []
        self.fail_search = fail_search
        self.scans = []

    def search_books(self, title, author=None):
        if self.fail_search:
            from abs_ingest.abs_client import AbsError

            raise AbsError("search failed (simulated)")
        return list(self.results)

    def scan_library(self, library_id, force=False):
        self.scans.append(library_id)


class FakeNotifier:
    def __init__(self):
        self.events = []

    def send(self, event, title, message):
        self.events.append((event, message))


@pytest.fixture
def cfg(tmp_path):
    c = Config(
        root=tmp_path,
        inbox=tmp_path / "inbox",
        processing=tmp_path / "processing",
        review=tmp_path / "review",
        failed=tmp_path / "failed",
        library=tmp_path / "library",
        aliases_file=tmp_path / "aliases.yaml",
        stable_seconds=0,
        abs_url="http://abs.invalid",
        abs_token="x",
        abs_library_id="lib1",
    )
    # library and review stand in for the big mounted disk: they must already exist
    c.library.mkdir()
    c.review.mkdir()
    c.ensure_dirs()
    return c


@pytest.fixture
def make_pipeline(cfg):
    def _make(results=None, fail_search=False, client=True):
        fake = FakeClient(results, fail_search) if client else None
        notifier = FakeNotifier()
        pipe = Pipeline(cfg, Aliases(cfg.aliases_file), client=fake, notifier=notifier)
        return pipe, fake, notifier

    return _make


def make_book_dir(inbox, name, files=("part1.mp3",)):
    folder = inbox / name
    folder.mkdir()
    for f in files:
        (folder / f).write_bytes(b"not really audio")
    return folder


def cand(title, author="Test Author", series=None, sequence=None, asin=None):
    return Candidate(title=title, author=author, series=series, sequence=sequence, asin=asin)
