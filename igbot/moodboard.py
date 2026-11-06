"""Moodboard carousel slides: a title plus labelled photo tiles.

Photos come from Openverse, filtered to public-domain and CC0 works, which may
be used commercially without attribution. Each photo is cached locally with
its source so a post can always be traced back to a licence.
"""

from __future__ import annotations

import io
import json
import random
import re
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import BUILD_DIR, ROOT

FONT_DIR = ROOT / "assets" / "fonts"
SIZE = (1080, 1350)
OPENVERSE = "https://api.openverse.org/v1/images/"
LICENSES = "cc0,pdm"

STYLE = {
    "background": "#E4E8DA",   # soft sage, deliberately not organic__101_'s cream
    "title": "#2F3B2A",
    "label": "#3A3328",
    "tile_border": "#FBFAF5",
    "accent": "#A0703C",
}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def find_photo(query: str, cache: Path, skip: set[str] | None = None) -> dict | None:
    """Download the first suitable public-domain/CC0 photo for `query`."""
    cache.mkdir(parents=True, exist_ok=True)
    resp = requests.get(OPENVERSE, params={"q": query, "license": LICENSES, "page_size": 20,
                                           "mature": "false"}, timeout=30)
    resp.raise_for_status()
    for result in resp.json().get("results", []):
        if (skip and result["id"] in skip) or (result.get("width") or 0) < 500:
            continue
        try:
            img = requests.get(result["url"], timeout=30)
            img.raise_for_status()
            photo = Image.open(io.BytesIO(img.content)).convert("RGB")
        except (requests.RequestException, OSError):
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
        path = cache / f"{slug}.jpg"
        photo.save(path, "JPEG", quality=90)
        meta = {"query": query, "id": result["id"], "license": result.get("license"),
                "source": result.get("foreign_landing_url"), "creator": result.get("creator")}
        path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"path": path, **meta}
    return None


def _tile(photo: Path, size: tuple[int, int], angle: float) -> Image.Image:
    """Photo cropped to `size`, white border, soft shadow, slight tilt."""
    img = ImageOps.fit(Image.open(photo).convert("RGB"), size)
    border = 12
    framed = Image.new("RGBA", (size[0] + 2 * border, size[1] + 2 * border), STYLE["tile_border"])
    framed.paste(img, (border, border))
    shadow = Image.new("RGBA", (framed.width + 40, framed.height + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([20, 26, framed.width + 20, framed.height + 26], fill=(0, 0, 0, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    shadow.alpha_composite(framed, (20, 20))
    return shadow.rotate(angle, resample=Image.BICUBIC, expand=True)


def render(title: str, tiles: list[tuple[str, Path]], out: Path, seed: int = 0,
           handle: str = "", footer: str = "") -> Path:
    """One slide: serif title on top, up to 6 labelled tiles in a loose grid."""
    rnd = random.Random(seed)
    W, H = SIZE
    slide = Image.new("RGBA", SIZE, STYLE["background"])
    draw = ImageDraw.Draw(slide)

    title_font = _font("DMSerifDisplay-Regular.ttf", 92)
    while draw.textlength(title, font=title_font) > W - 140 and title_font.size > 56:
        title_font = _font("DMSerifDisplay-Regular.ttf", title_font.size - 4)
    tw = draw.textlength(title, font=title_font)
    draw.text(((W - tw) / 2, 70), title, font=title_font, fill=STYLE["title"])
    draw.line([(W / 2 - 60, 70 + title_font.size + 28), (W / 2 + 60, 70 + title_font.size + 28)],
              fill=STYLE["accent"], width=4)

    label_font = _font("Inter-Regular.otf", 30)
    cols, rows = 2, 3
    top, bottom = 250, 90
    cell_w, cell_h = W // cols, (H - top - bottom) // rows
    photo_size = (int(cell_w * 0.74), int(cell_h * 0.64))
    for n, (label, photo) in enumerate(tiles[: cols * rows]):
        col, row = n % cols, n // cols
        tile = _tile(photo, photo_size, rnd.uniform(-4, 4))
        cx = col * cell_w + cell_w // 2 + rnd.randint(-18, 18)
        cy = top + row * cell_h + int(cell_h * 0.40) + rnd.randint(-8, 8)
        slide.alpha_composite(tile, (cx - tile.width // 2, cy - tile.height // 2))
        lw = draw.textlength(label, font=label_font)
        draw.text((cx - lw / 2, cy + photo_size[1] // 2 + 22), label, font=label_font, fill=STYLE["label"])

    small = _font("Inter-Bold.otf", 28)
    if handle:
        hw = draw.textlength(f"@{handle}", font=small)
        draw.text(((W - hw) / 2, H - 62), f"@{handle}", font=small, fill=STYLE["title"])
    if footer:
        fw = draw.textlength(footer, font=small)
        draw.text((W - 70 - fw, H - 62), footer, font=small, fill=STYLE["accent"])

    out.parent.mkdir(parents=True, exist_ok=True)
    slide.convert("RGB").save(out, "JPEG", quality=92)
    return out


def render_text_slide(lines: list[str], out: Path, handle: str = "") -> Path:
    """Closing slide: a short call to action in the same style."""
    W, H = SIZE
    slide = Image.new("RGB", SIZE, STYLE["background"])
    draw = ImageDraw.Draw(slide)
    big = _font("DMSerifDisplay-Regular.ttf", 84)
    body = _font("Inter-Regular.otf", 40)
    y = H // 2 - 200
    for n, line in enumerate(lines):
        font = big if n == 0 else body
        lw = draw.textlength(line, font=font)
        draw.text(((W - lw) / 2, y), line, font=font, fill=STYLE["title"])
        y += font.size + (60 if n == 0 else 24)
    if handle:
        small = _font("Inter-Bold.otf", 34)
        hw = draw.textlength(f"@{handle}", font=small)
        draw.text(((W - hw) / 2, H - 140), f"@{handle}", font=small, fill=STYLE["accent"])
    out.parent.mkdir(parents=True, exist_ok=True)
    slide.save(out, "JPEG", quality=92)
    return out
