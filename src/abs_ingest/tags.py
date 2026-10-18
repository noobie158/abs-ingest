from __future__ import annotations

from pathlib import Path
from typing import Optional

from .parser import AUDIO_EXTS


def first_audio_file(path: Path) -> Optional[Path]:
    if path.is_file():
        return path if path.suffix.lower() in AUDIO_EXTS else None
        """Return the input audio file or first sorted audio file found beneath a folder."""
    files = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    return files[0] if files else None


def read_tags(path: Path) -> dict:
    """Return {'author', 'title', 'album'} from the first audio file; {} if unreadable."""
    audio = first_audio_file(path)
    if audio is None:
        return {}
    try:
        import mutagen

        tags = mutagen.File(str(audio), easy=True)
    except Exception:
        return {}
    if not tags:
        return {}

    def first(*keys: str) -> str:
        for key in keys:
            value = tags.get(key)
            if value:
                return str(value[0]).strip()
        return ""

    result = {
        "author": first("albumartist", "artist"),
        "title": first("title"),
        "album": first("album"),
    }
    return {k: v for k, v in result.items() if v}
