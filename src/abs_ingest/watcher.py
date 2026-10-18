"""Watch the inbox; hand a book over only when it has stopped changing (copy finished)."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, NamedTuple, Optional

from . import organizer
from .config import Config
from .logsetup import log, say
from .parser import AUDIO_EXTS
from .pipeline import Pipeline

_TEMP_SUFFIXES = (".part", ".tmp", ".crdownload", ".partial", ".!sync")


def is_temp(name: str) -> bool:
    """Identify common temporary filenames used while clients copy or sync files."""
    n = name.lower()
    return n.endswith(_TEMP_SUFFIXES) or ".syncthing." in n or n.startswith("~syncthing~")


class Signature(NamedTuple):
    """Stable snapshot fields used to detect whether an inbox item is still changing."""

    files: int
    size: int
    mtime: float
    has_temp: bool


def signature(path: Path) -> Signature:
    """Summarize visible files, total bytes, newest modification, and temp-file presence."""
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    count = size = 0
    mtime = 0.0
    has_temp = False
    for f in files:
        if is_temp(f.name):
            has_temp = True
            continue
        if f.name.startswith("."):  # .DS_Store and friends
            continue
        try:
            st = f.stat()
        except OSError:
            continue  # vanished mid-scan
        count += 1
        size += st.st_size
        mtime = max(mtime, st.st_mtime)
    return Signature(count, size, mtime, has_temp)


class Watcher:
    """Poll the inbox and send items to the pipeline only after they settle."""

    def __init__(self, cfg: Config, pipeline: Pipeline, clock: Callable[[], float] = time.time):
        """Bind the queue configuration, pipeline, and injectable clock for stability checks."""
        self.cfg = cfg
        self.pipeline = pipeline
        self.clock = clock
        self._seen: dict[Path, tuple[Signature, float]] = {}

    def recover(self) -> None:
        """Anything left in processing/ means a previous run died mid-book: retry it."""
        if not self.cfg.processing.is_dir():
            return
        for leftover in sorted(self.cfg.processing.iterdir()):
            target = organizer.unique_path(self.cfg.inbox, leftover.name)
            organizer.move_item(leftover, target)
            say("recover", leftover.name, "found unfinished in processing/, returned to inbox", logging.WARNING)

    def ready_items(self) -> list[Path]:
        """Return non-symlink inbox items whose signatures stayed unchanged long enough."""
        now = self.clock()
        ready: list[Path] = []
        present: set[Path] = set()
        for item in sorted(self.cfg.inbox.iterdir()):
            if item.is_symlink() or item.name.startswith(".") or is_temp(item.name):
                continue
            if item.is_file() and item.suffix.lower() not in AUDIO_EXTS:
                continue
            present.add(item)
            sig = signature(item)
            previous = self._seen.get(item)

            if previous is None:
                say("waiting", item.name, f"new item detected ({sig.files} file(s)), waiting for the copy to finish")
                self._seen[item] = (sig, now)
                continue
            if previous[0] != sig:
                log.debug("[waiting ] %s: still changing", item.name)
                self._seen[item] = (sig, now)
                continue
            if sig.files == 0 or sig.has_temp:
                continue
            if now - previous[1] >= self.cfg.stable_seconds:
                ready.append(item)

        for gone in set(self._seen) - present:
            del self._seen[gone]
        return ready

    def tick(self) -> int:
        """Process one batch of ready items and flush a single pending library scan."""
        ready = self.ready_items()
        for item in ready:
            self._seen.pop(item, None)
            self.pipeline.process(item)
        if ready:
            self.pipeline.flush_scan()
        return len(ready)

    def run(self, stop: Optional[threading.Event] = None) -> None:
        """Recover interrupted work, then poll until interrupted or `stop` is set."""
        self.recover()
        stop = stop or threading.Event()
        say("watcher", "inbox", f"watching {self.cfg.inbox} (poll {self.cfg.poll_seconds:g}s, "
            f"settle {self.cfg.stable_seconds:g}s)")
        while not stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - keep the service alive
                say("watcher", "inbox", f"unexpected error: {type(exc).__name__}: {exc}", logging.ERROR)
                log.debug("watcher traceback", exc_info=True)
            stop.wait(self.cfg.poll_seconds)
