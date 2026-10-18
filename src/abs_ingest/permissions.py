"""Make files readable (and writable) for the audiobookshelf group - what set_acls.sh did by hand."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .logsetup import log


def _fix_one(path: Path, cfg: Config) -> None:
    """Apply configured ownership and mode to one non-symlink filesystem entry."""
    if path.is_symlink():
        return
    if cfg.group or (cfg.owner and os.geteuid() == 0):
        owner = cfg.owner if os.geteuid() == 0 else None
        shutil.chown(path, user=owner, group=cfg.group)
    os.chmod(path, cfg.dir_mode if path.is_dir() else cfg.file_mode)


def apply(path: Path, cfg: Config, recursive: bool = True) -> None:
    """Set group + mode (and optional ACL) on a book. Raises on failure so the book is not misfiled."""
    targets = [path]
    if recursive and path.is_dir():
        targets += sorted(path.rglob("*"))
    for t in targets:
        _fix_one(t, cfg)

    if cfg.use_setfacl and cfg.group and shutil.which("setfacl"):
        spec = f"g:{cfg.group}:rwX" + (f",u:{cfg.owner}:rwX" if cfg.owner else "")
        result = subprocess.run(
            ["setfacl", "-R", "-m", spec, str(path)], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"setfacl failed: {result.stderr.strip()}")


def apply_chain(library: Path, dest: Path, cfg: Config) -> None:
    """Fix the new Author/ and Series/ folders created between the library root and the book."""
    for parent in dest.parents:
        if parent == library or library not in parent.parents:
            break
        _fix_one(parent, cfg)
    log.debug("fixed permissions on folders above %s", dest)
