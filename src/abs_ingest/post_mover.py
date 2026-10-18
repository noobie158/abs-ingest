import logging
from pathlib import Path

import requests

from .config import Config
from .models import Book
from .organizer import build_dest, move_item, place
from .permissions import apply, apply_chain

logger = logging.getLogger("abs_ingest.post_mover")


def process_manually_matched_books(config: Config, token: str | None) -> bool:
    """
    List items from the configured review library, move matched review roots using ABS metadata,
    apply library permissions, and scan the destination library. Return False on API or move errors.
    """
    if not config.abs_url:
        logger.error("audiobookshelf.url is not set in the configuration file.")
        return False
    if not token:
        logger.error("Audiobookshelf API token is missing; configure audiobookshelf.token or ABS_TOKEN.")
        return False
    if not config.abs_library_id:
        logger.error("audiobookshelf.library_id is not set in the configuration file.")
        return False
    if not config.abs_review_library_id:
        logger.error("audiobookshelf.review_library_id is not set in the configuration file.")
        return False

    abs_url = config.abs_url.rstrip("/")
    target_library_id = config.abs_library_id
    review_library_id = config.abs_review_library_id
    review_dir = config.review.resolve()
    library_dir = config.library.resolve()

    # Cross-disk safety confirmation: Ensure the backup disk array mount point is active
    if not review_dir.is_dir() or not library_dir.is_dir():
        logger.error(f"Target paths unavailable. Check if mount disk array is online. Review: {review_dir}, Library: {library_dir}")
        return False

    headers = {"Authorization": f"Bearer {token}"}
    api_url = f"{abs_url}/api/libraries/{review_library_id}/items"

    logger.info("Fetching library items from Audiobookshelf API...")
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("results", []) if isinstance(payload, dict) else []
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (401, 403):
            logger.error("Audiobookshelf API authentication failed (HTTP %s); check ABS_TOKEN.", status)
        else:
            logger.error("Failed to query Audiobookshelf library items: %s", exc)
        return False
    except (requests.RequestException, ValueError) as exc:
        logger.error("Failed to query Audiobookshelf library items: %s", exc)
        return False

    moved_count = 0
    failed_count = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        library_files = item.get("libraryFiles", [])
        if not isinstance(library_files, list):
            continue

        for lib_file in library_files:
            if not isinstance(lib_file, dict) or not isinstance(lib_file.get("path"), str):
                continue
            item_path = Path(lib_file["path"]).resolve()
            try:
                relative_path = item_path.relative_to(review_dir)
            except ValueError:
                continue
            if not relative_path.parts:
                continue

            # Move the whole review entry, not just a nested track directory.
            source_path = review_dir / relative_path.parts[0]
            if not source_path.exists():
                continue

            media = item.get("media")
            metadata = media.get("metadata") if isinstance(media, dict) else None
            metadata = metadata if isinstance(metadata, dict) else {}

            title = metadata.get("title")
            author = metadata.get("authorName")
            if not isinstance(title, str) or not isinstance(author, str):
                continue
            title = title.strip()
            author = author.strip()
            if not title or not author or author.lower() in ("unknown", "various"):
                continue

            series = metadata.get("seriesName")
            series = series.strip() if isinstance(series, str) and series.strip() else None
            sequence = metadata.get("sequence")
            number = str(sequence).strip() if sequence not in (None, "") else None
            if number:
                try:
                    numeric_number = float(number)
                    if numeric_number.is_integer():
                        number = str(int(numeric_number))
                except (OverflowError, ValueError):
                    pass

            book = Book(title=title, author=author, series=series, number=number)
            dest_path = build_dest(library_dir, book, config)
            if dest_path.exists() or dest_path.is_symlink():
                logger.warning("Destination path already exists, skipping: %s", dest_path)
                break

            logger.info("Detected match for '%s'. Relocating to permanent library...", source_path.name)
            try:
                place(source_path, dest_path)
                apply(dest_path, config)
                apply_chain(library_dir, dest_path, config)
                moved_count += 1
                logger.info("Successfully processed and moved: %s", dest_path.name)
                break
            except Exception as exc:
                logger.error("Failed to relocate filesystem path %s: %s", source_path, exc)
                failed_count += 1
                if dest_path.exists() and not source_path.exists():
                    try:
                        move_item(dest_path, source_path)
                    except Exception as rollback_exc:
                        logger.critical(
                            "Could not restore %s after post-move failure (%s): %s",
                            source_path,
                            exc,
                            rollback_exc,
                        )
                break

    # Fire an update trigger so Audiobookshelf spots the new paths immediately
    if moved_count > 0:
        logger.info(f"Moved {moved_count} audiobooks. Requesting Audiobookshelf library scan...")
        try:
            scan_url = f"{abs_url}/api/libraries/{target_library_id}/scan"
            scan_res = requests.post(scan_url, headers=headers, timeout=10)
            scan_res.raise_for_status()
            logger.info("Audiobookshelf scanner triggered successfully.")
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (401, 403):
                logger.error("Audiobookshelf scan authentication failed (HTTP %s); check ABS_TOKEN.", status)
            else:
                logger.error("Failed to automatically alert library scan updater: %s", exc)
            return False
        except requests.RequestException as exc:
            logger.error("Failed to automatically alert library scan updater: %s", exc)
            return False
    else:
        if failed_count:
            logger.error("Failed to process %s matched review item(s).", failed_count)
        else:
            logger.info("No newly matched review entries found to process.")
    return failed_count == 0
