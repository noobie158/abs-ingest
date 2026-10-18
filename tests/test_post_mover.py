from types import SimpleNamespace

import requests

from abs_ingest.cli import cmd_process_matched
from abs_ingest.post_mover import process_manually_matched_books


class Response:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_process_matched_moves_review_root_for_nested_library_file(cfg, monkeypatch):
    cfg.abs_review_library_id = "review-lib"
    book_folder = cfg.review / "Review entry" / "Disc 1"
    book_folder.mkdir(parents=True)
    audio_file = book_folder / "01.mp3"
    audio_file.write_bytes(b"audio")
    calls = []

    def get(url, **kwargs):
        calls.append(("get", url))
        return Response({
            "results": [{
                "libraryFiles": [{"path": str(audio_file)}],
                "media": {"metadata": {
                    "title": "The Door",
                    "authorName": "Test Author",
                    "seriesName": "Azarinth Healer",
                    "sequence": "7",
                }},
            }]
        })

    def post(url, **kwargs):
        calls.append(("post", url))
        return Response()

    monkeypatch.setattr("abs_ingest.post_mover.requests.get", get)
    monkeypatch.setattr("abs_ingest.post_mover.requests.post", post)

    assert process_manually_matched_books(cfg, cfg.abs_token)
    destination = cfg.library / "Test Author" / "Azarinth Healer" / "Book 07 - The Door"
    assert (destination / "Disc 1" / "01.mp3").read_bytes() == b"audio"
    assert not (cfg.review / "Review entry").exists()
    assert calls[0][1].endswith("/api/libraries/review-lib/items")
    assert calls[-1][1].endswith("/api/libraries/lib1/scan")


def test_process_matched_wraps_loose_audio_file(cfg, monkeypatch):
    cfg.abs_review_library_id = "review-lib"
    audio_file = cfg.review / "Loose.m4b"
    audio_file.write_bytes(b"audio")
    payload = {
        "results": [{
            "libraryFiles": [{"path": str(audio_file)}],
            "media": {"metadata": {"title": "The Door", "authorName": "Test Author"}},
        }]
    }
    monkeypatch.setattr("abs_ingest.post_mover.requests.get", lambda *args, **kwargs: Response(payload))
    monkeypatch.setattr("abs_ingest.post_mover.requests.post", lambda *args, **kwargs: Response())

    assert process_manually_matched_books(cfg, cfg.abs_token)
    destination = cfg.library / "Test Author" / "The Door"
    assert (destination / "Loose.m4b").read_bytes() == b"audio"
    assert not audio_file.exists()


def test_process_matched_rolls_back_after_permission_failure(cfg, monkeypatch):
    cfg.abs_review_library_id = "review-lib"
    audio_file = cfg.review / "Loose.m4b"
    audio_file.write_bytes(b"audio")
    payload = {
        "results": [{
            "libraryFiles": [{"path": str(audio_file)}],
            "media": {"metadata": {"title": "The Door", "authorName": "Test Author"}},
        }]
    }
    monkeypatch.setattr("abs_ingest.post_mover.requests.get", lambda *args, **kwargs: Response(payload))
    monkeypatch.setattr("abs_ingest.post_mover.apply", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("chmod denied")))

    assert not process_manually_matched_books(cfg, cfg.abs_token)
    assert audio_file.read_bytes() == b"audio"
    assert not (cfg.library / "Test Author" / "The Door" / "Loose.m4b").exists()


def test_process_matched_reports_authentication_failure(cfg, monkeypatch, caplog):
    cfg.abs_review_library_id = "review-lib"
    error = requests.HTTPError("Unauthorized", response=SimpleNamespace(status_code=401))

    def get(*args, **kwargs):
        raise error

    monkeypatch.setattr("abs_ingest.post_mover.requests.get", get)

    assert not process_manually_matched_books(cfg, cfg.abs_token)
    assert "authentication failed (HTTP 401)" in caplog.text
    assert "ABS_TOKEN" in caplog.text


def test_process_matched_cli_rejects_missing_token(cfg):
    cfg.abs_token = None
    assert cmd_process_matched(cfg, SimpleNamespace()) == 1