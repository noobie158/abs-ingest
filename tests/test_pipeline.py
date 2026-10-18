import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from abs_ingest import organizer
from abs_ingest.aliases import Aliases
from abs_ingest.cli import cmd_approve

from conftest import cand, make_book_dir

SERIES7 = cand("The Door", series="Azarinth Healer", sequence="7")


def test_confident_book_is_filed_with_metadata_and_scan(cfg, make_pipeline):
    pipe, fake, notifier = make_pipeline([SERIES7])
    item = make_book_dir(cfg.inbox, "Azarinth Healer, Book 7")

    result = pipe.process(item)

    dest = cfg.library / "Test Author" / "Azarinth Healer" / "Book 07 - The Door"
    assert result.status == "filed" and result.destination == dest
    assert (dest / "part1.mp3").exists()
    meta = json.loads((dest / "metadata.json").read_text())
    assert meta["authors"] == ["Test Author"] and meta["series"] == ["Azarinth Healer #7"]
    assert not item.exists() and not list(cfg.processing.iterdir())

    pipe.flush_scan()
    assert fake.scans == ["lib1"]


def test_single_m4b_file_is_filed(cfg, make_pipeline):
    pipe, _, _ = make_pipeline([SERIES7])
    f = cfg.inbox / "Azarinth Healer, Book 7.m4b"
    f.write_bytes(b"x")
    assert pipe.process(f).status == "filed"
    dest = cfg.library / "Test Author" / "Azarinth Healer" / "Book 07 - The Door"
    assert (dest / "Azarinth Healer, Book 7.m4b").exists()


def test_no_lookup_result_goes_to_review_with_sidecar(cfg, make_pipeline):
    pipe, _, notifier = make_pipeline([])
    item = make_book_dir(cfg.inbox, "Backstreet Evolutionist Book 5")

    result = pipe.process(item)

    assert result.status == "review"
    assert (cfg.review / "Backstreet Evolutionist Book 5").is_dir()
    sidecar = json.loads((cfg.review / ".Backstreet Evolutionist Book 5.review.json").read_text())
    assert sidecar["parsed"]["number"] == "5" and sidecar["reasons"]
    assert notifier.events and notifier.events[0][0] == "review"
    assert not any(cfg.library.rglob("*.mp3"))


def test_collection_goes_to_review(cfg, make_pipeline):
    pipe, _, _ = make_pipeline([SERIES7])
    item = make_book_dir(cfg.inbox, "Chaos Walking Complete Chronological Collection")
    result = pipe.process(item)
    assert result.status == "review" and "collection" in result.reason


def test_lookup_error_goes_to_review_not_failed(cfg, make_pipeline):
    pipe, _, _ = make_pipeline(fail_search=True)
    item = make_book_dir(cfg.inbox, "Azarinth Healer, Book 7")
    result = pipe.process(item)
    assert result.status == "review" and "search failed" in result.reason


def test_lookup_not_configured_goes_to_review(cfg, make_pipeline):
    pipe, _, _ = make_pipeline(client=False)
    item = make_book_dir(cfg.inbox, "Azarinth Healer, Book 7")
    result = pipe.process(item)
    assert result.status == "review" and "not configured" in result.reason


def test_lookup_result_without_author_goes_to_review(cfg, make_pipeline):
    pipe, _, _ = make_pipeline([cand("A Standalone Novel", author="")])
    item = make_book_dir(cfg.inbox, "A Standalone Novel")

    result = pipe.process(item)

    assert result.status == "review" and "author" in result.reason.lower()
    assert (cfg.review / "A Standalone Novel").is_dir()
    assert not any(cfg.library.rglob("*.mp3"))


