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
- **iPod-ready by default.** Hi-res files are reduced to 16-bit / 44.1 kHz (CD quality, what iPods play natively) with dither (configurable).

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
| `MAX_SAMPLE_RATE` | `44100` | resample anything higher to this rate; `0` keeps the source |
| `LYRICS` | `lrclib` | `lrclib`: LRCLIB only; `sidecar`: only your `.txt`/`.lrc` next to the source; `off` |
| `LYRICS_STYLE` | `plain` | `plain` or `synced` (also switchable in the web UI) |
| `LYRICS_FILES` | `on` | `off`: lyrics only embedded, no `.txt`/`.lrc` next to each song (turning it off removes the ones flalac wrote) |
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

With `LYRICS=lrclib` (the default) lyrics come only from LRCLIB; files next to the source are
never read. `LYRICS=sidecar` uses only your own files instead (`.txt`, else `.lrc` without its
timestamps, else lyrics already in the tags).

**Plain** (default): LRCLIB's plain lyrics, exactly as on lrclib.net. A `.txt` is written next
to each converted song and the text is embedded.

**Synced**: LRCLIB's synced lyrics; songs without synced lyrics fall back to plain. A `.lrc` is
written next to each song and the timed text is embedded (for players that show synced lyrics;
iPods and the Music app display it as text).

LRCLIB is asked once per song, politely (one request at a time), and the answer is cached. An
entry needs a shared artist and the same title; the best is one within 2 s of the song's length,
else the same title at another length (an edit or remaster; plain lyrics only), else a title with
an extra suffix such as "Footloose (Footloose)". If LRCLIB is down, the song is asked again later.
Songs LRCLIB marks as instrumental are shown as such. If LRCLIB has words for a version
that is instrumental in your library, list its source path (as shown in the web UI) in
`no-lyrics.txt` in the config folder, one per line; flalac removes its lyrics on the next pass. Edit a
lyrics file next to a converted song and flalac keeps your version.

## Develop

```sh
uv sync
uv run pytest
uv run ruff format --check . && uv run ruff check .
SOURCE_DIR=./in TARGET_DIR=./out CONFIG_DIR=./config uv run flalac
```

Needs `ffmpeg` on the PATH. Design rules for the UI are in [DESIGN.md](DESIGN.md).

## Releases

Codeberg CI (Woodpecker) runs lint and tests on every push. Pushing a version tag such as
`v0.2.0` (matching `version` in `pyproject.toml`) also builds the image and publishes it to
`codeberg.org/kintsugiuwu/flalac` as `0.2.0` and `latest`. Pin a version in your quadlet or
compose file so nothing changes until you choose to update.

## Licence

GPL-3.0-or-later. Bundled: Atkinson Hyperlegible Next (SIL OFL 1.1), htmx (0BSD).
