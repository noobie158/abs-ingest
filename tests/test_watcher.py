from abs_ingest.watcher import Watcher, is_temp, signature

from conftest import make_book_dir


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_watcher(cfg, make_pipeline, clock, stable=60):
    cfg.stable_seconds = stable
    pipe, _, _ = make_pipeline([])
    return Watcher(cfg, pipe, clock=clock), pipe


def test_waits_until_item_has_stopped_changing(cfg, make_pipeline):
    clock = Clock()
    w, _ = make_watcher(cfg, make_pipeline, clock)
    folder = make_book_dir(cfg.inbox, "Some Book 1")

    assert w.ready_items() == []  # first sight
    clock.now += 30
    assert w.ready_items() == []  # not settled long enough
    (folder / "part2.mp3").write_bytes(b"more data arrived")
    clock.now += 40
    assert w.ready_items() == []  # it changed: timer restarts
    clock.now += 61
    assert w.ready_items() == [folder]


def test_partial_sync_files_block_processing(cfg, make_pipeline):
    clock = Clock()
    w, _ = make_watcher(cfg, make_pipeline, clock, stable=0)
    folder = make_book_dir(cfg.inbox, "Some Book 1", files=("a.mp3", ".syncthing.b.mp3.tmp"))
    w.ready_items()
    clock.now += 100
    assert w.ready_items() == []
    (folder / ".syncthing.b.mp3.tmp").unlink()
    w.ready_items()
    clock.now += 100
    assert w.ready_items() == [folder]


def test_hidden_and_non_audio_items_are_ignored(cfg, make_pipeline):
    clock = Clock()
    w, _ = make_watcher(cfg, make_pipeline, clock, stable=0)
    (cfg.inbox / ".stfolder").mkdir()
    (cfg.inbox / "cover.jpg").write_bytes(b"x")
    (cfg.inbox / "notes.txt").write_bytes(b"x")
    w.ready_items()
    clock.now += 10
    assert w.ready_items() == []


def test_dotfiles_inside_a_book_do_not_block(cfg, make_pipeline):
    clock = Clock()
    w, _ = make_watcher(cfg, make_pipeline, clock, stable=0)
    folder = make_book_dir(cfg.inbox, "Some Book 1", files=("a.mp3", ".DS_Store"))
    w.ready_items()
    clock.now += 10
    assert w.ready_items() == [folder]


def test_empty_folder_is_not_ready(cfg, make_pipeline):
    clock = Clock()
    w, _ = make_watcher(cfg, make_pipeline, clock, stable=0)
    (cfg.inbox / "Empty").mkdir()
    w.ready_items()
    clock.now += 10
    assert w.ready_items() == []


def test_tick_processes_and_leaves_inbox_empty(cfg, make_pipeline):
    clock = Clock()
    w, _ = make_watcher(cfg, make_pipeline, clock, stable=0)
    make_book_dir(cfg.inbox, "Some Book 1")
    assert w.tick() == 0
    clock.now += 5
    assert w.tick() == 1
    assert not [p for p in cfg.inbox.iterdir()]
    assert (cfg.review / "Some Book 1").exists()  # no lookup result -> review


def test_recover_returns_unfinished_items_to_inbox(cfg, make_pipeline):
    clock = Clock()
    w, _ = make_watcher(cfg, make_pipeline, clock)
    make_book_dir(cfg.processing, "Half Done Book 2")
    w.recover()
    assert (cfg.inbox / "Half Done Book 2").is_dir()
    assert not list(cfg.processing.iterdir())


def test_temp_detection():
    assert is_temp(".syncthing.x.mp3.tmp") and is_temp("a.part") and is_temp("b.crdownload")
    assert not is_temp("chapter 01.mp3")


def test_signature_counts_only_real_files(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"1234")
    (tmp_path / ".DS_Store").write_bytes(b"zz")
    sig = signature(tmp_path)
    assert sig.files == 1 and sig.size == 4 and not sig.has_temp
