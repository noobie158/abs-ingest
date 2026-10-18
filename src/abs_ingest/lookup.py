"""Decide which lookup result (if any) is really the book we hold.

Pure functions only - no network - so the matching logic is easy to test.
"""

from __future__ import annotations

import difflib
from typing import Optional

from .models import Candidate, ParsedName
from .parser import normalize


def sim(a: str, b: str) -> float:
    """Compare normalized names, rewarding long contained titles for punctuation variants."""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 8 and short in long_:
        ratio = max(ratio, 0.95)
    return ratio


def same_number(a: Optional[str], b: Optional[str]) -> bool:
    """Compare sequence strings numerically so values like `07` and `7` agree."""
    if a is None or b is None:
        return False
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def _identity(c: Candidate) -> tuple[str, str]:
    """Return the normalized title/author pair used to detect tied candidates."""
    return (normalize(c.title), normalize(c.author))


def choose(
    parsed: ParsedName,
    candidates: list[Candidate],
    tag_author: Optional[str] = None,
) -> tuple[Optional[Candidate], float, list[str]]:
    """Return (best candidate, confidence 0..1, reasons it lost points)."""
    if not candidates:
        return None, 0.0, ["lookup returned no results"]

    scored: list[tuple[float, Candidate, list[str]]] = []
    for c in candidates:
        reasons: list[str] = []
        if parsed.number is not None:
            name_sim = max(sim(parsed.base, c.series or ""), sim(parsed.base, c.title))
            num_ok = c.sequence is not None and same_number(parsed.number, c.sequence)
            score = 0.6 * name_sim + (0.4 if num_ok else 0.0)
            if not num_ok:
                reasons.append(
                    f"book number {parsed.number} not confirmed by lookup (got {c.sequence})"
                )
            if parsed.number_source == "bare":
                full = sim(parsed.clean, c.title)
                if full >= 0.9:  # the digits were part of the title ("Catch 22")
                    score, reasons = full, []
                elif not num_ok:
                    score = min(score, 0.6)
        else:
            score = sim(parsed.clean, c.title)
            if score < 0.85:
                reasons.append("title does not closely match the lookup result")

        if tag_author and c.author:
            agreement = sim(tag_author, c.author)
            if agreement >= 0.8:
                score = min(1.0, score + 0.1)
            elif agreement < 0.5:
                score -= 0.2
                reasons.append("author tag in the audio file disagrees with the lookup")
        scored.append((score, c, reasons))

    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best, reasons = scored[0]
    confidence = max(0.0, min(1.0, best_score))

    for other_score, other, _ in scored[1:]:
        if _identity(other) != _identity(best) and best_score - other_score < 0.05:
            confidence = min(confidence, 0.7)
            reasons = reasons + ["several equally good matches - needs a human to pick"]
            break

    return best, round(confidence, 3), reasons
