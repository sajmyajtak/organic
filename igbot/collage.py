"""Moodboard collage slides, built the way the niche's best carousels are.

Taken apart from @organic__101_'s top posts (country / season "maxxing",
6.000-18.500 likes): a cover that is a full-bleed wall of photos with a torn
paper strip carrying the title; inner slides on light paper with one big hero
picture above the title and 14-18 big things all around it, each with a short
lifestyle label ("Buying lemons", "Lake swimming", "Fresh pasta"). Things are
either cut-outs (food, objects) or rectangular photos of scenes and
activities. Colours, type and the white die-cut edge are ours (`brand` in
config/account.yaml).

Three layouts (content.slide_layout):
  cover  first slide: photos edge to edge above and below a torn paper strip
         with the title; cut-out stickers overlap the strip's edges; no labels.
  board  inner slides: hero on top, title, labelled things packed around.
  cta    closing slide: the cover's look with the post's own photos, the call
         to action and the handle on an accent pill.
Item flags in the post: `photo: true` (a rectangular photo of a scene or an
activity, not cut out) and `hero: true` (the big picture above the title).

Items are placed by a small packer, so any number of objects of any shape fits
without covering the title, the labels or (on boards) each other.
"""

from __future__ import annotations

import os
import random
import re
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage, signal

from .config import ROOT
from .content import slide_layout

FONT_DIR = ROOT / "assets" / "fonts"
SIZE = (1080, 1350)
GRID = 6  # packer resolution in px
BLEED = 30  # how far cover stickers may run off the page
COVER_OVERLAP = 16  # px cover stickers may overlap: about the white border, so thin parts stay visible
BOARD_OVERLAP = 6   # px neighbours on a board may tuck under each other, like a hand-made collage


@dataclass(frozen=True)
class Style:
    paper: str = "#E5D5BA"
    board: str = "#F1EADF"        # inner slides: light paper, so the photos carry the colour
    ink: str = "#3A2517"          # title
    label: str = "#3A2517"
    accent: str = "#9C4F28"
    outline: int = 7              # white die-cut border in px
    frame: int = 7                # white border of a rectangular photo
    max_rotation: float = 6
    shadow: tuple[int, int, int, float] = (4, 9, 9, 0.30)  # dx, dy, blur, opacity
    label_font: str = "Inter-Regular.otf"
    label_size: int = 29
    grain: float = 1.0
    margin: int = 34
    gap: int = 8                  # min space between objects

    @classmethod
    def from_brand(cls, brand: dict | None) -> "Style":
        brand = brand or {}
        base = cls()
        return replace(base, paper=brand.get("background", base.paper), ink=brand.get("foreground", base.ink),
                       label=brand.get("foreground", base.label), accent=brand.get("accent", base.accent))


STYLE = Style()


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


# --- paper ---------------------------------------------------------------

