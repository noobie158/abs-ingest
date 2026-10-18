"""Where a book goes in the library, and moving it there."""

from __future__ import annotations

import errno
import os
import re
import shutil
import uuid
from pathlib import Path

from .config import Config
from .models import Book

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_KEY = r"(?:book|vol(?:ume)?\.?|#)"


class _TemplateNumber(str):
    """Keep sequence numbers string-based while supporting integer format specs."""

    def __format__(self, spec: str) -> str:
        """Apply integer padding for `d` formats and normal string formatting otherwise."""
        if spec.endswith("d"):
            try:
                return format(int(self), spec)
            except ValueError as exc:
                raise ValueError("integer number format requires a whole-number sequence") from exc
        return super().__format__(spec)


def sanitize(text: str, fallback: str = "Unknown") -> str:
    """Safe for Linux AND for the Windows PC the files may be synced back to."""
    text = _INVALID.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:120].strip(" .") or fallback


def fmt_number(number: str) -> str:
    """Zero-pad integer sequences to two digits while preserving decimals and text."""
    return number.zfill(2) if re.fullmatch(r"\d+", number) else number


def clean_title(title: str, series: str | None, number: str | None) -> str:
    """Remove 'Series: ' prefixes and ', Book N' suffixes so the folder name isn't repetitive."""
    t = title.strip()
    if series:
        t = re.sub(r"^" + re.escape(series) + r"\s*[:,\-–]?\s*", "", t, flags=re.I)
    t = re.sub(rf"\s*[:,\-–(]*\s*{_KEY}\s*\d+(?:\.\d+)?\)?\s*$", "", t, flags=re.I)
    t = re.sub(rf"^{_KEY}\s*\d+(?:\.\d+)?\s*[:,\-–]?\s*", "", t, flags=re.I)
    t = t.strip(" ,:-–")
    return t or (series or title.strip())


def build_dest(library: Path, book: Book, cfg: Config) -> Path:
    """Render the configured naming template and ensure the result stays under library."""
    author = sanitize(book.author, "Unknown Author")
    if book.in_series:
        template = cfg.template_series
    elif book.series:
        template = cfg.template_series_no_number
    else:
        template = cfg.template_standalone

    title = clean_title(book.title or "", book.series, book.number)
    rel = template.format(
        author=author,
        series=sanitize(book.series or "", "Unknown Series"),
        number=_TemplateNumber(fmt_number(book.number) if book.number else ""),
        title=sanitize(title, "Untitled"),
    )
    segments = [sanitize(seg) for seg in rel.split("/") if seg.strip()]
    dest = library.joinpath(*segments)
    dest.resolve().relative_to(library.resolve())  # never escape the library
    return dest


def unique_path(directory: Path, name: str) -> Path:
    """Return an unused sibling path, adding a numeric suffix when needed."""
    candidate = directory / name
    n = 2
    while candidate.exists():
        candidate = directory / f"{name} ({n})"
        n += 1
    return candidate


def move_item(src: Path, dest: Path, rename=os.rename) -> None:
    """Move a file or folder; works across disks.

    Same filesystem: an instant rename. Different filesystems: copy to a
    hidden '.partial' name first and rename it into place when complete, so Audiobookshelf
    never sees a half-copied book. The source is removed only after the copy succeeded.
    """
    if dest.exists():
        raise FileExistsError(f"destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        rename(src, dest)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise

    partial = dest.parent / f".{dest.name}.{uuid.uuid4().hex}.partial"
    try:
        if src.is_dir():
            shutil.copytree(src, partial)
        else:
            shutil.copy2(src, partial)
        os.rename(partial, dest)
    except Exception:
        try:
            if partial.is_dir() and not partial.is_symlink():
                shutil.rmtree(partial)
            elif partial.exists() or partial.is_symlink():
                partial.unlink()
        except OSError:
            pass
        raise
    if src.is_dir():
        shutil.rmtree(src)
    else:
        src.unlink()


def place(src: Path, dest: Path) -> None:
    """Move a book folder (or a single audio file, wrapped in a folder) to `dest`."""
    if dest.exists():
        raise FileExistsError(f"destination already exists: {dest}")
    if src.is_dir():
        move_item(src, dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir()
        move_item(src, dest / src.name)
