"""Moodboard collage slides: cut-out photo "stickers" around a big serif title.

The technique follows the best-performing format of the niche (10-15 cut-out
objects with small labels around a large title on paper), the look is our own:
kraft paper, white die-cut outlines, title in the middle, colours from
`brand` in config/account.yaml.

Items are placed by a small packer, so any number of objects of any shape fits
without covering the title, the labels or each other. The closing slide lines
its objects up in one row under the call to action.
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

FONT_DIR = ROOT / "assets" / "fonts"
SIZE = (1080, 1350)
GRID = 6  # packer resolution in px


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


def _title_lines(title: str, body: str, style: Style, max_w: float, big: int) -> list[Line]:
    serif = "DMSerifDisplay-Regular.ttf"
    lines: list[Line] = []
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
    width = max(_text_w(l.font, l.text) for l in lines)
    height = sum(l.font.getbbox(l.text)[3] + l.gap_after for l in lines) - lines[-1].gap_after
    return width, height


def _draw_lines(draw, lines: list[Line], x0: float, y0: float, block_w: float) -> None:
    y = y0
    for line in lines:
        draw.text((x0 + (block_w - _text_w(line.font, line.text)) / 2, y), line.text, font=line.font, fill=line.fill)
        y += line.font.getbbox(line.text)[3] + line.gap_after


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


def _prepare(label: str, cut: Image.Image, side: float, style: Style, rnd: random.Random) -> Item:
    w, h = cut.size
    scale = side / (w * h) ** 0.5
    scale = min(scale, side * 1.45 / max(w, h))
    img = cut.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    if style.outline:
        img = _outline(img, style.outline)
    angle = rnd.uniform(-style.max_rotation, style.max_rotation)
    if abs(angle) > 0.3:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    alpha = np.asarray(img.getchannel("A")) > 20
    ys, xs = np.nonzero(alpha)
    obj_bottom, obj_cx = ys.max(), (xs.min() + xs.max()) / 2

    text = _clean(label)
    font = _font(style.label_font, style.label_size)
    lw = _text_w(font, text)
    lh = font.getbbox(text)[3]
    label_top = obj_bottom + (8 if style.outline else 12)
    lx0, ly0 = obj_cx - lw / 2 - 6, label_top - 4
    lx1, ly1 = obj_cx + lw / 2 + 6, label_top + lh + 6

    fx0, fx1 = min(0, int(lx0)), max(img.width, int(np.ceil(lx1)))
    fy1 = max(img.height, int(np.ceil(ly1)))
    g = style.gap
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


def _row(cuts: list[tuple[str, Image.Image]], style: Style, rnd: random.Random,
         top: float, bottom: float, height: float = 300) -> list[Item]:
    """Objects side by side, bottoms on one line, centred in the band [top, bottom]."""
    slot = (SIZE[0] - 2 * style.margin) / len(cuts)
    items = []
    for label, cut in cuts:
        w, h = cut.size
        hh = min(height, (bottom - top) * 0.7, slot * 0.8 * h / w)  # wide objects get less height
        items.append(_prepare(label, cut, hh * (w / h) ** 0.5, style, rnd))
    tallest = max(i.image.height for i in items)
    baseline = (top + bottom + tallest) / 2 - style.label_size - 12
    for k, item in enumerate(items):
        cx = style.margin + slot * (k + 0.5)
        item.pos = (int(cx - item.label_box[0]), int(baseline - item.image.height))
    return items


# --- slides --------------------------------------------------------------

def render_slide(title: str, items: list[tuple[str, Path]], out: Path, style: Style = STYLE,
                 seed: int = 0, handle: str = "", body: str = "", row: bool = False) -> Path:
    """One collage slide; returns the JPEG path.

    row=True lines the objects up in one row under the text (closing slide)
    instead of scattering them around the title."""
    rnd = random.Random(seed)
    W, H = SIZE
    m = style.margin
    slide = paper(SIZE, style.paper, seed=seed, grain=style.grain).convert("RGBA")
    draw = ImageDraw.Draw(slide)
    occ = np.zeros((H // GRID, W // GRID), bool)

    def block(x0, y0, x1, y1, pad=0):
        occ[max(0, int((y0 - pad) // GRID)):int(np.ceil((y1 + pad) / GRID)),
            max(0, int((x0 - pad) // GRID)):int(np.ceil((x1 + pad) / GRID))] = True

    # page frame: keep objects inside the margins
    block(0, 0, W, m); block(0, H - m, W, H); block(0, 0, m, H); block(W - m, 0, W, H)

    lines = _title_lines(_clean(title), _clean(body), style, W - 2 * m - 40, 138)
    tw, th = _measure(lines)
    x0, y0 = (W - tw) / 2, H * (0.36 if row else 0.47) - th / 2
    _draw_lines(draw, lines, x0, y0, tw)
    block(x0, y0, x0 + tw, y0 + th, pad=26)

    if handle:
        tag = f"@{handle}"
        f = _font("Inter-Bold.otf", 24)
        hw = _text_w(f, tag)
        draw.text(((W - hw) / 2, H - m - 14), tag, font=f, fill=style.ink)
        block((W - hw) / 2, H - m - 18, (W + hw) / 2, H, pad=12)

    cuts = [(label, Image.open(path).convert("RGBA")) for label, path in items]
    placed: list[Item] = []
    if cuts and row:
        placed = _row(cuts, style, rnd, y0 + th + 40, H - m - 50)
    elif cuts:
        free_px = (~occ).sum() * GRID * GRID
        side = (free_px * 0.36 / len(cuts)) ** 0.5
        sizes = [side * (1.18 if n == 0 else rnd.uniform(0.86, 1.1)) for n in range(len(cuts))]
        order = sorted(range(len(cuts)), key=lambda n: -sizes[n])
        for n in order:
            label, cut = cuts[n]
            for attempt in range(7):
                item = _prepare(label, cut, sizes[n] * 0.9 ** attempt, style, rnd)
                pos = _place(occ, item.footprint, rnd)
                if pos:
                    gy, gx = pos
                    occ[gy:gy + item.footprint.shape[0], gx:gx + item.footprint.shape[1]] |= item.footprint
                    item.pos = (gx * GRID + item.origin[0], gy * GRID + item.origin[1])
                    placed.append(item)
                    break
            else:
                print(f"  bez místa: {label}")

    if placed:
        dx, dy, blur, opacity = style.shadow
        shadow = Image.new("L", SIZE, 0)
        for item in placed:
            a = item.image.getchannel("A")
            shadow.paste(a, (item.pos[0] + dx, item.pos[1] + dy), a)
        shadow = shadow.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * opacity))
        tint = Image.new("RGBA", SIZE, (52, 36, 22, 255))
        tint.putalpha(shadow)
        slide.alpha_composite(tint)
        rnd.shuffle(placed)  # z-order doesn't follow size
        for item in placed:
            slide.alpha_composite(item.image, item.pos)
        draw = ImageDraw.Draw(slide)
        for item in placed:
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

    slide = {"title": .., "body": .. (closing slide), "items": [{"label": .., "queries": [..]}],
             "row": bool (default: True when the slide has a body)}
    """
    from . import cutout

    find = find or cutout.find_cutout
    used: set[str] = set()
    credits: list[dict] = []

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
            if not best or best["score"] < 0.15:
                print(f"  bez fotky: {spec['label']}")
                continue
            used.add(best["id"])
            credits.append({"label": spec["label"], **{k: v for k, v in best.items() if k != "path"}})
            got.append((spec["label"], Path(best["path"])))
        return got

    paths = []
    for n, slide in enumerate(slides, start=1):
        print(f"slide {n}/{len(slides)}: {slide['title']}")
        body = slide.get("body") or ""
        paths.append(render_slide(slide["title"], collect(slide.get("items") or []), out_dir / name(n), style,
                                  seed=seed + n, handle=handle, body=body, row=slide.get("row", bool(body))))
    return paths, credits


def render_post(plan: dict, out_dir: Path, handle: str = "", style: Style = STYLE,
                find=None, seed: int = 0) -> tuple[list[Path], list[dict]]:
    """A plan file: {"slides": [...], "cta": {"title", "body", "items"}} (cta = closing slide)."""
    slides = list(plan["slides"]) + ([{**plan["cta"], "row": True}] if plan.get("cta") else [])
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
