# Audiobookshelf Ingest Automation

## 1. Project goal

Automate ingestion of new audiobooks into the Audiobookshelf (ABS) library with as little human intervention as possible.

**Today (manual):**
1. Copy book from Windows PC to the Ubuntu server
2. Fix owner / permissions / ACLs on every file and folder
3. Move to a temporary folder ABS can read
4. Create/edit a metadata config file so ABS matches the correct book
5. Move to the final location: `Author/Series/Book Title + Book Number`

**Target:** drop a book on the PC -> it appears correctly matched and filed in ABS. Humans only handle exceptions.

---

## 2. Pipeline overview

```
Windows PC                      Ubuntu server
-----------                     -------------------------------------------------
[Drop folder] --sync--> [inbox/] -> stabilize -> permissions -> identify
                                                                   |
                                          +------- low confidence -+-> [review/]
                                          v
                              write metadata.json -> move to library
                              (Author/Series/Title) -> ABS scan + match (API)
                                                                   |
                                                       notify (success / needs review)
```

| Stage | What it does | Suggested tool |
|---|---|---|
| 1. Transfer | PC -> server, automatically | Syncthing (or rsync/SMB share) |
| 2. Watch | Detect new book folders | systemd `.path` unit or Python `watchdog` |
| 3. Stabilize | Wait until copy is finished (no size change for N seconds) | Python |
| 4. Permissions | Set owner, mode, ACLs | `chown`, `chmod`, `setfacl` |
| 5. Identify | Parse folder/file names + audio tags, look up book/series/number | `mutagen` / `ffprobe` + Audible/Open Library lookup |
| 6. Metadata | Write `metadata.json` next to the audio files | Python |
| 7. File | Move to `Author/Series/<Title + number>` | Python (`shutil.move`) |
| 8. ABS sync | Trigger library scan, optionally run match via API | ABS REST API |
| 9. Report | Log + notification, route failures to `review/` | log file, ntfy/Telegram/email |

---

## 3a. Example folders

| Role | Path |
|---|---|
| Inbox (sync/share drop location) | `/srv/audiobooks/inbox` |
| Review (items awaiting a human match) | `/srv/audiobooks/review` |
| Final library | `/srv/audiobooks/library` |
| Working folders | `/srv/audiobooks/processing`, `/srv/audiobooks/failed` |

Copy `config.example.yaml` and adjust it for your storage mounts and ABS library IDs. A local
`deploy/config.tom.yaml` may be used for machine-specific settings, but is excluded from Git.

* Confident matches go to the final library; uncertain items go to the review library with a hidden
  `.<name>.review.json` sidecar explaining why they need attention.
* Cross-filesystem moves copy to a unique hidden partial path and rename it into place only when
  complete. The source is removed only after the copy succeeds.
* Review and library directories must already exist. This helps avoid silently writing to an
  unmounted storage path.

## 3. Directory layout on the server

```
/srv/audiobooks/
├── inbox/        # sync target; nothing is processed until stable
├── processing/   # working area while a book is being handled
├── review/       # low-confidence matches, waiting for a human
├── failed/       # errors, with a log file beside each book
└── library/      # ABS library root
    └── Author/
        └── Series/
            └── Series 01 - Book Title/
                ├── *.m4b / *.mp3
                ├── cover.jpg
                └── metadata.json
```

Make the permissions problem go away at the source: give `inbox/` and `library/` **default ACLs** (`setfacl -d -m ...`) so new files inherit the right owner/group access for the sync user, the ingest service, and the ABS user, instead of fixing each file by hand.

---

## 4. Repository layout

```
abs-ingest/
├── README.md
├── config.example.yaml        # paths, ABS URL, library id, naming template
├── pyproject.toml
├── src/abs_ingest/
│   ├── cli.py                 # watch | run-once | status | parse | approve
│   ├── watcher.py             # polls inbox, waits until a copy has finished
│   ├── pipeline.py            # one book: claim -> permissions -> identify -> file / review / failed
│   ├── parser.py              # book number + clean name out of messy names
│   ├── tags.py                # author from embedded audio tags (mutagen)
│   ├── abs_client.py          # Audiobookshelf API: book search, library scan
│   ├── lookup.py              # picks the right search result, confidence score
│   ├── aliases.py             # remembered corrections (series -> author)
│   ├── identify.py            # combines aliases, lookup and tags
│   ├── organizer.py           # naming templates, safe paths, move into library
│   ├── metadata.py            # writes metadata.json
│   ├── permissions.py         # group, mode, optional setfacl
│   ├── notify.py              # optional ntfy phone push
│   ├── logsetup.py            # coloured live console + rotating log file
│   ├── config.py, models.py
├── tests/                     # 65 tests
├── deploy/
│   ├── abs-ingest.service     # systemd service
│   ├── setup-acls.sh          # one-time folder / ACL setup (replaces set_acls.sh)
│   ├── config.tom.yaml        # ready-made config for your folders
│   └── syncthing-notes.md     # Windows -> server transfer options
└── docs/
    └── naming-rules.md
```

---

## 5. Key design decisions

- **Naming template is configurable**, e.g. `{author}/{series}/{series} {number:02d} - {title}`, with a fallback for standalone books: `{author}/{title}`.
- **Confidence score**: if author, title and series/number all agree across tags, filename and online lookup, the book is auto-filed; otherwise it goes to `review/`. This is what keeps wrong matches out of the library.
- **Idempotent and safe**: never delete originals until the move succeeds; keep a per-book log; dry-run mode (`--dry-run`) that only prints what would happen.
- **Secrets** (ABS API token) in environment variables or a root-only file, not in the repo.

