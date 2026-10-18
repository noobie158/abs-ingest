"""Work out author / series / number / title for one item."""

from __future__ import annotations

import logging
from typing import Optional, Protocol

from .abs_client import AbsError
from .aliases import Aliases
from .logsetup import say
from .lookup import choose
from .models import Book, Candidate, ParsedName


class Searcher(Protocol):
    """Interface required by the identification flow for metadata lookup."""

    def search_books(self, title: str, author: Optional[str] = None) -> list[Candidate]: ...


def fallback_title(parsed: ParsedName, series: Optional[str], number: Optional[str]) -> str:
    """Build a readable title from parsed name parts when lookup has no title."""
    if series and number:
        return f"{series}, Book {number}"
    return parsed.base or parsed.clean


def gather_candidates(
    name: str, parsed: ParsedName, client: Searcher, tag_author: Optional[str]
) -> list[Candidate]:
    """Search by the cleaned name and by 'name book N'; merge and de-duplicate."""
    queries = [parsed.base]
    if parsed.number is not None:
        queries.append(f"{parsed.base} book {parsed.number}")
    if parsed.clean != parsed.base:
        queries.append(parsed.clean)

    seen: set = set()
    found: list[Candidate] = []
    for q in dict.fromkeys(queries):  # unique, ordered
        for c in client.search_books(q, tag_author):
            key = c.asin or (c.title.lower(), c.author.lower())
            if key not in seen:
                seen.add(key)
                found.append(c)
    say("lookup", name, f"{len(found)} candidate(s) from lookup", logging.DEBUG)
    return found


def identify(
    name: str,
    parsed: ParsedName,
    tags: dict,
    aliases: Aliases,
    client: Optional[Searcher],
    threshold: float,
) -> Book:
    """Combine aliases, lookup candidates, and tags into a confidence-scored book."""
    tag_author = tags.get("author")

    if parsed.is_collection and parsed.number is None:
        return Book(
            title=parsed.clean,
            confidence=0.0,
            reasons=["looks like a collection / box set - needs a human to split or file it"],
            source="none",
        )

    candidates: list[Candidate] = []
    lookup_error: Optional[str] = None
    if client is not None:
        try:
            candidates = gather_candidates(name, parsed, client, tag_author)
        except AbsError as exc:
            lookup_error = str(exc)
            say("lookup", name, lookup_error, logging.ERROR)

    best, confidence, reasons = choose(parsed, candidates, tag_author) if candidates else (None, 0.0, [])
    best_missing_author = best is not None and not best.author.strip()

    # 1. a correction a human made earlier wins for author + series
    alias = aliases.get(parsed.base) if parsed.number is not None else None
    if alias:
        title = ""
        if best and confidence >= threshold:
            title = best.title
        say("identify", name, f"known series '{alias['series']}' from aliases", ok=True)
        return Book(
            title=title or fallback_title(parsed, alias["series"], parsed.number),
            author=alias["author"],
            series=alias["series"],
            number=parsed.number,
            asin=best.asin if best and confidence >= threshold else None,
            confidence=0.95,
            source="alias",
        )

    # 2. online lookup
    if best is not None and not best_missing_author:
        return Book(
            title=best.title,
            author=best.author,
            series=best.series,
            number=best.sequence or parsed.number,
            asin=best.asin,
            confidence=confidence,
            reasons=reasons,
            source="lookup",
        )

    # 3. nothing certain: best guess from embedded tags, always below the auto threshold
    why = [lookup_error] if lookup_error else []
    if client is None:
        why.append("online lookup is not configured (set audiobookshelf.url and token)")
    elif not lookup_error:
        why.append("lookup result did not include an author" if best_missing_author else "lookup returned no results")

    if tag_author:
        series = parsed.base if parsed.number is not None else None
        return Book(
            title=tags.get("title") or fallback_title(parsed, series, parsed.number),
            author=tag_author,
            series=series,
            number=parsed.number,
            confidence=min(0.6, threshold - 0.01),
            reasons=why + ["only the author tag was available"],
            source="tags",
        )

    return Book(
        title=parsed.base or parsed.clean,
        series=parsed.base if parsed.number is not None else None,
        number=parsed.number,
        confidence=0.0,
        reasons=why + ["no author found in tags, aliases or lookup"],
        source="none",
    )
