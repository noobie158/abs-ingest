"""abs-ingest command line: watch | run-once | status | parse | approve | process-matched."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .abs_client import AbsClient
from .aliases import Aliases
from .config import Config, ConfigError, find_config, load
from .logsetup import log, setup
from .parser import parse_name
from .pipeline import Pipeline
from .watcher import Watcher
from .post_mover import process_manually_matched_books

def build_pipeline(cfg: Config, dry_run: bool = False) -> Pipeline:
    """Construct the pipeline and optional ABS search client from configuration."""
    client = None
    if cfg.lookup_enabled:
        client = AbsClient(cfg.abs_url, cfg.abs_token, cfg.abs_provider)  # type: ignore[arg-type]
    return Pipeline(cfg, Aliases(cfg.aliases_file), client=client, dry_run=dry_run)


def banner(cfg: Config, dry_run: bool) -> None:
    """Log the active paths and integration settings before a command runs."""
    log.info("abs-ingest %s%s", __version__, "  [DRY RUN - nothing will be moved]" if dry_run else "")
    log.info("inbox      %s", cfg.inbox)
    log.info("library    %s", cfg.library)
    log.info("lookup     %s", "on (" + cfg.abs_provider + ")" if cfg.lookup_enabled
             else "OFF - set audiobookshelf.url + token; books will go to review/")
    log.info("scan       %s", "on" if cfg.scan_enabled else "off (no library_id)")
    log.info("notify     %s", f"ntfy topic '{cfg.ntfy_topic}'" if cfg.ntfy_topic else "console/log only")
    log.info("auto-file  confidence >= %.2f", cfg.auto_threshold)


def cmd_watch(cfg: Config, args) -> int:
    """Start the continuous inbox watcher until interrupted."""
    cfg.ensure_dirs()
    banner(cfg, args.dry_run)
    pipeline = build_pipeline(cfg, args.dry_run)
    try:
        Watcher(cfg, pipeline).run()
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


def cmd_run_once(cfg: Config, args) -> int:
    """Process the currently ready inbox items once, optionally skipping settle time."""
    cfg.ensure_dirs()
    banner(cfg, args.dry_run)
    cfg.stable_seconds = 0 if args.now else cfg.stable_seconds
    pipeline = build_pipeline(cfg, args.dry_run)
    watcher = Watcher(cfg, pipeline)
    watcher.recover()
    watcher.ready_items()  # first sight of each item
    count = watcher.tick()
    if count == 0:
        log.info("nothing ready in %s (use --now to skip the settle time)", cfg.inbox)
    return 0


def _list(directory: Path) -> list[str]:
    """Return visible item names, excluding hidden sidecars and error reports."""
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir()
                  if not p.name.startswith(".") and not p.name.endswith((".review.json", ".error.txt")))


def cmd_status(cfg: Config, args) -> int:
    """Print queue counts and the most recent warning/error log entries."""
    for label, directory in (("inbox", cfg.inbox), ("processing", cfg.processing),
                             ("review", cfg.review), ("failed", cfg.failed)):
        names = _list(directory)
        print(f"{label:<11}{len(names):>3}  {directory}")
        for n in names[:15]:
            print(f"             - {n}")
        if len(names) > 15:
            print(f"             ... and {len(names) - 15} more")

    log_file = getattr(log, "log_file", cfg.log_file)
    print(f"\nrecent problems (from {log_file}):")
    try:
        lines = Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()
        problems = [ln for ln in lines if " ERROR " in ln or " WARNING " in ln][-args.errors:]
    except OSError:
        problems = []
    print("\n".join(problems) if problems else "  none")
    return 0


def cmd_parse(args) -> int:
    """Show how each supplied filename is split into a base name and sequence."""
    for raw in args.names:
        p = parse_name(raw)
        print(f"{raw}\n    name={p.base!r} number={p.number} ({p.number_source or '-'}) "
              f"collection={p.is_collection}")
    return 0


def cmd_approve(cfg: Config, args) -> int:
    """File one reviewed item using the author/series details supplied by the user."""
    pipeline = build_pipeline(cfg)
    try:
        result = pipeline.approve(args.name, args.author, args.series, args.number,
                                  args.title, remember=not args.no_remember)
    except (OSError, RuntimeError, ValueError) as exc:
        log.error("approval failed: %s", exc)
        return 1
    pipeline.flush_scan()
    return 0 if result.status == "filed" else 1


def cmd_process_matched(cfg: Config, args) -> int:
    """Move ABS-matched items from the review library into the destination library."""
    token = cfg.abs_token
    if not token:
        log.error("Audiobookshelf API token is missing; configure audiobookshelf.token or ABS_TOKEN.")
        return 1
    log.info("Starting post-match processing sequence...")
    try:
        succeeded = process_manually_matched_books(cfg, token)
        if not succeeded:
            return 1
        log.info("Post-match processing completed.")
        return 0
    except Exception as e:
        log.error(f"Error executing post-match mover command: {e}")
        return 1


def main(argv=None) -> int:
    """Parse CLI arguments, load settings, configure logging, and dispatch a command."""
    ap = argparse.ArgumentParser(prog="abs-ingest", description=__doc__)
    ap.add_argument("--config", help="path to config.yaml")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true", help="show debug lines too")
    sub = ap.add_subparsers(dest="command", required=True)

    w = sub.add_parser("watch", help="run continuously (this is the live console)")
    w.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("run-once", help="process whatever is ready in the inbox, then exit")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--now", action="store_true", help="do not wait for the copy to settle")
    s = sub.add_parser("status", help="show folder contents and recent errors")
    s.add_argument("-n", "--errors", type=int, default=10)
    pa = sub.add_parser("parse", help="show how names are understood (no config needed)")
    pa.add_argument("names", nargs="+")
    a = sub.add_parser("approve", help="file an item from review/ with details you supply")
    a.add_argument("name", help="folder/file name inside review/")
    a.add_argument("--author", required=True)
    a.add_argument("--series")
    a.add_argument("--number")
    a.add_argument("--title")
    a.add_argument("--no-remember", action="store_true", help="do not save an alias for the series")

    # Registered command parser for the new match engine
    sub.add_parser("process-matched", help="Scan 04Unsorted for matched audiobooks and move them to 03authors")

    args = ap.parse_args(argv)
    if args.command == "parse":
        return cmd_parse(args)

    try:
        cfg = load(find_config(args.config))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    setup(cfg.log_file, color=False if args.no_color else None, verbose=args.verbose)
    handler = {
        "watch": cmd_watch,
        "run-once": cmd_run_once,
        "status": cmd_status,
        "approve": cmd_approve,
        "process-matched": cmd_process_matched
    }[args.command]

    try:
        return handler(cfg, args)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