---

## 6. Phases

1. **Foundation**: directory structure, ACLs, Syncthing from PC to `inbox/`.
2. **Mover MVP**: watcher + stability check + permissions + move using folder-name parsing only.
3. **Metadata**: tag reading, online lookup, `metadata.json`, confidence scoring and `review/`.
4. **ABS integration**: API scan after each ingest, optional automatic match.
5. **Polish**: notifications, a small review helper (CLI or script to approve/correct items), tests, docs.

---

## 7. Confirmed facts

- Input: both MP3 folders and single `.m4b` files.
- ABS runs natively as user `audiobookshelf`; staging owner is `tom`, shared group `audiobookshelf`.
- Input names are **not consistent** and usually contain **no author**. Real examples:
  - `All Jobs and Classes! I Just Wanted One Skill, Not Them All!, Book 4`
  - `Azarinth Healer, Book 7`
  - `Backstreet Evolutionist Book 5`
  - `Book 6 Nameless Sovereign`
  - `Chaos Walking Complete Chronological Collection`
  - `The Stubborn Skill-Grinder in a Time Loop 5`

## 8. Identification strategy (because names are messy)

Filename parsing alone is not enough; the author is usually missing, so the author and series must come from a lookup.

1. **Extract a book number and a clean title** with an ordered list of patterns:
   `, Book N` / ` Book N` at the end, `Book N ` at the start, and a bare trailing number (`... Loop 5`).
   Strip noise such as `(unabridged)`, bitrates and brackets.
2. **Read embedded tags** (m4b/mp3: author, album, series) when present; they are the strongest signal.
3. **Look up title (+ number) online** (Audible catalog, or ABS's own match search) to get author, series name, series number.
4. **Score confidence**: lookup result agrees with the extracted number/title -> auto-file; disagreement or several candidates -> `review/`.
5. **Box sets and collections** (e.g. `Chaos Walking Complete Chronological Collection`) have no single book number: always send to `review/`.
6. Keep a small **alias file** (`aliases.yaml`) so a correction made once in review is remembered for the next book of that series.

## 9. Console and logging

- Structured log file (`/var/log/abs-ingest/ingest.log`), rotated.
- Live console for production: `abs-ingest watch` (coloured, shows each book moving through the stages, errors in red) and `journalctl -fu abs-ingest` for the raw service log.
- `abs-ingest status`: what is in `inbox/`, `processing/`, `review/`, `failed/`, plus the last N errors.
- Every error includes the book name, the stage that failed, and the reason.
- Optional later: a tiny read-only web page with the same information.

## 10. Install and use (Ubuntu server)

```bash
# 1. Create a service account (skip if it already exists).
sudo useradd --system --home /var/lib/abs-ingest --create-home --shell /usr/sbin/nologin abs-ingest

# 2. Create or mount storage. Review and library must exist before setup.
sudo mkdir -p /srv/audiobooks/review /srv/audiobooks/library
sudo ./deploy/setup-acls.sh            # or pass the directories from your config

# 3. Install and configure
sudo mkdir -p /opt/abs-ingest /etc/abs-ingest
sudo python3 -m venv /opt/abs-ingest/venv
sudo /opt/abs-ingest/venv/bin/pip install .
sudo cp config.example.yaml /etc/abs-ingest/config.yaml  # set paths, URL, and both library IDs
echo 'ABS_TOKEN=your-audiobookshelf-api-token' | sudo tee /etc/abs-ingest/env
sudo chmod 600 /etc/abs-ingest/env

# 4. Try it WITHOUT moving anything
abs-ingest --config /etc/abs-ingest/config.yaml run-once --dry-run --now

# 5. Run as a service
sudo cp deploy/abs-ingest.service /etc/systemd/system/
sudo systemctl enable --now abs-ingest
journalctl -fu abs-ingest            # the live console
```

Everyday commands:

| Command | Does |
|---|---|
| `abs-ingest watch` | run in the foreground with the live coloured console |
| `abs-ingest status` | what is in inbox / review / failed, plus recent errors |
| `abs-ingest parse "Azarinth Healer, Book 7"` | show how a name is understood |
| `abs-ingest approve "<name in review>" --author ... --series ... --number N` | file a review item and remember the series |
| `abs-ingest run-once [--dry-run] [--now]` | process what is ready, then exit |

## 11. Status and honest limitations

Run the automated suite with `pip install -e '.[dev]'` followed by `pytest`.

**Not verified, please check on your server:**

* **The real Audiobookshelf search call.** Run `--dry-run` first. If identification finds nothing for
  known books, inspect the response shape handled by `parse_result` in `abs_client.py`.
* **Permissions on the target system.** Verify the configured service user, ABS group, mount paths,
  and ACLs before enabling the service.
* **The Windows-to-server transfer** (see `deploy/syncthing-notes.md`).
* No record of already-ingested names: if your sync tool re-delivers a book it would be ingested again
  (an existing destination is never overwritten; it goes to `review/`).
* Without a working lookup (no token, Audiobookshelf down) every book goes to `review/`. That is deliberate:
  the author is not in your file names, so guessing would misfile books.

Next improvements: **`abs-ingest sort`** - after you match a book in Audiobookshelf's web interface, file it from the review library into the final library automatically (this needs Audiobookshelf to store `metadata.json` with the item, which should be verified on the target server); a small read-only web page for the console, an ingested-names ledger,
splitting box sets automatically, other lookup sources (Open Library, Google Books) as a fallback.
