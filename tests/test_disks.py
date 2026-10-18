import errno
import os
from pathlib import Path

from abs_ingest import organizer
from abs_ingest.config import ConfigError

from conftest import cand, make_book_dir

import pytest


def cross_disk_rename(blocked: Path):
    """os.rename that fails like a move between two disks for one specific path."""

    def rename(a, b):
        if Path(a) == blocked:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        os.rename(a, b)

    return rename


def test_move_across_disks_copies_then_removes_source(tmp_path):
    src = make_book_dir(tmp_path, "Book One")
    (src / "cover.jpg").write_bytes(b"img")
    dest = tmp_path / "other_disk" / "Book One"

    organizer.move_item(src, dest, rename=cross_disk_rename(src))

    assert (dest / "part1.mp3").read_bytes() == b"not really audio"
    assert (dest / "cover.jpg").exists()
    assert not src.exists()
    assert not [p for p in dest.parent.iterdir() if p.name.endswith(".partial")]


def test_move_single_file_across_disks(tmp_path):
    src = tmp_path / "Book.m4b"
    src.write_bytes(b"audio")
    dest = tmp_path / "x" / "Book.m4b"
    organizer.move_item(src, dest, rename=cross_disk_rename(src))
    assert dest.read_bytes() == b"audio" and not src.exists()


def test_failed_copy_keeps_the_source(tmp_path, monkeypatch):
    src = make_book_dir(tmp_path, "Book One")

    def broken_copy(*a, **k):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(organizer.shutil, "copytree", broken_copy)
    with pytest.raises(OSError):
        organizer.move_item(src, tmp_path / "d" / "Book One", rename=cross_disk_rename(src))
    assert (src / "part1.mp3").exists()  # original untouched


def test_failed_copy_does_not_remove_another_partial(tmp_path, monkeypatch):
    src = tmp_path / "Book.m4b"
    src.write_bytes(b"audio")
    dest = tmp_path / "other_disk" / "Book.m4b"
    dest.parent.mkdir()
    stale_partial = dest.parent / ".Book.m4b.partial"
    stale_partial.write_bytes(b"another process's copy")

    def fail_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(organizer.shutil, "copy2", fail_copy)
    with pytest.raises(OSError):
        organizer.move_item(src, dest, rename=cross_disk_rename(src))

    assert stale_partial.read_bytes() == b"another process's copy"
    assert src.exists()


def test_other_os_errors_are_not_swallowed(tmp_path):
    src = make_book_dir(tmp_path, "Book One")

    def denied(a, b):
        raise PermissionError(errno.EACCES, "denied")

    with pytest.raises(PermissionError):
        organizer.move_item(src, tmp_path / "Book Two", rename=denied)


def test_missing_library_disk_is_reported_not_created(cfg, make_pipeline):
    pipe, _, _ = make_pipeline([cand("The Door", series="Azarinth Healer", sequence="7")])
    item = make_book_dir(cfg.inbox, "Azarinth Healer, Book 7")
    cfg.library.rmdir()  # simulate an unmounted disk

    result = pipe.process(item)

    assert result.status == "failed" and "mounted" in result.reason
    assert (item / "part1.mp3").exists()  # book stays in the inbox
    assert not cfg.library.exists()  # nothing silently created


def test_ensure_dirs_refuses_to_create_the_library(tmp_path):
    from abs_ingest.config import Config

    c = Config(
        root=tmp_path,
        inbox=tmp_path / "in",
        processing=tmp_path / "pr",
        review=tmp_path / "rv",
        failed=tmp_path / "fl",
        library=tmp_path / "lib",
    )
    with pytest.raises(ConfigError):
        c.ensure_dirs()
    assert not (tmp_path / "lib").exists() and not (tmp_path / "rv").exists()
