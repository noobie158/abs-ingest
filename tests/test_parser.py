import pytest

from abs_ingest.parser import parse_name

# The real names from the project brief.
CASES = [
    (
        "All Jobs and Classes! I Just Wanted One Skill, Not Them All!, Book 4",
        "All Jobs and Classes! I Just Wanted One Skill, Not Them All!",
        "4",
        "explicit",
    ),
    ("Azarinth Healer, Book 7", "Azarinth Healer", "7", "explicit"),
    ("Backstreet Evolutionist Book 5", "Backstreet Evolutionist", "5", "explicit"),
    ("Book 6 Nameless Sovereign", "Nameless Sovereign", "6", "explicit"),
    (
        "The Stubborn Skill-Grinder in a Time Loop 5",
        "The Stubborn Skill-Grinder in a Time Loop",
        "5",
        "bare",
    ),
]


@pytest.mark.parametrize("raw,base,number,source", CASES)
def test_real_names(raw, base, number, source):
    p = parse_name(raw)
    assert p.base == base
    assert p.number == number
    assert p.number_source == source
    assert not p.is_collection


def test_collection_has_no_number():
    p = parse_name("Chaos Walking Complete Chronological Collection")
    assert p.is_collection
    assert p.number is None


def test_noise_is_removed():
    p = parse_name("Azarinth_Healer, Book 7 (Unabridged) [320kbps]")
    assert p.base == "Azarinth Healer"
    assert p.number == "7"


def test_single_file_extension_is_ignored():
    p = parse_name("Azarinth Healer, Book 7.m4b")
    assert p.base == "Azarinth Healer"
    assert p.number == "7"


def test_big_trailing_number_is_not_a_book_number():
    p = parse_name("Fahrenheit 451")
    assert p.number is None
    assert p.base == "Fahrenheit 451"


def test_word_ending_in_book_is_not_a_keyword():
    p = parse_name("Handbook 5")
    assert p.base == "Handbook"  # bare number, but the word 'Handbook' stays whole
    assert p.number_source == "bare"


def test_decimal_numbers():
    p = parse_name("Some Series, Book 4.5")
    assert p.number == "4.5"
    assert p.base == "Some Series"


def test_no_number_at_all():
    p = parse_name("A Standalone Novel")
    assert p.number is None
    assert p.base == "A Standalone Novel"
