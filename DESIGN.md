# flalac design

flalac exists to feed iPods and iTunes. The interface borrows from the iPod's own: a plain list
you move through, one flat highlight for the current row, and hardware colours. It is a tool you
glance at to see whether the mirror is in step, so the library table is the whole screen.

## Layout

- Top bar: the name, one sentence of status ("2,214 of 2,214 in step · watching /source"), and
  the only action, "Scan now".
- Main: one table, grouped by album folder. An album is a row; it opens (native `<details>`) to
  show its tracks. Columns: title, state, lyrics source. Nothing else competes with it.
- Filters above the table: All · Problems · Lyrics missing, plus a search field.
- Bottom: a one-line activity strip with the latest event; the full log is a separate page.
- No dashboard, no stat cards, no hero, no sidebar.

## Colour (hardware, not a template palette)

| Role | Light | Dark |
| --- | --- | --- |
| Page (aluminium) | `#e6e8eb` | `#141517` |
| Rows (LCD white) | `#f9fafb` | `#1d1e21` |
| Ink (graphite) | `#1c1d1f` | `#e8e9eb` |
| Secondary text | `#575c63` | `#a6aab0` |
| Rules | `#c8ccd1` | `#36383d` |
| Highlight (iPod menu selection, flat) | `#2a5fc0` on white text | `#3d73d6` on white text |
| In step | `#2c6a37` | `#7cc489` |
| Waiting | `#865600` | `#e0b25a` |
| Error | `#b0241c` | `#f08a82` |

Status colours appear only on the state word they describe. All text meets WCAG AA.

## Type

- Atkinson Hyperlegible Next, 400 and 700, self-hosted (no font CDN). 15 px base.
- Tabular figures for counts, durations and times.
- Sentence case everywhere. No all-caps letter-spaced labels, no monospace "terminal" chrome.

## Shape and motion

- Square-ish: 3 px radius at most, on inputs and buttons only. No shadows, no blur.
- The current row gets the full-width flat highlight (like the iPod menu), keyboard first:
  rows are focusable, Enter opens an album.
- Visible focus ring: 2 px highlight colour, 2 px offset.
- Motion only where it carries information (progress); none under `prefers-reduced-motion`.

## Never

Gradients or gradient text; card grids; `rounded-2xl` + `shadow-lg` + `backdrop-blur`; shadcn or
Tailwind default palettes; emoji; icons inside rounded squares; sparkles; cream + terracotta;
Inter, Space Grotesk, Geist, Fraunces, Instrument Serif; uniform fade-up animations; generic
copy ("Elevate…", "Get started"). Every page is checked against this list.
