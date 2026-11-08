"""Moodboard collage slides: cut-out photo "stickers" around a big serif title.

The technique follows the best-performing format of the niche (10-15 cut-out
objects with small labels around a large title on paper), the look is our own:
kraft paper, white die-cut outlines, title in the middle, colours from
`brand` in config/account.yaml.

Three layouts (content.slide_layout):
  cover  first slide of a carousel: pure mood. Bigger stickers piled densely
         around the title, overlapping a little, no labels.
  board  inner slides and single images: title with labelled stickers.
  cta    closing slide: a fan of the post's stickers without labels, the call
         to action and the handle on an accent pill.

Items are placed by a small packer, so any number of objects of any shape fits
without covering the title, the labels or (on boards) each other.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class Style:
    paper: str = "#E5D5BA"
    ink: str = "#3A2517"          # title
    label: str = "#3A2517"
    accent: str = "#9C4F28"
    outline: int = 9              # white die-cut border in px
    max_rotation: float = 7
    shadow: tuple[int, int, int, float] = (4, 9, 9, 0.30)  # dx, dy, blur, opacity
    label_font: str = "Inter-Regular.otf"
    label_size: int = 25
    grain: float = 1.0
    margin: int = 46
    gap: int = 10                 # min space between objects

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
    label: str
    image: Image.Image          # styled, rotated sticker (no shadow)
    label_font: ImageFont.FreeTypeFont
    footprint: np.ndarray       # grid mask: object + gap + label
    origin: tuple[int, int]     # image top-left inside the footprint, px
    label_box: tuple[float, float]  # label centre x and top y, relative to image
    pos: tuple[int, int] | None = None


def _prepare(label: str, cut: Image.Image, side: float, style: Style, rnd: random.Random,
             overlap: int = 0, angle: float | None = None) -> Item:
    """A sized, outlined, rotated sticker and its footprint for the packer.

    An empty label draws none. overlap > 0 shrinks the footprint by that many
    px, so neighbouring stickers may overlap like a pile (cover slide)."""
    w, h = cut.size
    scale = side / (w * h) ** 0.5
    scale = min(scale, side * 1.45 / max(w, h))
    img = cut.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    if style.outline:
        img = _outline(img, style.outline)
    if angle is None:
        angle = rnd.uniform(-style.max_rotation, style.max_rotation)
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
    lw = _text_w(font, text)
    lh = font.getbbox(text)[3]
    label_top = obj_bottom + (8 if style.outline else 12)
    lx0, ly0 = obj_cx - lw / 2 - 6, label_top - 4
    lx1, ly1 = obj_cx + lw / 2 + 6, label_top + lh + 6

    fx0, fx1 = min(0, int(lx0)), max(img.width, int(np.ceil(lx1)))
    fy1 = max(img.height, int(np.ceil(ly1)))
    full = np.zeros((fy1 + 2 * g, fx1 - fx0 + 2 * g), bool)
    ox, oy = -fx0 + g, g
    full[oy:oy + img.height, ox:ox + img.width] = alpha
    full = ndimage.distance_transform_edt(~full) <= g if g else full
    full[int(ly0) + oy:int(ly1) + oy, int(lx0) + ox:int(np.ceil(lx1)) + ox] = True
    return Item(text, img, font, _maxpool(full), (ox, oy), (obj_cx, label_top))


def _place(occ: np.ndarray, fp: np.ndarray, rnd: random.Random) -> tuple[int, int] | None:
    """Top-left grid cell where `fp` overlaps nothing and sits deepest in free space."""
    fh, fw = fp.shape
    if fh > occ.shape[0] or fw > occ.shape[1]:
        return None
    overlap = signal.fftconvolve(occ.astype(np.float32), fp[::-1, ::-1].astype(np.float32), mode="valid")
    valid = overlap < 0.5
    if not valid.any():
        return None
    clearance = ndimage.distance_transform_edt(~occ)
    cy, cx = fh // 2, fw // 2
    score = clearance[cy:cy + valid.shape[0], cx:cx + valid.shape[1]]
    noise = np.random.default_rng(rnd.randrange(1 << 30)).uniform(0, 2.5, valid.shape)
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


# --- slides --------------------------------------------------------------

def render_slide(title: str, items: list[tuple[str, Path]], out: Path, style: Style = STYLE,
                 seed: int = 0, handle: str = "", body: str = "", layout: str = "board",
                 kicker: str = "") -> Path:
    """One collage slide; returns the JPEG path. layout: "cover", "board" or "cta"
    (see the module docstring). Labels are drawn on boards only."""
    rnd = random.Random(seed)
    W, H = SIZE
    m = style.margin
    slide = paper(SIZE, style.paper, seed=seed, grain=style.grain).convert("RGBA")
    draw = ImageDraw.Draw(slide)
    cuts =[(label if layout == "board" else "", Image.open(path).convert("RGBA")) for label, path in items]
    placed: list[Item] = []

    if layout == "cta":
        lines = _title_lines(_clean(title), _clean(body), style, W - 2 * m - 80, 116, kicker)
        tw, th = _measure(lines)
        placed = _fan([c for _, c in cuts], style, rnd) if cuts else []
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

    lines = _title_lines(_clean(title), _clean(body), style, W - 2 * m - 40, 150 if cover else 138, kicker)
    if cover and handle:
        lines[-1].gap_after = 26
        lines.append(_kicker(f"@{handle}", style, 24))
        lines[-1].tracking = 3
    tw, th = _measure(lines)
    x0, y0 = (W - tw) / 2, H * (0.5 if cover else 0.47) - th / 2
    _draw_lines(draw, lines, x0, y0, tw)
    block(x0, y0, x0 + tw, y0 + th, pad=34 if cover else 26)

    if handle and not cover:
        tag = f"@{handle}"
        f = _font("Inter-Bold.otf", 24)
        hw = _text_w(f, tag)
        draw.text(((W - hw) / 2, H - m - 14), tag, font=f, fill=style.ink)
        block((W - hw) / 2, H - m - 18, (W + hw) / 2, H, pad=12)

    if cuts:
        free_px = (~occ).sum() * GRID * GRID
        side = (free_px * (0.6 if cover else 0.36) / len(cuts)) ** 0.5
        sizes = [side * (1.18 if n == 0 else rnd.uniform(0.86, 1.1)) for n in range(len(cuts))]
        order = sorted(range(len(cuts)), key=lambda n: -sizes[n])
        for n in order:
            label, cut = cuts[n]
            for attempt in range(7):
                item = _prepare(label, cut, sizes[n] * 0.9 ** attempt, style, rnd, overlap=COVER_OVERLAP if cover else 0)
                pos = _place(occ, item.footprint, rnd)
                if pos:
                    gy, gx = pos
                    occ[gy:gy + item.footprint.shape[0], gx:gx + item.footprint.shape[1]] |= item.footprint
                    item.pos = (gx * GRID + item.origin[0] - bleed, gy * GRID + item.origin[1] - bleed)
                    placed.append(item)
                    break
            else:
                print(f"  bez místa: {label or n + 1}")

    if cover:
        # Piled stickers: big ones underneath, so a small one never hides behind a big one.
        placed.sort(key=lambda i: -int((np.asarray(i.image.getchannel("A")) > 20).sum()))
    else:
        rnd.shuffle(placed)  # z-order doesn't follow size
    _composite(slide, placed, style)
    draw = ImageDraw.Draw(slide)
    for item in placed:
        if item.label:
            cx, ty = item.label_box
            lw = _text_w(item.label_font, item.label)
            draw.text((item.pos[0] + cx - lw / 2, item.pos[1] + ty), item.label, font=item.label_font,
                      fill=style.label)

    out.parent.mkdir(parents=True, exist_ok=True)
    slide.convert("RGB").save(out, "JPEG", quality=93)
    return out


def render_slides(slides: list[dict], out_dir: Path, handle: str = "", style: Style = STYLE,
                  find=None, seed: int = 0, name=lambda n: f"{n:02d}.jpg") -> tuple[list[Path], list[dict]]:
    """All slides of one post plus the licence trail of its photos.

    slide = {"title": .., "kicker": small line above the title (optional),
             "body": .. (closing slide), "items": [{"label": .., "queries": [..]}],
             "layout": "cover" | "board" | "cta" (default: content.slide_layout),
             "echo": [labels] (closing slide: which earlier stickers to show)}
    A closing slide without items shows stickers of the post's other slides.
    """
    from . import cutout

    find = find or cutout.find_cutout
    used: set[str] = set()
    credits: list[dict] = []
    seen: list[list[tuple[float, str, Path]]] = []   # per slide: (score, label, path)

    def collect(spec_items: list[dict]) -> list[tuple[str, Path]]:
        got = []
        for spec in spec_items:
            queries = spec.get("queries") or [spec.get("query") or spec["label"]]
            best = None
            for q in queries:
                found = find(q, exclude=used)
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
            got.append((label, Path(best["path"])))
            seen[-1].append((best["score"], label, Path(best["path"])))
        return got

    def echo(labels: list[str] | None = None, count: int = FAN_MAX) -> list[tuple[str, Path]]:
        """Stickers of earlier slides for the closing slide: the ones named in `labels`,
        else the best sticker of each earlier slide in turn (cover first)."""
        if labels:
            by_label = {label.lower(): (label, path) for slide in seen for _, label, path in slide}
            picked = [by_label[name.lower()] for name in labels if name.lower() in by_label]
            if picked:
                return picked[:count]
        ranked = [sorted(slide, key=lambda x: -x[0]) for slide in seen if slide]
        out: list[tuple[str, Path]] = []
        for depth in range(max((len(r) for r in ranked), default=0)):
            for r in ranked:
                if depth < len(r) and len(out) < count:
                    out.append(r[depth][1:])
        return out

    paths = []
    for n, slide in enumerate(slides, start=1):
        layout = slide_layout(slides, n - 1)
        print(f"slide {n}/{len(slides)} ({layout}): {slide['title']}")
        seen.append([])
        things = collect(slide.get("items") or [])
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
