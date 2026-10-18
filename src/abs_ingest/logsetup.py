from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

RESET = "\033[0m"
COLORS = {
    logging.DEBUG: "\033[90m",
    logging.INFO: "",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[1;31m",
    logging.CRITICAL: "\033[1;37;41m",
}
GREEN = "\033[32m"

log = logging.getLogger("abs_ingest")


class ConsoleFormatter(logging.Formatter):
    """Format log records consistently, optionally adding terminal colors."""

    def __init__(self, color: bool):
        """Set the base timestamped format and whether ANSI colors are enabled."""
        super().__init__("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        """Format one record and color it according to level or success status."""
        text = super().format(record)
        if not self.color:
            return text
        colour = GREEN if getattr(record, "ok", False) else COLORS.get(record.levelno, "")
        return f"{colour}{text}{RESET}" if colour else text


def setup(
    log_file: Optional[Path], color: Optional[bool] = None, verbose: bool = False
) -> logging.Logger:
    """Console (coloured, live) plus rotating log file with full detail."""
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.propagate = False

    if color is None:
        color = sys.stdout.isatty()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(ConsoleFormatter(color))
    log.addHandler(console)

    if log_file is not None:
        for target in (Path(log_file), Path.home() / ".local/state/abs-ingest/ingest.log"):
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.handlers.RotatingFileHandler(
                    target, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
                )
            except OSError as exc:
                log.warning("cannot write log file %s: %s", target, exc)
                continue
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
            )
            log.addHandler(handler)
            log.log_file = target  # type: ignore[attr-defined]
            if target != Path(log_file):
                log.warning("using fallback log file %s", target)
            break
    return log


def say(stage: str, name: str, msg: str, level: int = logging.INFO, ok: bool = False) -> None:
    """One consistent line per step: [stage] book name: message."""
    log.log(level, "[%-8s] %s: %s", stage, name, msg, extra={"ok": ok})
