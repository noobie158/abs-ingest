"""One book from inbox to library (or to review/ failed). Every step is logged."""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import organizer, permissions
from .abs_client import AbsError
from .aliases import Aliases
from .config import Config
from .identify import Searcher, identify
from .logsetup import log, say
from .metadata import write_metadata
from .models import Book, ParsedName
from .notify import Notifier
from .parser import parse_name
from .tags import read_tags


@dataclass
class Result:
    """Outcome for one item, including its final location or failure reason."""

    name: str
    status: str  # filed | review | failed | dry-run
    destination: Optional[Path] = None
    reason: str = ""


class Pipeline:
    """Coordinate one audiobook's parse, identify, file/review, and scan lifecycle."""

    def __init__(
        self,
        cfg: Config,
        aliases: Aliases,
        client: Optional[Searcher] = None,
        notifier: Optional[Notifier] = None,
        dry_run: bool = False,
    ):
        """Store shared services and choose whether processing may change the filesystem."""
        self.cfg = cfg
        self.aliases = aliases
        self.client = client
        self.notifier = notifier or Notifier(cfg)
        self.dry_run = dry_run
        self.scan_pending = False

    # ------------------------------------------------------------------ main entry

    def process(self, item: Path) -> Result:
        """Claim an inbox item, identify it, and file it or route it for review/failure."""
        name = item.name
        stage = "parse"
        work = item
        dest: Optional[Path] = None

        if item.is_symlink() or (item.is_dir() and any(path.is_symlink() for path in item.rglob("*"))):
            reason = "symlink inputs are not supported"
            say("FAILED", name, reason, logging.ERROR)
            return Result(name, "failed", None, reason)

        missing = self.cfg.missing_dirs()
        if missing:  # leave the book untouched in the inbox and shout about it
            reason = "folder missing (is the disk mounted?): " + ", ".join(map(str, missing))
            say("FAILED", name, reason, logging.ERROR)
            return Result(name, "failed", None, reason)

        try:
            parsed = parse_name(name)
            say("found", name, self._describe(parsed))

            if not self.dry_run:
                stage = "claim"
                work = self._claim(item)
                stage = "perms"
                permissions.apply(work, self.cfg)
                say("perms", name, "permissions set")

            stage = "identify"
            tags = read_tags(work)
            book = identify(name, parsed, tags, self.aliases, self.client, self.cfg.auto_threshold)
            say(
                "identify",
                name,
                f"{book.author or '?'} | {book.series or '-'} #{book.number or '-'} | "
                f"'{book.title}' | confidence {book.confidence:.2f} via {book.source}",
            )

            if book.confidence < self.cfg.auto_threshold:
                return self._to_review(work, parsed, book, book.reasons)

            stage = "move"
            dest = organizer.build_dest(self.cfg.library, book, self.cfg)
            if dest.exists():
                return self._to_review(
                    work, parsed, book, book.reasons + [f"destination already exists: {dest}"]
                )

            if self.dry_run:
                say("dry-run", name, f"would file as {dest}")
                return Result(name, "dry-run", dest)

            organizer.place(work, dest)
            work = dest
            say("move", name, f"-> {dest}")

            stage = "metadata"
            write_metadata(dest, book)
            say("metadata", name, "metadata.json written")

            stage = "perms"
            permissions.apply(dest, self.cfg)
            permissions.apply_chain(self.cfg.library, dest, self.cfg)

            self.scan_pending = True
            say("done", name, f"filed as {dest.relative_to(self.cfg.library)}", ok=True)
            self.notifier.send("filed", "Audiobook filed", f"{name} -> {dest.relative_to(self.cfg.library)}")
            return Result(name, "filed", dest)

        except Exception as exc:  # noqa: BLE001 - one bad book must never stop the service
            if dest is not None and dest.exists():
                work = dest
            return self._fail(work, name, stage, exc)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _describe(parsed: ParsedName) -> str:
        """Summarize parsed collection/number information for progress logs."""
        if parsed.is_collection and parsed.number is None:
            return "looks like a collection / box set"
        if parsed.number:
            return f"name '{parsed.base}', book number {parsed.number} ({parsed.number_source})"
        return f"name '{parsed.base}', no book number found"

    def _claim(self, item: Path) -> Path:
        """Move out of the inbox first, so a book is never processed twice."""
        target = organizer.unique_path(self.cfg.processing, item.name)
        organizer.move_item(item, target)
        say("claim", item.name, "moved to processing")
        return target

    def _park(self, work: Path, folder: Path) -> Path:
        """Move an item into a queue folder without overwriting an existing entry."""
        target = organizer.unique_path(folder, work.name)
        organizer.move_item(work, target)
        return target

    def _to_review(self, work: Path, parsed: ParsedName, book: Book, reasons: list[str]) -> Result:
        """Move an uncertain item to review and write a hidden explanation sidecar."""
        name = work.name
        reason = "; ".join(reasons) or "confidence below the auto-file threshold"
        if self.dry_run:
            say("dry-run", name, f"would send to review: {reason}", logging.WARNING)
            return Result(name, "dry-run", None, reason)

        target = self._park(work, self.cfg.review)
        sidecar = target.parent / f".{target.name}.review.json"
        try:
            sidecar.write_text(
                json.dumps(
                    {
                        "item": target.name,
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "parsed": asdict(parsed),
                        "guess": asdict(book),
                        "reasons": reasons,
                        "how_to_fix": f'abs-ingest approve "{target.name}" --author "..." '
                        '--series "..." --number N',
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            permissions.apply(target, self.cfg)
        except Exception as exc:
            try:
                sidecar.unlink(missing_ok=True)
            except OSError:
                pass
            return self._fail(target, name, "review", exc)
        say("review", name, f"needs a human: {reason}", logging.WARNING)
        self.notifier.send("review", "Audiobook needs review", f"{name}: {reason}")
        return Result(name, "review", target, reason)

    def _fail(self, work: Path, name: str, stage: str, exc: Exception) -> Result:
        """Log an exception and preserve the current work item in the failed queue."""
        reason = f"{type(exc).__name__}: {exc}"
        say("FAILED", name, f"step '{stage}' failed - {reason}", logging.ERROR)
        log.debug("traceback for %s:\n%s", name, traceback.format_exc())
        target = None
        try:
            if work.exists() and not self.dry_run:
                target = self._park(work, self.cfg.failed)
                (target.parent / (target.name + ".error.txt")).write_text(
                    f"step: {stage}\nerror: {reason}\n\n{traceback.format_exc()}", encoding="utf-8"
                )
                say("FAILED", name, f"kept in {target}", logging.ERROR)
        except Exception as park_exc:  # noqa: BLE001
            say("FAILED", name, f"could not move to failed/: {park_exc}", logging.ERROR)
        self.notifier.send("failed", "Audiobook ingest failed", f"{name} ({stage}): {reason}")
        return Result(name, "failed", target, reason)

    # ------------------------------------------------------------------ audiobookshelf

    def flush_scan(self) -> None:
        """Ask Audiobookshelf to scan once after a batch of books."""
        if not self.scan_pending or self.dry_run:
            return
        self.scan_pending = False
        if not self.cfg.scan_enabled or not hasattr(self.client, "scan_library"):
            log.warning("[scan    ] library scan not configured - Audiobookshelf will pick the "
                        "books up with its own watcher/scheduled scan")
            return
        try:
            self.client.scan_library(self.cfg.abs_library_id)  # type: ignore[union-attr]
            say("scan", "library", "Audiobookshelf scan triggered", ok=True)
        except AbsError as exc:
            say("scan", "library", str(exc), logging.ERROR)

    # ------------------------------------------------------------------ manual approval

    def approve(
        self,
        item_name: str,
        author: str,
        series: Optional[str] = None,
        number: Optional[str] = None,
        title: Optional[str] = None,
        remember: bool = True,
    ) -> Result:
        """File an item from review/ using details supplied by a human."""
        if item_name in ("", ".", "..") or Path(item_name).name != item_name:
            raise FileNotFoundError(f"{item_name!r} is not a top-level item in {self.cfg.review}")
        item = self.cfg.review / item_name
        if item.is_symlink():
            raise FileNotFoundError(f"{item_name!r} is not a regular item in {self.cfg.review}")
        try:
            item.resolve().relative_to(self.cfg.review.resolve())
        except ValueError as exc:
            raise FileNotFoundError(f"{item_name!r} is not inside {self.cfg.review}") from exc
        if not item.exists():
            raise FileNotFoundError(f"{item_name!r} is not in {self.cfg.review}")

        sidecar = self.cfg.review / f".{item_name}.review.json"
        parsed = parse_name(item_name)
        if sidecar.is_file():
            try:
                parsed = ParsedName(**json.loads(sidecar.read_text(encoding="utf-8"))["parsed"])
            except (KeyError, TypeError, ValueError):
                pass

        book = Book(
            title=title or (f"{series}, Book {number}" if series and number else parsed.base),
            author=author,
            series=series,
            number=number,
            confidence=1.0,
            source="human",
        )
        dest = organizer.build_dest(self.cfg.library, book, self.cfg)
        if dest.exists():
            raise FileExistsError(f"destination already exists: {dest}")

        try:
            organizer.place(item, dest)
            write_metadata(dest, book)
            permissions.apply(dest, self.cfg)
            permissions.apply_chain(self.cfg.library, dest, self.cfg)
            if remember and series:
                self.aliases.add(parsed.base, author, series)
        except Exception as exc:
            if dest.exists() and not item.exists():
                try:
                    organizer.move_item(dest, item)
                except Exception as rollback_exc:
                    log.error("could not restore %s after approval failure: %s", item, rollback_exc)
            raise
        if sidecar.is_file():
            try:
                sidecar.unlink()
            except OSError as exc:
                log.warning("could not remove review sidecar %s: %s", sidecar, exc)
        if remember and series:
            say("identify", item_name, f"remembered '{parsed.base}' -> {author} / {series}")
        self.scan_pending = True
        say("done", item_name, f"filed as {dest.relative_to(self.cfg.library)}", ok=True)
        return Result(item_name, "filed", dest)
