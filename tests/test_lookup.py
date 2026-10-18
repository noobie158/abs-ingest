from abs_ingest.abs_client import parse_result
from abs_ingest.lookup import choose
from abs_ingest.parser import parse_name

from conftest import cand


def test_parse_result_list_series():
    c = parse_result(
        {"title": "T", "author": "A", "series": [{"series": "S", "sequence": "3"}], "asin": "B1"}
    )
    assert (c.series, c.sequence, c.asin) == ("S", "3", "B1")


def test_parse_result_string_series():
    c = parse_result({"title": "T", "author": "A", "series": "My Series #4"})
    assert (c.series, c.sequence) == ("My Series", "4")


def test_parse_result_no_series():
    c = parse_result({"title": "T", "author": ["A", "B"]})
    assert c.series is None and c.author == "A, B"


def test_good_series_match_is_confident():
    parsed = parse_name("Azarinth Healer, Book 7")
    best, conf, reasons = choose(parsed, [cand("The Door", series="Azarinth Healer", sequence="7")])
    assert best.title == "The Door"
    assert conf >= 0.85 and not reasons


def test_wrong_number_is_not_confident():
    parsed = parse_name("Azarinth Healer, Book 7")
    _, conf, reasons = choose(parsed, [cand("The Door", series="Azarinth Healer", sequence="6")])
    assert conf < 0.85
    assert any("book number" in r for r in reasons)


def test_picks_the_right_number_out_of_a_series():
    parsed = parse_name("Azarinth Healer, Book 7")
    cands = [
        cand("One", series="Azarinth Healer", sequence="1"),
        cand("Seven", series="Azarinth Healer", sequence="7"),
    ]
    best, conf, _ = choose(parsed, cands)
    assert best.title == "Seven" and conf >= 0.85


def test_two_different_books_equally_good_needs_a_human():
    parsed = parse_name("Azarinth Healer, Book 7")
    cands = [
        cand("Seven A", author="Author One", series="Azarinth Healer", sequence="7"),
        cand("Seven B", author="Author Two", series="Azarinth Healer", sequence="7"),
    ]
    _, conf, reasons = choose(parsed, cands)
    assert conf <= 0.7
    assert any("equally good" in r for r in reasons)


def test_bare_number_unconfirmed_is_capped():
    parsed = parse_name("The Stubborn Skill-Grinder in a Time Loop 5")
    _, conf, _ = choose(parsed, [cand("Other", series="The Stubborn Skill-Grinder in a Time Loop", sequence="1")])
    assert conf <= 0.6


def test_number_that_belongs_to_the_title():
    parsed = parse_name("Catch 22")
    best, conf, _ = choose(parsed, [cand("Catch 22")])
    assert best.title == "Catch 22" and conf >= 0.85


def test_author_tag_disagreement_lowers_confidence():
    parsed = parse_name("Azarinth Healer, Book 7")
    c = cand("The Door", author="Author One", series="Azarinth Healer", sequence="7")
    _, agree, _ = choose(parsed, [c], tag_author="Author One")
    _, clash, reasons = choose(parsed, [c], tag_author="Someone Else Entirely")
    assert agree > clash
    assert any("author tag" in r for r in reasons)


def test_no_candidates():
    best, conf, reasons = choose(parse_name("X, Book 1"), [])
    assert best is None and conf == 0.0 and reasons
