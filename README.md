# flalac

Keeps a lossless mirror of your music library in another format: point it at your FLAC
library and it maintains an ALAC copy for iTunes, the Music app and iPods (or the other way
round, ALAC → FLAC). New, changed, renamed and deleted songs are followed automatically, and
each song gets readable plain lyrics.

- **Bit-identical.** Every converted file is decoded and compared with the source before it
  replaces anything.
- **Tags, cover art, MusicBrainz IDs** carried over the way Picard and iTunes expect them.
- **Lyrics** for iPods and the Music app: plain or synced lyrics from [LRCLIB](https://lrclib.net)
  or your own `.txt`/`.lrc` files, embedded and written next to each song. Edit one and flalac
  keeps your version.
- **Cheap updates.** A tag change only rewrites tags; a rename moves the copy; nothing is
  re-encoded unless the audio changed.
- **Safe.** The source is only read. Nothing is deleted when the source looks missing, and a scan
  that would delete more than 5 % of the mirror waits for you to confirm. Files flalac did not
  make are never touched.
- **iPod-ready by default.** Hi-res files are reduced to 16-bit / 48 kHz with dither (configurable).

## Run it

```sh
docker run -d --name flalac -p 8090:8090 \
  -v /path/to/music/flac:/source:ro \
  -v /path/to/music/alac:/target \
  -v ./config:/config \
  codeberg.org/kintsugiuwu/flalac:latest
```

Then open `http://<host>:8090`. A [compose file](compose.yaml) and a rootless Podman
[quadlet](contrib/flalac.container) are included.

Tip: start once with `DRY_RUN=true`. The log then lists everything flalac *would* do.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `TARGET_FORMAT` | `alac` | `alac`, `flac` or `aac` (lossy, for small devices) |
| `AAC_BITRATE` | `256` | kbit/s when the target is AAC |
| `MAX_BIT_DEPTH` | `16` | reduce higher bit depths (with dither); `0` keeps the source |
| `MAX_SAMPLE_RATE` | `48000` | reduce higher sample rates; `0` keeps the source |
| `LYRICS` | `lrclib` | `lrclib`: LRCLIB, else local files; `sidecar`: only local `.txt`/`.lrc`; `off` |
| `LYRICS_STYLE` | `plain` | `plain` or `synced` (also switchable in the web UI) |
| `WORKERS` | half the CPUs (1–4) | songs converted in parallel |
| `RESCAN_MINUTES` | `30` | full rescan interval, on top of watching for changes; `0` turns it off |
| `SETTLE_SECONDS` | `10` | wait until a file stopped changing (taggers write in steps) |
| `DELETE_GUARD_PERCENT` | `5` | larger deletions wait for confirmation in the UI |
| `AUTH_TOKEN` | – | protects the UI and API (`Authorization: Bearer …` for scripts) |
| `DRY_RUN` | `false` | only list what would happen |
| `PUID` / `PGID` / `UMASK` | `1000` / `1000` / `022` | user, group and permissions for files written (when started as root) |
| `PORT` | `8090` | web UI port |

Volumes: `/source` (read-only), `/target`, `/config`.

## Lyrics

**Plain** (default): your `.txt` next to the source file → LRCLIB's plain lyrics, exactly as on
lrclib.net → the `.lrc` next to the source without its timestamps → lyrics already in the tags.
A `.txt` is written next to each converted song and the text is embedded.

**Synced**: your `.lrc` next to the source file → LRCLIB's synced lyrics; songs without synced
lyrics fall back to plain. A `.lrc` is written next to each song and the timed text is embedded
(for players that show synced lyrics; iPods and the Music app display it as text).

LRCLIB is asked once per song, politely (one request at a time), only for entries within 2 s of
the song's length, and the answer is cached. If LRCLIB is down, local lyrics are used for now
and the song is asked again later. Songs LRCLIB marks as instrumental are shown as such. Edit a
lyrics file next to a converted song and flalac keeps your version.

## Develop

```sh
uv sync
uv run pytest
uv run ruff format --check . && uv run ruff check .
SOURCE_DIR=./in TARGET_DIR=./out CONFIG_DIR=./config uv run flalac
```

Needs `ffmpeg` on the PATH. Design rules for the UI are in [DESIGN.md](DESIGN.md).

## Licence

GPL-3.0-or-later. Bundled: Atkinson Hyperlegible Next (SIL OFL 1.1), htmx (0BSD).