def test_existing_destination_is_never_overwritten(cfg, make_pipeline):
    pipe, _, _ = make_pipeline([SERIES7])
    existing = cfg.library / "Test Author" / "Azarinth Healer" / "Book 07 - The Door"
    existing.mkdir(parents=True)
    (existing / "keep.mp3").write_bytes(b"original")

    result = pipe.process(make_book_dir(cfg.inbox, "Azarinth Healer, Book 7"))

    assert result.status == "review" and "already exists" in result.reason
    assert (existing / "keep.mp3").read_bytes() == b"original"


def test_unexpected_error_goes_to_failed_with_reason(cfg, make_pipeline, monkeypatch):
    pipe, _, notifier = make_pipeline([SERIES7])

    def boom(src, dest):
        raise OSError("disk exploded")

    monkeypatch.setattr(organizer, "place", boom)
    result = pipe.process(make_book_dir(cfg.inbox, "Azarinth Healer, Book 7"))

    assert result.status == "failed" and "disk exploded" in result.reason
    assert (cfg.failed / "Azarinth Healer, Book 7").is_dir()
    assert "disk exploded" in (cfg.failed / "Azarinth Healer, Book 7.error.txt").read_text()
    assert notifier.events[-1][0] == "failed"


def test_metadata_failure_after_move_is_parked_in_failed(cfg, make_pipeline, monkeypatch):
    pipe, _, _ = make_pipeline([SERIES7])

    def fail_metadata(folder, book):
        raise OSError("metadata disk error")

    monkeypatch.setattr("abs_ingest.pipeline.write_metadata", fail_metadata)
    result = pipe.process(make_book_dir(cfg.inbox, "Azarinth Healer, Book 7"))

    assert result.status == "failed"
    assert result.destination is not None and result.destination.is_relative_to(cfg.failed)
    assert result.destination.is_dir()
    assert not (cfg.library / "Test Author" / "Azarinth Healer" / "Book 07 - The Door").exists()


def test_review_sidecar_failure_is_parked_in_failed(cfg, make_pipeline, monkeypatch):
    pipe, _, _ = make_pipeline([])
    original_write_text = Path.write_text

    def fail_review_sidecar(path, *args, **kwargs):
        if path.name.endswith(".review.json"):
            raise OSError("review sidecar denied")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_review_sidecar)
    result = pipe.process(make_book_dir(cfg.inbox, "Unmatched Book"))

    assert result.status == "failed"
    assert result.destination is not None and result.destination.is_relative_to(cfg.failed)
    assert result.destination.is_dir()
    assert not (cfg.review / "Unmatched Book").exists()
    assert (result.destination.parent / f"{result.destination.name}.error.txt").exists()


def test_process_rejects_symlink_without_changing_target(cfg, make_pipeline, tmp_path):
    pipe, _, _ = make_pipeline([SERIES7])
    external = tmp_path / "external.m4b"
    external.write_bytes(b"keep")
    external.chmod(0o600)
    link = cfg.inbox / "Azarinth Healer, Book 7.m4b"
    try:
        link.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    result = pipe.process(link)

    assert result.status == "failed" and "symlink" in result.reason
    assert link.is_symlink() and external.stat().st_mode & 0o777 == 0o600


def test_process_rejects_nested_symlink_without_changing_target(cfg, make_pipeline, tmp_path):
    pipe, _, _ = make_pipeline([SERIES7])
    external = tmp_path / "external.mp3"
    external.write_bytes(b"keep")
    external.chmod(0o600)
    item = make_book_dir(cfg.inbox, "Azarinth Healer, Book 7", files=())
    link = item / "linked-track.mp3"
    try:
        link.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    result = pipe.process(item)

    assert result.status == "failed" and "symlink" in result.reason
    assert link.is_symlink() and external.stat().st_mode & 0o777 == 0o600


