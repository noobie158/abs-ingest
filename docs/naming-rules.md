# How names are read

`abs-ingest parse "<name>" ...` shows what the tool understands, without any config.

| Input name | Name | Number |
|---|---|---|
| `Azarinth Healer, Book 7` | Azarinth Healer | 7 (explicit) |
| `Backstreet Evolutionist Book 5` | Backstreet Evolutionist | 5 (explicit) |
| `Book 6 Nameless Sovereign` | Nameless Sovereign | 6 (explicit) |
| `The Stubborn Skill-Grinder in a Time Loop 5` | The Stubborn Skill-Grinder in a Time Loop | 5 (bare) |
| `Chaos Walking Complete Chronological Collection` | whole name | none, box set -> review |

Rules, in order:

1. Noise is removed first: `(Unabridged)`, `[anything in brackets]`, `320kbps`, underscores, file extension.
2. `Book N` / `Vol N` / `#N` at the **start**, then at the **end**: *explicit* number.
3. A bare 1-2 digit number at the end: *bare* number. This is weaker: Audible must confirm it,
   otherwise the book goes to `review/` (so `Catch 22` or `Fahrenheit 451` are not mistaken for book numbers).
4. Words like `Collection`, `Box Set`, `Omnibus`, `Books 1-3` mark a box set: always `review/`.

## What decides "file automatically" vs "review"

Confidence (0 - 1) must reach `identify.auto_threshold` (default 0.85):

* name matches the lookup result's series/title **and** the book number matches -> high
* embedded author tag agrees with the lookup -> small bonus; disagrees -> penalty
* two different books match equally well -> capped, goes to review
* a remembered alias (from a previous `approve`) -> files automatically for that series

## Fixing something in `review/`

```
abs-ingest approve "Backstreet Evolutionist Book 5" \
    --author "Author Name" --series "Backstreet Evolutionist" --number 5
```

This files the book and remembers the series, so `Backstreet Evolutionist Book 6`
afterwards goes through without help. Use `--no-remember` to skip that.
