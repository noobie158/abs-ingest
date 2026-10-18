import pytest

from abs_ingest.config import ConfigError, load


def test_minimal_config_gets_defaults(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(f"paths:\n  root: {tmp_path}/books\n")
    cfg = load(f)
    assert cfg.inbox == tmp_path / "books" / "inbox"
    assert cfg.library == tmp_path / "books" / "library"
    assert cfg.dir_mode == 0o2775 and cfg.file_mode == 0o664
    assert not cfg.lookup_enabled and not cfg.scan_enabled


def test_only_library_given(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(f"paths:\n  library: {tmp_path}/books/library\n")
    assert load(f).root == tmp_path / "books"


def test_full_config(tmp_path, monkeypatch):
    f = tmp_path / "config.yaml"
    f.write_text(
        f"""
paths: {{root: {tmp_path}}}
permissions: {{group: audiobookshelf, dir_mode: "2770", file_mode: "660"}}
audiobookshelf: {{url: "http://x:1", library_id: L1, review_library_id: R1, token: tok}}
notify: {{ntfy_topic: mytopic, events: [failed]}}
identify: {{auto_threshold: 0.9}}
"""
    )
    cfg = load(f)
    assert cfg.dir_mode == 0o2770 and cfg.file_mode == 0o660
    assert cfg.lookup_enabled and cfg.scan_enabled
    assert cfg.abs_library_id == "L1" and cfg.abs_review_library_id == "R1"
    assert cfg.ntfy_topic == "mytopic" and cfg.notify_on == ("failed",)
    assert cfg.auto_threshold == 0.9


def test_bare_on_key_is_still_understood(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(f"paths: {{root: {tmp_path}}}\nnotify:\n  on: [filed]\n")
    assert load(f).notify_on == ("filed",)


def test_example_config_loads(tmp_path):
    from pathlib import Path

    example = Path(__file__).parent.parent / "config.example.yaml"
    cfg = load(example)
    assert cfg.notify_on == ("review", "failed")
    assert cfg.group == "audiobookshelf" and cfg.dir_mode == 0o2775
    assert cfg.template_series == "{author}/{series}/Book {number} - {title}"


def test_missing_root_is_a_clear_error(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("watch: {poll_seconds: 5}\n")
    with pytest.raises(ConfigError):
        load(f)


def test_non_mapping_config_root_is_a_clear_error(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("- not a mapping\n")
    with pytest.raises(ConfigError, match="YAML mapping"):
        load(f)


@pytest.mark.parametrize("threshold", [".nan", ".inf", "-0.1", "1.1", "not-a-number"])
def test_invalid_auto_threshold_is_rejected(tmp_path, threshold):
    f = tmp_path / "config.yaml"
    f.write_text(f"paths: {{root: {tmp_path}}}\nidentify: {{auto_threshold: {threshold}}}\n")
    with pytest.raises(ConfigError, match="auto_threshold"):
        load(f)
