from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_TEMPLATE_SERIES = "{author}/{series}/Book {number} - {title}"
DEFAULT_TEMPLATE_SERIES_NO_NUMBER = "{author}/{series}/{title}"
DEFAULT_TEMPLATE_STANDALONE = "{author}/{title}"

CONFIG_SEARCH = ("config.yaml", "/etc/abs-ingest/config.yaml")


class ConfigError(Exception):
    """Raised when configuration is missing, malformed, or unsafe to use."""

    pass


@dataclass
class Config:
    """Resolved application settings, including paths, permissions, and ABS options."""

    root: Path
    inbox: Path
    processing: Path
    review: Path
    failed: Path
    library: Path
    owner: Optional[str] = None
    group: Optional[str] = None
    dir_mode: int = 0o2775
    file_mode: int = 0o664
    use_setfacl: bool = False
    poll_seconds: float = 10.0
    stable_seconds: float = 60.0
    auto_threshold: float = 0.85
    template_series: str = DEFAULT_TEMPLATE_SERIES
    template_series_no_number: str = DEFAULT_TEMPLATE_SERIES_NO_NUMBER
    template_standalone: str = DEFAULT_TEMPLATE_STANDALONE
    abs_url: Optional[str] = None
    abs_token: Optional[str] = None
    abs_library_id: Optional[str] = None
    abs_review_library_id: Optional[str] = None
    abs_provider: str = "audible"
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: Optional[str] = None
    notify_on: tuple = ("review", "failed")
    log_file: Path = Path("/var/log/abs-ingest/ingest.log")
    aliases_file: Path = Path("aliases.yaml")

    @property
    def lookup_enabled(self) -> bool:
        """Whether ABS search can run with the configured URL and token."""
        return bool(self.abs_url and self.abs_token)

    @property
    def scan_enabled(self) -> bool:
        """Whether automatic ABS library scans have all required settings."""
        return bool(self.abs_url and self.abs_token and self.abs_library_id)

    def missing_dirs(self) -> list[Path]:
        """Library and review live on the big disk and are never created automatically:
        if that disk is not mounted, creating them would silently fill the system disk."""
        return [d for d in (self.library, self.review) if not d.is_dir()]

    def ensure_dirs(self) -> None:
        """Require mounted library paths, then create only local working directories."""
        missing = self.missing_dirs()
        if missing:
            raise ConfigError(
                "folder(s) do not exist (is the disk mounted?): " + ", ".join(map(str, missing))
            )
        for d in (self.inbox, self.processing, self.failed):
            d.mkdir(parents=True, exist_ok=True)


def _mode(value, default: int) -> int:
    """Parse a permission mode written in octal, using `default` when omitted."""
    if value is None:
        return default
    try:
        return int(str(value), 8)
    except ValueError as exc:
        raise ConfigError(f"invalid file mode {value!r} (use octal like 2775)") from exc


def find_config(explicit: Optional[str]) -> Path:
    """Find the requested config file or search the documented default locations."""
    candidates = []
    if explicit:
        candidates.append(explicit)
    elif os.environ.get("ABS_INGEST_CONFIG"):
        candidates.append(os.environ["ABS_INGEST_CONFIG"])
    else:
        candidates.extend(CONFIG_SEARCH)
    for c in candidates:
        if Path(c).is_file():
            return Path(c)
    raise ConfigError(
        "no config file found (tried: " + ", ".join(candidates) + "). "
        "Copy config.example.yaml and pass --config."
    )


def load(path: Path) -> Config:
    """Parse YAML and resolve defaults into a validated `Config` instance."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: configuration must be a YAML mapping")

    paths = raw.get("paths") or {}
    if "root" not in paths and "library" not in paths:
        raise ConfigError(f"{path}: paths.root is required")
    root = Path(paths["root"]) if "root" in paths else Path(paths["library"]).parent

    def p(key: str, default: str) -> Path:
        """Resolve a configured path or its location beneath the root directory."""
        return Path(paths.get(key) or root / default)

    perms = raw.get("permissions") or {}
    watch = raw.get("watch") or {}
    ident = raw.get("identify") or {}
    names = raw.get("naming") or {}
    abs_ = raw.get("audiobookshelf") or {}
    notify = raw.get("notify") or {}
    logging_ = raw.get("logging") or {}

    try:
        auto_threshold = float(ident.get("auto_threshold", 0.85))
    except (TypeError, ValueError) as exc:
        raise ConfigError("identify.auto_threshold must be a finite number from 0 to 1") from exc
    if not math.isfinite(auto_threshold) or not 0 <= auto_threshold <= 1:
        raise ConfigError("identify.auto_threshold must be a finite number from 0 to 1")

    token = abs_.get("token") or os.environ.get(abs_.get("token_env", "ABS_TOKEN"))

    cfg = Config(
        root=root,
        inbox=p("inbox", "inbox"),
        processing=p("processing", "processing"),
        review=p("review", "review"),
        failed=p("failed", "failed"),
        library=p("library", "library"),
        owner=perms.get("owner"),
        group=perms.get("group"),
        dir_mode=_mode(perms.get("dir_mode"), 0o2775),
        file_mode=_mode(perms.get("file_mode"), 0o664),
        use_setfacl=bool(perms.get("use_setfacl", False)),
        poll_seconds=float(watch.get("poll_seconds", 10)),
        stable_seconds=float(watch.get("stable_seconds", 60)),
        auto_threshold=auto_threshold,
        template_series=names.get("series", DEFAULT_TEMPLATE_SERIES),
        template_series_no_number=names.get(
            "series_no_number", DEFAULT_TEMPLATE_SERIES_NO_NUMBER
        ),
        template_standalone=names.get("standalone", DEFAULT_TEMPLATE_STANDALONE),
        abs_url=abs_.get("url"),
        abs_token=token,
        abs_library_id=abs_.get("library_id"),
        abs_review_library_id=abs_.get("review_library_id"),
        abs_provider=abs_.get("provider", "audible"),
        ntfy_server=notify.get("ntfy_server", "https://ntfy.sh"),
        ntfy_topic=notify.get("ntfy_topic"),
        # YAML 1.1 reads a bare `on:` key as boolean True, so accept that spelling too
        notify_on=tuple(
            notify.get("events", notify.get("on", notify.get(True, ["review", "failed"])))
        ),
        log_file=Path(logging_.get("file", "/var/log/abs-ingest/ingest.log")),
        aliases_file=Path(raw.get("aliases_file", root / "aliases.yaml")),
    )
    return cfg