def paper(size: tuple[int, int], color: str, seed: int = 0, grain: float = 1.0) -> Image.Image:
    """Procedural paper: soft blotches, faint fibres, fine grain, light vignette."""
    w, h = size
    rng = np.random.default_rng(seed)
    low = ndimage.gaussian_filter(rng.standard_normal((h // 6, w // 6)), 7).astype(np.float32)
    low = np.array(Image.fromarray(low, "F").resize((w, h), Image.BICUBIC))
    low /= np.abs(low).max() + 1e-6
    fibres = ndimage.gaussian_filter(rng.standard_normal((h, w)), sigma=(0.6, 2.6))
    fibres /= fibres.std() + 1e-6
    fine = rng.standard_normal((h, w))
    yy, xx = np.mgrid[0:h, 0:w]
    r2 = (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 2
    lum = (1 + grain * (0.035 * low + 0.010 * fibres + 0.012 * fine)) * (1 - 0.07 * r2)
    base = np.array(ImageColor.getrgb(color), np.float32)
    return Image.fromarray(np.clip(base * lum[..., None], 0, 255).astype(np.uint8), "RGB")


# --- text ----------------------------------------------------------------

def _text_w(font, text: str) -> float:
    return font.getlength(text)


def _clean(text: str) -> str:
    """Drop emoji and joiners: the bundled fonts have no glyphs for them."""
    return "".join(ch for ch in text if ord(ch) < 0x1F000 and not 0xFE00 <= ord(ch) <= 0xFE0F
                   and ch not in "\u200d\u2600\u2728").strip()


def _wrap(font, text: str, max_w: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if line and font.getlength(test) > max_w:
            lines.append(line)
            line = word
        else:
            line = test
    return lines + ([line] if line else [])


def _fit(text: str, font_name: str, top: int, max_w: float) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """Largest size where `text` fits on one line (down to 0.72*top), else two lines."""
    for max_lines, floor in ((1, int(top * 0.72)), (2, int(top * 0.5)), (3, 40)):
        for size in range(top, floor - 1, -4):
            font = _font(font_name, size)
            lines = _wrap(font, text, max_w)
            if len(lines) <= max_lines:
                return lines, font
    return _wrap(font, text, max_w), font


@dataclass
class Line:
    text: str
    font: ImageFont.FreeTypeFont
    fill: str
    gap_after: int = 0
    tracking: float = 0          # extra space between letters, px

    @property
    def width(self) -> float:
        return _text_w(self.font, self.text) + self.tracking * max(0, len(self.text) - 1)

    @property
    def height(self) -> float:
        return self.font.getbbox(self.text or "x")[3]


def _kicker(text: str, style: Style, size: int) -> Line:
    """Small spaced capitals in the accent colour above a title ("THIS", "NOT THIS", "THEN")."""
    return Line(text.upper(), _font("Inter-Bold.otf", size), style.accent, tracking=size * 0.28)


def _title_lines(title: str, body: str, style: Style, max_w: float, big: int, kicker: str = "") -> list[Line]:
    serif = "DMSerifDisplay-Regular.ttf"
    lines: list[Line] = []
    if kicker:
        lines.append(_kicker(kicker, style, max(22, int(big * 0.2))))
        lines[-1].gap_after = int(big * 0.16)
    main = title
    m = re.match(r"(?i)^(the art of)\s+(.+)$", title.strip())
    if m:
        main = m.group(2)
        lines.append(Line(m.group(1), _font(serif, int(big * 0.46)), style.ink, gap_after=int(big * 0.02)))
    texts, font = _fit(main, serif, big, max_w)
    lines += [Line(t, font, style.ink, gap_after=int(font.size * -0.06)) for t in texts]
    if body:
        body_font = _font("Inter-Regular.otf", 34)
        lines[-1].gap_after = 34
        lines += [Line(t, body_font, style.label, gap_after=10) for t in _wrap(body_font, body, max_w)]
    return lines


def _measure(lines: list[Line]) -> tuple[float, float]:
    width = max(line.width for line in lines)
    height = sum(line.height + line.gap_after for line in lines) - lines[-1].gap_after
    return width, height


def _draw_text(draw, xy: tuple[float, float], line: Line) -> None:
    if not line.tracking:
        draw.text(xy, line.text, font=line.font, fill=line.fill)
        return
    x, y = xy
    for ch in line.text:
        draw.text((x, y), ch, font=line.font, fill=line.fill)
        x += _text_w(line.font, ch) + line.tracking


def _draw_lines(draw, lines: list[Line], x0: float, y0: float, block_w: float) -> None:
    y = y0
    for line in lines:
        _draw_text(draw, (x0 + (block_w - line.width) / 2, y), line)
        y += line.height + line.gap_after


# --- stickers ------------------------------------------------------------

def _outline(img: Image.Image, px: int) -> Image.Image:
    """Die-cut sticker: a smooth white border around the object's silhouette."""
    pad = px + 6
    canvas = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
    canvas.paste(img, (pad, pad))
    mask = np.asarray(canvas.getchannel("A")) > 110
    dilated = ndimage.distance_transform_edt(~mask) <= px
    smooth = ndimage.gaussian_filter(dilated.astype(np.float32), px / 2.5)  # rounds off spikes and notches
    border = np.clip((smooth - 0.35) * 6, 0, 1)
    out = Image.new("RGBA", canvas.size, (255, 252, 245, 0))
    out.putalpha(Image.fromarray((border * 255).astype(np.uint8), "L"))
    out.alpha_composite(canvas)
    return out


def _maxpool(mask: np.ndarray, g: int = GRID) -> np.ndarray:
    h, w = mask.shape
    ph, pw = -h % g, -w % g
    m = np.pad(mask, ((0, ph), (0, pw)))
    return m.reshape(m.shape[0] // g, g, m.shape[1] // g, g).any(axis=(1, 3))


@dataclass
class Item:
    label: str                  # may hold a line break
    image: Image.Image          # styled, rotated sticker or framed photo (no shadow)
    label_font: ImageFont.FreeTypeFont
    footprint: np.ndarray       # grid mask: object + gap + label
    origin: tuple[int, int]     # image top-left inside the footprint, px
    label_box: tuple[float, float]  # label centre x and top y, relative to image
    pos: tuple[int, int] | None = None
    grid: tuple[int, int] | None = None   # footprint's top-left cell once placed
    remake: object = None                 # side -> the same thing at another size (for growing)
    side: float = 0.0


def _crop_to(img: Image.Image, aspect: float) -> Image.Image:
    """Centre crop to width/height = aspect (a little above centre: horizons, faces)."""
    w, h = img.size
    if w / h > aspect:
        nw = round(h * aspect)
        return img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    nh = round(w / aspect)
    top = max(0, min(h - nh, round((h - nh) * 0.4)))
    return img.crop((0, top, w, top + nh))


def _framed(photo: Image.Image, side: float, style: Style, aspect: float | None = None) -> Image.Image:
    """A rectangular photo with a thin white border, like a print."""
    img = photo.convert("RGB")
    if aspect is None:   # keep the photo's shape, within reason
        aspect = min(1.35, max(0.75, img.width / img.height))
    img = _crop_to(img, aspect)
    w = side * aspect ** 0.5
    h = side / aspect ** 0.5
    img = img.resize((max(1, round(w)), max(1, round(h))), Image.LANCZOS)
    b = style.frame
    out = Image.new("RGBA", (img.width + 2 * b, img.height + 2 * b), (255, 252, 245, 255))
    out.paste(img, (b, b))
    return out


def _label_lines(font, text: str, max_w: float) -> list[str]:
    """One line if it fits, else two balanced lines (never more)."""
    if _text_w(font, text) <= max_w or " " not in text:
        return [text]
    words = text.split()
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        width = max(_text_w(font, a), _text_w(font, b))
        if best is None or width < best[0]:
            best = (width, [a, b])
    return best[1]


def _prepare(label: str, cut: Image.Image, side: float, style: Style, rnd: random.Random,
             overlap: int = 0, angle: float | None = None, photo: bool = False) -> Item:
    """A sized, outlined (or framed), rotated thing and its footprint for the packer.

    An empty label draws none. overlap > 0 shrinks the footprint by that many
    px, so neighbouring stickers may overlap like a pile. photo=True keeps the
    picture rectangular with a white border instead of a die-cut outline."""
    if photo:
        img = _framed(cut, side, style)
    else:
        w, h = cut.size
        scale = side / (w * h) ** 0.5
        scale = min(scale, side * 1.45 / max(w, h))
        img = cut.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        if style.outline:
            img = _outline(img, style.outline)
    if angle is None:
        angle = rnd.uniform(-style.max_rotation, style.max_rotation) * (0.5 if photo else 1)
    if abs(angle) > 0.3:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    alpha = np.asarray(img.getchannel("A")) > 20
    ys, xs = np.nonzero(alpha)
    obj_bottom, obj_cx = ys.max(), (xs.min() + xs.max()) / 2

    text = _clean(label)
    font = _font(style.label_font, style.label_size)
    g = style.gap
    if not text:
        body = ndimage.distance_transform_edt(alpha) > overlap if overlap else alpha
        full = np.pad(body, g)
        full = ndimage.distance_transform_edt(~full) <= g if g else full
        return Item("", img, font, _maxpool(full), (g, g), (obj_cx, obj_bottom))
    lines = _label_lines(font, text, max(img.width * 1.15, 250))
    text = "\n".join(lines)
    lw = max(_text_w(font, t) for t in lines)
    line_h = font.getbbox("Hg")[3]
    lh = line_h * len(lines) + 2 * (len(lines) - 1)
    label_top = obj_bottom + 6
    lx0, ly0 = obj_cx - lw / 2 - 6, label_top - 4
    lx1, ly1 = obj_cx + lw / 2 + 6, label_top + lh + 6

    fx0, fx1 = min(0, int(lx0)), max(img.width, int(np.ceil(lx1)))
    fy1 = max(img.height, int(np.ceil(ly1)))
    full = np.zeros((fy1 + 2 * g, fx1 - fx0 + 2 * g), bool)
    ox, oy = -fx0 + g, g
    body = ndimage.distance_transform_edt(alpha) > overlap if overlap else alpha
    full[oy:oy + img.height, ox:ox + img.width] = body
    full = ndimage.distance_transform_edt(~full) <= g if g else full
    full[int(ly0) + oy:int(ly1) + oy, int(lx0) + ox:int(np.ceil(lx1)) + ox] = True
    return Item(text, img, font, _maxpool(full), (ox, oy), (obj_cx, label_top))


def _place(occ: np.ndarray, fp: np.ndarray, rnd: random.Random, snug: bool = False) -> tuple[int, int] | None:
    """Top-left grid cell where `fp` overlaps nothing.

    Default: deepest in free space (things spread out). snug=True: where the
    footprint touches the most of what is already there (other things, the
    title, the page margin), so a board fills up densely like the niche's
    boards instead of leaving holes between scattered things."""
    fh, fw = fp.shape
    if fh > occ.shape[0] or fw > occ.shape[1]:
        return None
    occ_f = occ.astype(np.float32)
    overlap = signal.fftconvolve(occ_f, fp[::-1, ::-1].astype(np.float32), mode="valid")
    valid = overlap < 0.5
    if not valid.any():
        return None
    noise = np.random.default_rng(rnd.randrange(1 << 30)).uniform(0, 2.5, valid.shape)
    if snug:
        r = 3
        padded = np.pad(fp, r)
        ring = ndimage.binary_dilation(padded, iterations=r) & ~padded
        # The page edge counts as something to lean on.
        occ_p = np.pad(occ_f, r, constant_values=1.0)
        contact = signal.fftconvolve(occ_p, ring[::-1, ::-1].astype(np.float32), mode="valid")
        score = np.where(valid, contact + noise, -1)
    else:
        clearance = ndimage.distance_transform_edt(~occ)
        cy, cx = fh // 2, fw // 2
        score = clearance[cy:cy + valid.shape[0], cx:cx + valid.shape[1]]
        score = np.where(valid, score + noise, -1)
    y, x = np.unravel_index(int(np.argmax(score)), score.shape)
    return int(y), int(x)


FAN_MAX = 4  # stickers on the closing slide


def _fan(cuts: list[Image.Image], style: Style, rnd: random.Random) -> list[Item]:
    """The closing slide's stickers: a gentle arc tilted outwards, middle ones on top.
    Positions are relative to the fan's top centre (0, 0); the caller moves them."""
    cuts = cuts[:FAN_MAX]
    n = len(cuts)
    W = SIZE[0]
    side = {1: 420, 2: 380, 3: 350}.get(n, 315)
    items = []
    for k, cut in enumerate(cuts):
        t = (k - (n - 1) / 2) / ((n - 1) / 2) if n > 1 else 0.0   # -1 .. 1
        size = side * (1.1 - 0.14 * abs(t))
        items.append((t, _prepare("", cut, size, style, rnd, angle=-10 * t + rnd.uniform(-3, 3))))
    # centres spread so neighbours just touch, the whole fan inside the margins
    widths = [i.image.width for _, i in items]
    step = sum(widths) / n * 0.86
    span = min(step * (n - 1), W - 2 * style.margin - (widths[0] + widths[-1]) / 2) if n > 1 else 0
    tallest = max(i.image.height for _, i in items)
    for t, item in items:
        cx = t * span / 2
        cy = tallest / 2 + 34 * t * t
        item.pos = (int(cx - item.image.width / 2), int(cy - item.image.height / 2))
    return [item for _, item in sorted(items, key=lambda ti: -abs(ti[0]))]   # outer first, middle on top


def _composite(slide: Image.Image, placed: list[Item], style: Style) -> None:
    """Stickers in order, each with its own soft shadow, so piled stickers shade the ones below."""
    dx, dy, blur, opacity = style.shadow
    pad = 3 * blur
    for item in placed:
        x, y = item.pos
        a = item.image.getchannel("A")
        sh = Image.new("L", (a.width + 2 * pad, a.height + 2 * pad), 0)
        sh.paste(a, (pad, pad))
        sh = sh.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * opacity))
        tint = Image.new("RGBA", sh.size, (52, 36, 22, 255))
        tint.putalpha(sh)
        _paste_clipped(slide, tint, (x + dx - pad, y + dy - pad))
        _paste_clipped(slide, item.image, (x, y))


def _paste_clipped(canvas: Image.Image, img: Image.Image, xy: tuple[int, int]) -> None:
    """alpha_composite that tolerates images partly outside the canvas."""
    x, y = xy
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(img.width, canvas.width - x), min(img.height, canvas.height - y)
    if right <= left or bottom <= top:
        return
    canvas.alpha_composite(img.crop((left, top, right, bottom)), (x + left, y + top))


def _pill(draw, text: str, cx: float, top: float, style: Style, size: int = 34) -> tuple[float, float, float, float]:
    """The handle on a rounded accent pill; returns its box."""
    font = _font("Inter-Bold.otf", size)
    tw = _text_w(font, text)
    th = font.getbbox(text)[3]
    px, py = size * 0.85, size * 0.5
    box = (cx - tw / 2 - px, top, cx + tw / 2 + px, top + th + 2 * py)
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) / 2, fill=style.accent)
    draw.text((cx - tw / 2, top + py - size * 0.06), text, font=font, fill=style.paper)
    return box


# --- full-bleed cover and closing slide ------------------------------------

def _torn_strip(size: tuple[int, int], y0: float, y1: float, color: str, seed: int) -> tuple[Image.Image, Image.Image]:
    """A strip of paper torn along both long edges, and its shadow (both RGBA, page-sized)."""
    W, H = size
    rng = np.random.default_rng(seed)
    xs = np.arange(W, dtype=np.float32)

    def edge(base: float) -> np.ndarray:
        n = np.zeros(W, np.float32)
        for scale, amp in ((260, 26), (70, 10), (14, 4), (3, 1.6)):   # long waves, then fibres
            pts = rng.standard_normal(W // scale + 3).astype(np.float32)
            n += amp * np.interp(xs / scale, np.arange(len(pts)), pts)
        return base + n

    top, bottom = edge(y0), edge(y1)
    yy = np.arange(H, dtype=np.float32)[:, None]
    mask = (yy >= top[None, :]) & (yy <= bottom[None, :])
    sheet = np.asarray(paper(size, color, seed=seed + 7, grain=0.9), np.float32)
    # The torn edge shows the paper's lighter core: a ragged pale rim.
    depth = ndimage.distance_transform_edt(mask)
    rim_w = 3.0 + 2.5 * np.abs(ndimage.gaussian_filter1d(rng.standard_normal(W), 3))[None, :]
    rim = (depth > 0) & (depth < rim_w)
    sheet[rim] = sheet[rim] * 0.25 + np.array([252, 250, 245], np.float32) * 0.75
    layer = Image.fromarray(np.clip(sheet, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    layer.putalpha(Image.fromarray((mask * 255).astype(np.uint8), "L"))
    sh = Image.fromarray((mask * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(10))
    sh = ImageChops_offset(sh, 0, 6).point(lambda v: int(v * 0.42))
    shadow = Image.new("RGBA", size, (40, 28, 18, 255))
    shadow.putalpha(sh)
    return layer, shadow


def ImageChops_offset(img: Image.Image, dx: int, dy: int) -> Image.Image:
    out = Image.new(img.mode, img.size, 0)
    out.paste(img, (dx, dy))
    return out


def _band(slide: Image.Image, photos: list[Image.Image], y0: int, y1: int, rnd: random.Random) -> None:
    """Photos edge to edge across the page between y0 and y1, in columns of varied width."""
    if not photos:
        return
    W = slide.width
    weights = [rnd.uniform(0.75, 1.35) for _ in photos]
    total = sum(weights)
    x = 0
    for n, (img, wt) in enumerate(zip(photos, weights)):
        w = W - x if n == len(photos) - 1 else round(W * wt / total)
        tile = _crop_to(img.convert("RGB"), w / (y1 - y0)).resize((w, y1 - y0), Image.LANCZOS)
        slide.paste(tile, (x, y0))
        x += w


def _banded(slide: Image.Image, photos: list[Image.Image], stickers: list[Image.Image], style: Style,
            rnd: random.Random, seed: int, strip: tuple[float, float]) -> tuple[float, float]:
    """The cover look: photo wall above and below a torn paper strip, stickers on its edges.
    Returns the strip's (top, bottom) in px; the caller writes on it."""
    W, H = SIZE
    s0, s1 = H * strip[0], H * strip[1]
    half = (len(photos) + 1) // 2
    _band(slide, photos[:half], 0, int(s0) + 40, rnd)
    _band(slide, photos[half:] or photos[:half], int(s1) - 40, H, rnd)
    layer, shadow = _torn_strip(SIZE, s0, s1, style.board, seed)
    slide.alpha_composite(shadow)
    slide.alpha_composite(layer)
    # Stickers sit on the strip's torn edges, away from the text in its middle.
    n_top = (len(stickers) + 1) // 2
    placed = []
    for k, cut in enumerate(stickers):
        top = k < n_top
        row = n_top if top else len(stickers) - n_top
        i = k if top else k - n_top
        cx = W * (i + 0.5) / row + rnd.uniform(-40, 40) + (0 if top else W * 0.08 * (1 if i % 2 else -1))
        item = _prepare("", cut, rnd.uniform(250, 310), style, rnd)
        cy = s0 - item.image.height * 0.32 if top else s1 + item.image.height * 0.30
        item.pos = (int(min(max(cx - item.image.width / 2, -20), W - item.image.width + 20)),
                    int(cy - item.image.height / 2))
        placed.append(item)
    _composite(slide, placed, style)
    return s0, s1


# --- slides --------------------------------------------------------------

def _draw_label(draw, item: Item, style: Style) -> None:
    cx, ty = item.label_box
    line_h = item.label_font.getbbox("Hg")[3] + 2
    for k, line in enumerate(item.label.split("\n")):
        lw = _text_w(item.label_font, line)
        draw.text((item.pos[0] + cx - lw / 2, item.pos[1] + ty + k * line_h), line, font=item.label_font,
                  fill=style.label)


def _things(items: list) -> list[tuple[str, Image.Image, bool, bool]]:
    """(label, image, photo, hero) from (label, path) or (label, path, {"photo":.., "hero":..})."""
    out = []
    for it in items:
        label, path, flags = (it if len(it) == 3 else (*it, {}))
        img = Image.open(path)
        photo = bool(flags.get("photo"))
        out.append((label, img.convert("RGB" if photo else "RGBA"), photo, bool(flags.get("hero"))))
    return out


def _fit_box(label: str, img: Image.Image, photo: bool, box_w: float, box_h: float, style: Style,
             rnd: random.Random) -> tuple[Image.Image, list[str]]:
    """The thing (outlined cut-out or framed photo, slightly turned) as big as fits in
    box_w x box_h with its label underneath, and the label's lines."""
    font = _font(style.label_font, style.label_size)
    lines = _label_lines(font, _clean(label), box_w - 8) if _clean(label) else []
    label_h = (font.getbbox("Hg")[3] + 2) * len(lines) + (8 if lines else 0)
    room_w, room_h = box_w, max(40.0, box_h - label_h)
    angle = rnd.uniform(-style.max_rotation, style.max_rotation) * (0.45 if photo else 0.8)
    k = rnd.uniform(0.92, 1.0)
    for _ in range(6):   # as big as the box allows, then shrink until the turned picture fits
        if photo:
            src = img.convert("RGB")
            aspect = min(1.35, max(0.75, src.width / src.height))
            side = min(room_w / aspect ** 0.5, room_h * aspect ** 0.5)
            pic = _framed(src, side * k, style, aspect)
        else:
            w, h = img.size
            sc = min(room_w / w, room_h / h) * k
            pic = img.resize((max(1, round(w * sc)), max(1, round(h * sc))), Image.LANCZOS)
            pic = _outline(pic, style.outline) if style.outline else pic
        if abs(angle) > 0.3:
            pic = pic.rotate(angle, resample=Image.BICUBIC, expand=True)
        fit = min(room_w / pic.width, room_h / pic.height)
        if fit >= 0.995:
            break
        k *= fit * 0.99
    box = pic.getchannel("A").getbbox()
    return (pic.crop(box) if box else pic), lines


def _grid_board(slide: Image.Image, cuts: list, hero_box: tuple[float, float, float, float],
                title_box: tuple[float, float, float, float], style: Style, rnd: random.Random) -> list[Item]:
    """The niche's board, made regular: two columns of things beside the hero, rows of
    things under the title, every thing as big as its cell allows, label underneath."""
    W, H = SIZE
    m, gap = style.margin, 14
    n = len(cuts)
    hx0, hy0, hx1, hy1 = hero_box
    side_rows = 2 if n <= 14 else 3
    side_cells = []
    for x0, x1 in ((m, hx0 - gap), (hx1 + gap, W - m)):
        ch = (hy1 - m) / side_rows
        side_cells += [(x0, m + r * ch, x1, m + (r + 1) * ch) for r in range(side_rows)]
    rest = n - len(side_cells)
    top = title_box[3] + 18
    rows = 2 if rest <= 10 else 3
    per_row = [rest // rows + (1 if r < rest % rows else 0) for r in range(rows)]
    rh = (H - m - top) / rows
    bottom_cells = []
    for r, k in enumerate(per_row):
        cw = (W - 2 * m) / max(1, k)
        bottom_cells += [(m + c * cw, top + r * rh, m + (c + 1) * cw, top + (r + 1) * rh) for c in range(k)]
    cells = (side_cells + bottom_cells)[:n]
    # Photos and cut-outs alternate, so neither clumps in one corner.
    photos_ = [c for c in cuts if c[2]]
    others = [c for c in cuts if not c[2]]
    order, pi, oi = [], 0, 0
    for k in range(n):
        want_photo = photos_ and (k % 3 == 1 or not others[oi:])
        if want_photo and pi < len(photos_):
            order.append(photos_[pi]); pi += 1
        elif oi < len(others):
            order.append(others[oi]); oi += 1
        else:
            order.append(photos_[pi]); pi += 1
    rnd.shuffle(cells)
    items = []
    font = _font(style.label_font, style.label_size)
    line_h = font.getbbox("Hg")[3] + 2
    for (label, img, photo, _), (x0, y0, x1, y1) in zip(order, cells):
        pic, lines = _fit_box(label, img, photo, x1 - x0 - 8, y1 - y0 - 8, style, rnd)
        block_h = pic.height + (8 + line_h * len(lines) if lines else 0)
        px = (x0 + x1) / 2 - pic.width / 2 + rnd.uniform(-6, 6)
        py = (y0 + y1) / 2 - block_h / 2 + rnd.uniform(-5, 5)
        item = Item("\n".join(lines), pic, font, np.zeros((1, 1), bool), (0, 0),
                    (pic.width / 2, pic.height + 6))
        item.pos = (int(px), int(py))
        items.append(item)
    return items


def _grow(occ: np.ndarray, placed: list[Item], bleed: int, rounds: int = 6, step: float = 1.08) -> None:
    """Fill the holes the packer leaves: each thing grows in place, around its own centre,
    as long as it touches nothing new. The board ends up as full as the niche's boards."""
    H, W = occ.shape
    for _ in range(rounds):
        grew = False
        for k, item in enumerate(placed):
            if item.remake is None:
                continue
            gy, gx = item.grid
            fh, fw = item.footprint.shape
            occ[gy:gy + fh, gx:gx + fw] &= ~item.footprint
            bigger = item.remake(item.side * step)
            bh, bw = bigger.footprint.shape
            ny, nx = round(gy + fh / 2 - bh / 2), round(gx + fw / 2 - bw / 2)
            fits = (0 <= ny and 0 <= nx and ny + bh <= H and nx + bw <= W
                    and not (occ[ny:ny + bh, nx:nx + bw] & bigger.footprint).any())
            if fits:
                occ[ny:ny + bh, nx:nx + bw] |= bigger.footprint
                bigger.pos = (nx * GRID + bigger.origin[0] - bleed, ny * GRID + bigger.origin[1] - bleed)
                bigger.grid, bigger.remake, bigger.side = (ny, nx), item.remake, item.side * step
                placed[k] = bigger
                grew = True
            else:
                occ[gy:gy + fh, gx:gx + fw] |= item.footprint
        if not grew:
            break


def _vintage(img: Image.Image, seed: int = 0) -> Image.Image:
    """A faded warm print: mostly sepia, lifted blacks, softer highlights, fine grain."""
    arr = np.asarray(img.convert("RGB"), np.float32) / 255.0
    gray = arr @ np.array([0.299, 0.587, 0.114], np.float32)
    sepia = np.stack([gray * 1.07 + 0.05, gray * 0.93 + 0.03, gray * 0.74 + 0.01], axis=-1)
    out = 0.72 * sepia + 0.28 * arr
    out = 0.07 + out * 0.86
    out += np.random.default_rng(seed).normal(0, 0.022, gray.shape)[..., None]
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), "RGB")


def _pair(things: list, title: str, body: str, kicker: str, style: Style, out: Path) -> Path:
    """Then and now, the way the niche's best comparison carousel does it: four photos edge
    to edge, the top two captioned with `title` ("Evenings then"), the bottom two with
    `body` ("Evenings now"), and an optional word on the seam (`kicker`, e.g. "Why?")."""
    W, H = SIZE
    slide = Image.new("RGB", SIZE, style.board)
    cw, ch = W // 2, H // 2
    for k, (_, img, _, _) in enumerate(things[:4]):
        tile = _crop_to(img.convert("RGB"), cw / ch).resize((cw, ch), Image.LANCZOS)
        if k < 2:   # "then": an old print's warm, faded tones, so the comparison reads at a glance
            tile = _vintage(tile, seed=k)
        slide.paste(tile, ((k % 2) * cw, (k // 2) * ch))
    slide = slide.convert("RGBA")

    def caption(text: str, cy: float, size: int, font_name: str = "Inter-Bold.otf") -> None:
        text = _clean(text)
        if not text:
            return
        font = _font(font_name, size)
        while _text_w(font, text) > W - 120 and size > 40:
            size -= 4
            font = _font(font_name, size)
        tw, th = _text_w(font, text), font.getbbox(text)[3]
        x, y = (W - tw) / 2, cy - th / 2 - size * 0.12
        shadow = Image.new("L", SIZE, 0)
        ImageDraw.Draw(shadow).text((x, y + 3), text, font=font, fill=255)
        shadow = shadow.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.75))
        dark = Image.new("RGBA", SIZE, (0, 0, 0, 255))
        dark.putalpha(shadow)
        slide.alpha_composite(dark)
        ImageDraw.Draw(slide).text((x, y), text, font=font, fill="#FFFFFF")

    caption(title, ch * 0.5, 66)
    caption(body, ch * 1.5, 66)
    if kicker:
        caption(kicker, ch, 110, "DMSerifDisplay-Regular.ttf")
    out.parent.mkdir(parents=True, exist_ok=True)
    slide.convert("RGB").save(out, "JPEG", quality=93)
    return out


def render_slide(title: str, items: list, out: Path, style: Style = STYLE,
                 seed: int = 0, handle: str = "", body: str = "", layout: str = "board",
                 kicker: str = "") -> Path:
    """One collage slide; returns the JPEG path. layout: "cover", "board" or "cta"
    (see the module docstring). Labels are drawn on boards only. items:
    (label, path) or (label, path, {"photo": bool, "hero": bool})."""
    rnd = random.Random(seed)
    W, H = SIZE
    m = style.margin
    things = _things(items)
    if layout == "pair":
        return _pair(things, title, body, kicker, style, out)
    photos_ = [img for _, img, photo, _ in things if photo]
    cuts_only = [img for _, img, photo, _ in things if not photo]

    # Cover and closing slide with photos: the full-bleed wall with a torn strip.
    if layout in ("cover", "cta") and len(photos_) >= 2:
        slide = paper(SIZE, style.board, seed=seed, grain=0.6).convert("RGBA")
        strip = (0.355, 0.635) if layout == "cover" else (0.33, 0.67)
        s0, s1 = _banded(slide, photos_, cuts_only[:6 if layout == "cover" else 4], style, rnd, seed, strip)
        draw = ImageDraw.Draw(slide)
        lines = _title_lines(_clean(title), _clean(body), style, W - 2 * m - 90, 132 if layout == "cover" else 112,
                             kicker)
        if layout == "cover" and handle:
            lines[-1].gap_after = 22
            lines.append(_kicker(f"@{handle}", style, 24))
            lines[-1].tracking = 3
        tw, th = _measure(lines)
        pill_h = 82 if layout == "cta" and handle else 0
        y0 = (s0 + s1) / 2 - (th + (40 + pill_h if pill_h else 0)) / 2 + 4
        _draw_lines(draw, lines, (W - tw) / 2, y0, tw)
        if pill_h:
            _pill(draw, f"@{handle}", W / 2, y0 + th + 40, style)
        out.parent.mkdir(parents=True, exist_ok=True)
        slide.convert("RGB").save(out, "JPEG", quality=93)
        return out

    slide = paper(SIZE, style.paper if layout != "board" else style.board, seed=seed,
                  grain=style.grain if layout != "board" else 0.6).convert("RGBA")
    draw = ImageDraw.Draw(slide)
    cuts = [(label if layout == "board" else "", img, photo, hero) for label, img, photo, hero in things]
    placed: list[Item] = []

    if layout == "cta":
        lines = _title_lines(_clean(title), _clean(body), style, W - 2 * m - 80, 116, kicker)
        tw, th = _measure(lines)
        placed = _fan([c for _, c, photo, _ in cuts if not photo], style, rnd) if cuts else []
        fan_h = max((i.pos[1] + i.image.height for i in placed), default=0)
        pill_h, gap_fan, gap_pill = 82, 70, 56
        total = fan_h + (gap_fan if placed else 0) + th + (gap_pill + pill_h if handle else 0)
        top = (H - total) / 2 - 10   # optically a touch above centre
        for item in placed:
            item.pos = (int(W / 2 + item.pos[0]), int(top + item.pos[1]))
        y0 = top + fan_h + (gap_fan if placed else 0)
        _draw_lines(draw, lines, (W - tw) / 2, y0, tw)
        if handle:
            _pill(draw, f"@{handle}", W / 2, y0 + th + gap_pill, style)
        _composite(slide, placed, style)
        out.parent.mkdir(parents=True, exist_ok=True)
        slide.convert("RGB").save(out, "JPEG", quality=93)
        return out

    cover = layout == "cover"
    # The cover's stickers may run off the page edges (BLEED px), like a full collage.
    bleed = BLEED if cover else 0
    occ = np.zeros(((H + 2 * bleed) // GRID, (W + 2 * bleed) // GRID), bool)

    def block(x0, y0, x1, y1, pad=0):
        x0, x1, y0, y1 = x0 + bleed, x1 + bleed, y0 + bleed, y1 + bleed
        occ[max(0, int((y0 - pad) // GRID)):int(np.ceil((y1 + pad) / GRID)),
            max(0, int((x0 - pad) // GRID)):int(np.ceil((x1 + pad) / GRID))] = True

    if not cover:
        # page frame: keep objects inside the margins
        block(0, 0, W, m); block(0, H - m, W, H); block(0, 0, m, H); block(W - m, 0, W, H)

    lines = _title_lines(_clean(title), _clean(body), style, W - 2 * m - 40, 150 if cover else 124, kicker)
    tw, th = _measure(lines)
    hero = next((c for c in cuts if c[3]), None) if not cover else None
    title_y = H * (0.5 if cover else (0.5 if hero else 0.47)) - th / 2
    if cover and handle:
        lines[-1].gap_after = 26
        lines.append(_kicker(f"@{handle}", style, 24))
        lines[-1].tracking = 3
        tw, th = _measure(lines)
    x0 = (W - tw) / 2
    block(x0, title_y, x0 + tw, title_y + th, pad=34 if cover else 22)
    tag, tag_font = (f"@{handle}", _font("Inter-Bold.otf", 22)) if handle and not cover else ("", None)
    if tag:
        hw = _text_w(tag_font, tag)
        block((W - hw) / 2, title_y + th + 10, (W + hw) / 2, title_y + th + 42, pad=8)

    if hero:
        # The big picture above the title, like the flag or figure of the niche's best boards.
        label, img, photo, _ = hero
        cuts.remove(hero)
        room_h = title_y - m - 4
        if photo:   # a near-square crop fills the band above the title and leaves two columns
            img = _crop_to(img.convert("RGB"), 1.08)
        side = min(room_h, W * 0.46) * (0.98 if photo else 0.92)
        item = _prepare("", img, side, style, rnd, angle=rnd.uniform(-1.5, 1.5), photo=photo)
        k = min(1.0, room_h / item.image.height, W * 0.48 / item.image.width)
        if k < 1:
            item = _prepare("", img, side * k, style, rnd, angle=0, photo=photo)
        hx = int((W - item.image.width) / 2)
        hy = int(title_y + 10 - item.image.height)
        item.pos = (hx, hy)
        alpha = np.asarray(item.image.getchannel("A")) > 20
        fp = _maxpool(np.pad(alpha, style.gap) if style.gap else alpha)
        gy, gx = max(0, (hy - style.gap) // GRID), max(0, (hx - style.gap) // GRID)
        h_, w_ = min(fp.shape[0], occ.shape[0] - gy), min(fp.shape[1], occ.shape[1] - gx)
        occ[gy:gy + h_, gx:gx + w_] |= fp[:h_, :w_]
        placed.append(item)

    if cuts and hero and not cover:
        hx0, hy0 = placed[0].pos
        hero_box = (hx0, hy0, hx0 + placed[0].image.width, hy0 + placed[0].image.height)
        bottom = title_y + th + (46 if tag else 10)
        placed += _grid_board(slide, cuts, hero_box, (x0, title_y, x0 + tw, bottom), style, rnd)
        cuts = []

    if cuts:
        free_px = (~occ).sum() * GRID * GRID
        side = (free_px * (0.6 if cover else 0.52) / len(cuts)) ** 0.5
        sizes = [side * (1.12 if n == 0 else rnd.uniform(0.88, 1.08)) * (1.08 if c[2] else 1.0)
                 for n, c in enumerate(cuts)]
        order = sorted(range(len(cuts)), key=lambda n: -sizes[n])
        base, fixed = occ.copy(), list(placed)
        # Everything has to fit: if something finds no room, pack again a size smaller.
        for scale in (1.0, 0.92, 0.85, 0.78, 0.72, 0.66):
            occ, placed, missing = base.copy(), list(fixed), []
            for n in order:
                label, cut, photo, _ = cuts[n]
                for attempt in range(8):   # a thing that doesn't fit shrinks alone first
                    side_now = sizes[n] * scale * 0.94 ** attempt
                    angle = rnd.uniform(-style.max_rotation, style.max_rotation) * (0.5 if photo else 1)
                    remake = (lambda sd, label=label, cut=cut, photo=photo, angle=angle:
                              _prepare(label, cut, sd, style, rnd, angle=angle, photo=photo,
                                       overlap=COVER_OVERLAP if cover else BOARD_OVERLAP))
                    item = remake(side_now)
                    pos = _place(occ, item.footprint, rnd, snug=False)
                    if pos:
                        gy, gx = pos
                        occ[gy:gy + item.footprint.shape[0], gx:gx + item.footprint.shape[1]] |= item.footprint
                        item.pos = (gx * GRID + item.origin[0] - bleed, gy * GRID + item.origin[1] - bleed)
                        item.grid, item.remake, item.side = (gy, gx), remake, side_now
                        placed.append(item)
                        break
                else:
                    missing.append(label or str(n + 1))
            if os.environ.get("IGBOT_DEBUG_PACK"):
                print("  scale", scale, "side", round(side), "missing", missing)
            if not missing:
                break
        for label in missing:
            print(f"  bez místa: {label}")
        if not cover:
            _grow(occ, placed, bleed)

    if cover:
        # Piled stickers: big ones underneath, so a small one never hides behind a big one.
        placed.sort(key=lambda i: -int((np.asarray(i.image.getchannel("A")) > 20).sum()))
    else:
        first = placed[:1] if hero else []
        rest = placed[len(first):]
        rnd.shuffle(rest)  # z-order doesn't follow size
        placed = first + rest
    _composite(slide, placed, style)
    draw = ImageDraw.Draw(slide)
    _draw_lines(draw, lines, x0, title_y, tw)   # after the pictures: the hero may tuck under the title
    if tag:
        draw.text(((W - _text_w(tag_font, tag)) / 2, title_y + th + 14), tag, font=tag_font, fill=style.accent)
    for item in placed:
        if item.label:
            _draw_label(draw, item, style)

    out.parent.mkdir(parents=True, exist_ok=True)
    slide.convert("RGB").save(out, "JPEG", quality=93)
    return out


def render_slides(slides: list[dict], out_dir: Path, handle: str = "", style: Style = STYLE,
                  find=None, seed: int = 0, name=lambda n: f"{n:02d}.jpg",
                  find_photo=None) -> tuple[list[Path], list[dict]]:
    """All slides of one post plus the licence trail of its photos.

    slide = {"title": .., "kicker": small line above the title (optional),
             "body": .. (closing slide), "items": [{"label": .., "queries": [..],
             "photo": true (scene, not cut out), "hero": true (big, above the title)}],
             "layout": "cover" | "board" | "cta" (default: content.slide_layout),
             "echo": [labels] (closing slide: which earlier stickers to show)}
    A closing slide without items shows pictures of the post's other slides.
    """
    from . import cutout

    find = find or cutout.find_cutout
    find_photo = find_photo or cutout.find_photo
    used: set[str] = set()
    credits: list[dict] = []
    seen: list[list[tuple[float, str, Path, bool]]] = []   # per slide: (score, label, path, photo)

    def collect(spec_items: list[dict], pair: bool = False) -> list[tuple[str, Path, dict]]:
        got = []
        for spec in spec_items:
            queries = spec.get("queries") or [spec.get("query") or spec["label"]]
            photo = bool(spec.get("photo")) or pair
            finder = find_photo if photo else find
            best = None
            for q in queries:
                found = finder(q, exclude=used)
                if found and (best is None or found["score"] > best["score"]):
                    best = found
                if best and best["score"] >= 0.45:
                    break
            label = spec.get("label") or queries[0]
            if not best or best["score"] < 0.15:
                print(f"  bez fotky: {label}")
                continue
            used.add(best["id"])
            credits.append({"label": label, **{k: v for k, v in best.items() if k != "path"}})
            got.append((label, Path(best["path"]), {"photo": photo, "hero": bool(spec.get("hero"))}))
            seen[-1].append((best["score"], label, Path(best["path"]), photo))
        return got

    def echo(labels: list[str] | None = None) -> list[tuple[str, Path, dict]]:
        """Pictures of earlier slides for the closing slide: a wall of up to 8 photos (one
        from each slide in turn) with 4 stickers, or without photos a fan of stickers.
        Stickers named in `labels` come first, then the best of each slide."""
        named = [n.lower() for n in labels or []]
        order = seen[1:] + seen[:1]           # inner slides first, the cover last
        ranked = [sorted(slide, key=lambda x: -x[0]) for slide in order]
        wall: list = []
        for depth in range(max((len(r) for r in ranked), default=0)):
            for r in ranked:
                photos_here = [x for x in r if x[3]]
                if depth < len(photos_here) and len(wall) < 8:
                    wall.append(photos_here[depth])
        cuts: list = [x for name in named for slide in order for x in slide if not x[3] and x[1].lower() == name]
        for depth in range(max((len(r) for r in ranked), default=0)):
            for r in ranked:
                stickers = [x for x in r if not x[3]]
                if depth < len(stickers) and stickers[depth] not in cuts:
                    cuts.append(stickers[depth])
        if len(wall) >= 2:
            return [(x[1], x[2], {"photo": True}) for x in wall] + [(x[1], x[2], {}) for x in cuts[:4]]
        return [(x[1], x[2], {}) for x in cuts[:FAN_MAX]]

    paths = []
    for n, slide in enumerate(slides, start=1):
        layout = slide_layout(slides, n - 1)
        print(f"slide {n}/{len(slides)} ({layout}): {slide['title']}")
        seen.append([])
        things = collect(slide.get("items") or [], pair=layout == "pair")
        if layout == "cta" and not things:
            things = echo(slide.get("echo"))
        paths.append(render_slide(slide["title"], things, out_dir / name(n), style, seed=seed + n,
                                  handle=handle, body=slide.get("body") or "", layout=layout,
                                  kicker=slide.get("kicker") or ""))
    return paths, credits


def render_post(plan: dict, out_dir: Path, handle: str = "", style: Style = STYLE,
                find=None, seed: int = 0) -> tuple[list[Path], list[dict]]:
    """A plan file: {"slides": [...], "cta": {"title", "body", "items"}} (cta = closing slide)."""
    slides = list(plan["slides"]) + ([{**plan["cta"], "layout": "cta"}] if plan.get("cta") else [])
    return render_slides(slides, out_dir, handle, style, find, seed)


def is_collage(item: dict) -> bool:
    return any(s.get("items") for s in item.get("slides") or [])


def render_item(item: dict, out_dir: Path, brand: dict | None = None, handle: str = "",
                find=None, seed: int = 0) -> list[Path]:
    """Slides of a queue item. The photo licence trail is stored on the item
    (`photo_credits`), so it is kept when the item is saved as published."""
    paths, credits = render_slides(item["slides"], out_dir, handle, Style.from_brand(brand), find,
                                   seed=sum(map(ord, item["id"])) + seed, name=lambda n: f"{item['id']}-{n}.jpg")
    item["photo_credits"] = credits
    return paths


def contact_sheet(paths: list[Path], out: Path, cols: int = 3, width: int = 360) -> Path:
    """All slides of a post side by side, for quick review."""
    h = round(width * SIZE[1] / SIZE[0])
    rows = -(-len(paths) // cols)
    sheet = Image.new("RGB", (cols * width + (cols + 1) * 16, rows * h + (rows + 1) * 16), "#FFFFFF")
    for n, p in enumerate(paths):
        img = Image.open(p).convert("RGB").resize((width, h), Image.LANCZOS)
        sheet.paste(img, (16 + (n % cols) * (width + 16), 16 + (n // cols) * (h + 16)))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=90)
    return out
