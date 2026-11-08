#!/usr/bin/env python3
"""Rebuild packaging/flalac.icns from src/flalac/static/icon.svg.

The icon follows Apple's macOS app icon grid (Big Sur and later): a 824 px rounded
square with a 185.4 px corner radius, centred on a transparent 1024 px canvas, with a
soft drop shadow. macOS 26 and later wrap an icon that misses this grid in a rounded
square of their own; macOS 11 to 15 show it exactly as drawn, so an opaque square
icon stays a square there.

Needs Pillow and ImageMagick (`magick`) to render the SVG:

    python3 packaging/make_icns.py
"""

import io
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "src/flalac/static/icon.svg"
OUT = ROOT / "packaging/flalac.icns"

SS = 4  # supersampling factor
N = 1024 * SS  # canvas
BODY = 824 * SS  # rounded square
OFF = 100 * SS  # its margin
RADIUS = round(185.4 * SS)
ART = 0.78  # iPod height as a share of the body


def render_svg() -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "art.png"
        subprocess.run(
            [
                "magick",
                "-background",
                "none",
                "-density",
                "3072",
                str(SVG),
                "-resize",
                f"{N}x{N}",
                str(png),
            ],
            check=True,
        )
        art = Image.open(png).convert("RGBA")
        art.load()
    return art.crop(art.getchannel("A").getbbox())


def master() -> Image.Image:
    mask = Image.new("L", (BODY, BODY), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, BODY - 1, BODY - 1], radius=RADIUS, fill=255)

    canvas = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    # shadow: black at 30 %, 10 px down, 10 px blur (at 1024 px)
    shadow = Image.new("L", (N, N), 0)
    shadow.paste(mask, (OFF, OFF + 10 * SS))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10 * SS)).point(lambda v: int(v * 0.30))
    canvas.paste(Image.new("RGBA", (N, N), (0, 0, 0, 255)), (0, 0), shadow)

    # white body with a faint top-to-bottom tint
    body = Image.new("RGBA", (BODY, BODY))
    draw = ImageDraw.Draw(body)
    for y in range(BODY):
        v = round(255 - 10 * y / BODY)
        draw.line([(0, y), (BODY, y)], fill=(v, v, v, 255))
    canvas.paste(body, (OFF, OFF), mask)

    art = render_svg()
    h = int(BODY * ART)
    w = int(art.width * h / art.height)
    art = art.resize((w, h), Image.LANCZOS)
    canvas.alpha_composite(art, ((N - w) // 2, (N - h) // 2))
    return canvas.resize((1024, 1024), Image.LANCZOS)


def write_icns(img: Image.Image, path: Path) -> None:
    def png(px: int) -> bytes:
        buf = io.BytesIO()
        img.resize((px, px), Image.LANCZOS).save(buf, "PNG", optimize=True)
        return buf.getvalue()

    types = [
        ("ic11", 32),
        ("ic12", 64),
        ("ic07", 128),
        ("ic13", 256),
        ("ic08", 256),
        ("ic14", 512),
        ("ic09", 512),
        ("ic10", 1024),
    ]
    chunks = b"".join(
        t.encode() + struct.pack(">I", 8 + len(d)) + d for t, d in ((t, png(px)) for t, px in types)
    )
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(chunks)) + chunks)


if __name__ == "__main__":
    write_icns(master(), OUT)
    print(f"wrote {OUT}")
