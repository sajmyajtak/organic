"""Render original post graphics (carousel slides, single images, stories) with Pillow.

Instagram's publishing API only accepts JPEG images, so everything is saved as
JPEG. Sizes follow Instagram's recommended ratios: 4:5 portrait for feed
(1080x1350) and 9:16 for stories (1080x1920).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"

FEED_SIZE = (1080, 1350)
STORY_SIZE = (1080, 1920)


@dataclass
class Theme:
    background: str = "#F4F1EA"
    foreground: str = "#1F2A1F"
    accent: str = "#4E7D3A"
    muted: str = "#6B6B5E"
    handle: str = ""

    @classmethod
    def from_config(cls, cfg: dict) -> "Theme":
        brand = cfg.get("brand", {})
        return cls(
            background=brand.get("background", cls.background),
            foreground=brand.get("foreground", cls.foreground),
            accent=brand.get("accent", cls.accent),
            muted=brand.get("muted", cls.muted),
            handle=cfg.get("account", {}).get("handle", ""),
        )


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "Inter-Bold.otf" if bold else "Inter-Regular.otf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _clean(text: str) -> str:
    """Drop emoji and joiners: the bundled font has no glyphs for them."""
    return "".join(ch for ch in text if ord(ch) < 0x1F000 and not 0xFE00 <= ord(ch) <= 0xFE0F
                   and ch != "\u200d").strip()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if draw.textlength(candidate, font=font) <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _fit_block(draw, text: str, max_width: int, max_height: int, start: int, minimum: int, bold: bool):
    """Pick the largest font size (down to `minimum`) at which `text` fits the box."""
    size = start
    while True:
        font = _font(size, bold)
        lines = _wrap(draw, text, font, max_width)
        line_height = int(size * 1.25)
        if len(lines) * line_height <= max_height or size <= minimum:
            return font, lines, line_height
        size -= 4


def _background(size: tuple[int, int], theme: Theme, photo: Path | None) -> Image.Image:
    """Plain brand background, or a cover-cropped photo darkened for legible text."""
    if not photo:
        return Image.new("RGB", size, theme.background)
    src = Image.open(photo).convert("RGB")
    scale = max(size[0] / src.width, size[1] / src.height)
    src = src.resize((round(src.width * scale), round(src.height * scale)))
    left = (src.width - size[0]) // 2
    top = (src.height - size[1]) // 2
    src = src.crop((left, top, left + size[0], top + size[1]))
    return Image.blend(src, Image.new("RGB", size, "#000000"), 0.45)


def render_slide(
    slide: dict,
    out_path: Path,
    theme: Theme,
    size: tuple[int, int] = FEED_SIZE,
    index: int | None = None,
    total: int | None = None,
) -> Path:
    """Render one slide dict ({title, body, footer?, photo?}) to a JPEG file.

    `photo` is an optional path (relative to the repo root) to an original or
    licensed photo used as the background.
    """
    width, height = size
    is_story = size == STORY_SIZE
    margin = 96
    photo = ROOT / slide["photo"] if slide.get("photo") else None
    img = _background(size, theme, photo)
    draw = ImageDraw.Draw(img)
    fg = "#FFFFFF" if photo else theme.foreground

    # Stories: keep text out of the areas covered by Instagram's own UI
    # (profile bar at the top, reply bar at the bottom).
    top = 300 if is_story else margin + 80
    bottom_reserved = 380 if is_story else 170
    text_width = width - 2 * margin
    available = height - top - bottom_reserved

    title = _clean(slide.get("title") or "")
    body = _clean(slide.get("body") or "")

    blocks = []
    if title:
        title_box = available if not body else int(available * 0.45)
        blocks.append(_fit_block(draw, title, text_width, title_box, 96 if not body else 88, 48, bold=True))
    if body:
        used = sum(len(lines) * lh for _, lines, lh in blocks) + (40 if blocks else 0)
        blocks.append(_fit_block(draw, body, text_width, available - used, 52, 30, bold=False))

    content_height = sum(len(lines) * lh for _, lines, lh in blocks) + 40 * (len(blocks) - 1)
    # Cover slides and stories read better centered; content slides start at the top.
    centered = is_story or not body
    y = top + max(0, (available - content_height) // 2) if centered else top

    accent_y = y - 60 if centered else margin
    draw.rectangle([margin, accent_y, margin + 120, accent_y + 14], fill=theme.accent)

    for n, (font, lines, lh) in enumerate(blocks):
        for line in lines:
            draw.text((margin, y), line, font=font, fill=fg)
            y += lh
        if n < len(blocks) - 1:
            y += 40

    footer_font = _font(34, bold=True)
    footer_y = height - (bottom_reserved - 60 if is_story else margin + 34)
    if theme.handle:
        draw.text((margin, footer_y), f"@{theme.handle}", font=footer_font, fill="#E6E6E6" if photo else theme.muted)
    footer = slide.get("footer")
    if index is not None and total and total > 1:
        footer = footer or f"{index}/{total}" + ("  →" if index < total else "")
    if footer:
        w = draw.textlength(footer, font=footer_font)
        draw.text((width - margin - w, footer_y), footer, font=footer_font, fill=theme.accent)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92, optimize=True)
    return out_path


def render_item(item: dict, out_dir: Path, theme: Theme) -> list[Path]:
    """Render all images for a content item; returns paths in publishing order."""
    kind = item["kind"]
    slides = item.get("slides") or []
    if not slides:
        return []
    size = STORY_SIZE if kind == "story" else FEED_SIZE
    total = len(slides)
    return [
        render_slide(slide, out_dir / f"{item['id']}-{i}.jpg", theme, size, i, total)
        for i, slide in enumerate(slides, start=1)
    ]
