import json

from abs_ingest.metadata import build_metadata
from abs_ingest.models import Book
from abs_ingest.organizer import build_dest, clean_title, place, sanitize


def test_series_book_path(cfg):
    book = Book(title="The Door", author="Test Author", series="Azarinth Healer", number="7")
    dest = build_dest(cfg.library, book, cfg)
    assert dest == cfg.library / "Test Author" / "Azarinth Healer" / "Book 07 - The Door"


def test_number_format_spec_in_template(cfg):
    cfg.template_series = "{author}/{series}/{number:02d} - {title}"
    book = Book(title="The Door", author="Test Author", series="Azarinth Healer", number="7")
    assert build_dest(cfg.library, book, cfg) == (
        cfg.library / "Test Author" / "Azarinth Healer" / "07 - The Door"
    )


def test_standalone_path(cfg):
    book = Book(title="A Novel", author="Test Author")
    assert build_dest(cfg.library, book, cfg) == cfg.library / "Test Author" / "A Novel"


def test_series_without_number_path(cfg):
    book = Book(title="A Novel", author="Test Author", series="Some Series")
    assert build_dest(cfg.library, book, cfg) == cfg.library / "Test Author" / "Some Series" / "A Novel"


def test_title_repeating_series_and_number_is_cleaned():
    assert clean_title("Azarinth Healer, Book 7", "Azarinth Healer", "7") == "Azarinth Healer"
    assert clean_title("Mistborn: The Final Empire", "Mistborn", "1") == "The Final Empire"
    assert clean_title("The Door (Book 7)", "Azarinth Healer", "7") == "The Door"


def test_illegal_characters_are_removed():
    assert sanitize('What? A "Title": Part/2.') == "What A Title Part2"
    assert sanitize("..", "Unknown") == "Unknown"


def test_cannot_escape_library(cfg):
    book = Book(title="../../etc/passwd", author="../x", series=None)
    dest = build_dest(cfg.library, book, cfg)
    dest.resolve().relative_to(cfg.library.resolve())


def test_place_wraps_single_file(tmp_path):
    f = tmp_path / "Book.m4b"
    f.write_bytes(b"x")
    dest = tmp_path / "lib" / "Author" / "Title"
    place(f, dest)
    assert (dest / "Book.m4b").exists() and not f.exists()


def test_metadata_json_format():
    book = Book(title="The Door", author="Test Author", series="Azarinth Healer", number="7", asin="B0")
    data = build_metadata(book)
    assert data == {
        "title": "The Door",
        "authors": ["Test Author"],
        "series": ["Azarinth Healer #7"],
        "asin": "B0",
    }
    json.dumps(data)