def test_approve_metadata_failure_rolls_item_back(cfg, make_pipeline, monkeypatch):
    pipe, _, _ = make_pipeline([])
    item = cfg.review / "Approved Book"
    item.mkdir()
    (item / "book.mp3").write_bytes(b"audio")
    monkeypatch.setattr("abs_ingest.pipeline.write_metadata", lambda *args: (_ for _ in ()).throw(OSError("metadata disk error")))

    with pytest.raises(OSError, match="metadata disk error"):
        pipe.approve("Approved Book", author="Test Author")

    assert item.is_dir() and (item / "book.mp3").exists()
    assert not any(cfg.library.rglob("*.mp3"))
    assert not any(cfg.library.rglob("metadata.json"))


def test_approve_cli_returns_failure_for_io_error(cfg, make_pipeline, monkeypatch):
    pipe, _, _ = make_pipeline([])
    monkeypatch.setattr(pipe, "approve", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk error")))
    monkeypatch.setattr("abs_ingest.cli.build_pipeline", lambda config: pipe)
    args = SimpleNamespace(name="Book", author="Author", series=None, number=None, title=None, no_remember=True)

    assert cmd_approve(cfg, args) == 1


def test_one_failure_does_not_stop_the_next_book(cfg, make_pipeline, monkeypatch):
    pipe, _, _ = make_pipeline([SERIES7])
    real_place = organizer.place
    calls = []

    def flaky(src, dest):
        calls.append(src.name)
        if len(calls) == 1:
            raise OSError("first one fails")
        return real_place(src, dest)

    monkeypatch.setattr(organizer, "place", flaky)
    first = pipe.process(make_book_dir(cfg.inbox, "Azarinth Healer, Book 7"))
    second = pipe.process(make_book_dir(cfg.inbox, "Azarinth Healer, Book 7 "))
    assert first.status == "failed"
    assert second.status in ("filed", "review")


def test_dry_run_changes_nothing(cfg, make_pipeline):
    pipe, fake, _ = make_pipeline([SERIES7])
    pipe.dry_run = True
    item = make_book_dir(cfg.inbox, "Azarinth Healer, Book 7")
    result = pipe.process(item)
    assert result.status == "dry-run"
    assert item.exists() and not any(cfg.library.rglob("*"))
    pipe.flush_scan()
    assert fake.scans == []


def test_approve_files_item_and_remembers_series(cfg, make_pipeline):
    pipe, _, _ = make_pipeline([])
    pipe.process(make_book_dir(cfg.inbox, "Backstreet Evolutionist Book 5"))

    result = pipe.approve(
        "Backstreet Evolutionist Book 5", author="Test Author", series="Backstreet Evolutionist", number="5"
    )

    assert result.status == "filed"
    assert not (cfg.review / "Backstreet Evolutionist Book 5").exists()
    assert not (cfg.review / ".Backstreet Evolutionist Book 5.review.json").exists()
    assert (cfg.library / "Test Author" / "Backstreet Evolutionist").is_dir()

    # next book of that series is now automatic - even with lookup returning nothing
    pipe2, _, _ = make_pipeline([])
    pipe2.aliases = Aliases(cfg.aliases_file)
    again = pipe2.process(make_book_dir(cfg.inbox, "Backstreet Evolutionist Book 6"))
    assert again.status == "filed"
    assert list((cfg.library / "Test Author" / "Backstreet Evolutionist").glob("Book 06 - *"))


def test_approve_rejects_path_outside_review(cfg, make_pipeline):
    pipe, _, _ = make_pipeline([])
    outside = cfg.root / "outside.m4b"
    outside.write_bytes(b"keep")

    with pytest.raises(FileNotFoundError):
        pipe.approve(str(outside), author="Test Author")

    assert outside.read_bytes() == b"keep"


def test_review_items_are_kept_apart_from_each_other(cfg, make_pipeline):
    pipe, _, _ = make_pipeline([])
    pipe.process(make_book_dir(cfg.inbox, "Same Name Book 1"))
    pipe.process(make_book_dir(cfg.inbox, "Same Name Book 1"))
    assert len([p for p in cfg.review.iterdir() if p.is_dir()]) == 2
