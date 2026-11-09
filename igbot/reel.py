"""A carousel as a Reel: the slides swipe by like a carousel, music comes from Instagram.

Instagram attaches music (Audio API, `audio_configuration`) only to Reels, not
to carousels, so a post goes out as a short video of its own slides: each
slide as a card on a dark background, swiping to the next one like a carousel,
with the carousel dots underneath and the edge of the next card peeking in.
The video itself is silent (a quiet AAC track keeps every player happy); the
song is added by Instagram when the Reel is created.

1080x1920 (9:16), H.264 + AAC, 30 fps, moov atom first: what the Reels API
asks for. The card sits a little above the middle: the bottom of the screen
is covered by the caption and buttons in the Reels player, and the profile
grid shows the middle 3:4.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import collage

W, H = 1080, 1920
FPS = 30
CARD_W = 960
GAP = 36                 # between cards; the next card's edge peeks in on the right
RADIUS = 30
CARD_TOP = 250
HOLD_FIRST, HOLD, HOLD_LAST = 2.6, 2.2, 3.2   # seconds on the cover, inner slides, closing slide
SWIPE = 0.5


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _ease(t: float) -> float:
    """easeInOutCubic: a finger swipe, slow - fast - slow."""
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _card(slide: Image.Image) -> tuple[Image.Image, int]:
    """The slide with rounded corners and a soft shadow; returns (tile, margin around the card)."""
    h = round(slide.height * CARD_W / slide.width)
    img = slide.convert("RGB").resize((CARD_W, h), Image.LANCZOS)
    mask = Image.new("L", (CARD_W * 3, h * 3), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W * 3 - 1, h * 3 - 1], RADIUS * 3, fill=255)
    mask = mask.resize((CARD_W, h), Image.LANCZOS)
    m = 60
    size = (CARD_W + 2 * m, h + 2 * m)
    shadow = Image.new("L", size, 0)
    shadow.paste(mask, (m, m + 14))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22)).point(lambda v: int(v * 0.55))
    tile = Image.merge("RGBA", (*Image.new("RGB", size, (8, 4, 2)).split(), shadow))
    card = img.convert("RGBA")
    card.putalpha(mask)
    tile.alpha_composite(card, (m, m))
    return tile, m


def _background(brand: dict) -> Image.Image:
    dark = brand.get("foreground", "#3A2517")
    return collage.paper((W, H), dark, seed=11, grain=0.5).convert("RGB")


def timeline(n: int) -> list[float]:
    """Carousel position (0 = first slide) for every frame."""
    pos: list[float] = []
    for i in range(n):
        hold = HOLD_FIRST if i == 0 else HOLD_LAST if i == n - 1 else HOLD
        pos += [float(i)] * round(hold * FPS)
        if i < n - 1:
            steps = round(SWIPE * FPS)
            pos += [i + _ease((k + 1) / steps) for k in range(steps)]
    return pos


def frames(slides: list[Image.Image], brand: dict):
    """Every frame of the reel as an RGB array."""
    bg = _background(brand).convert("RGBA")
    cards = [_card(s) for s in slides]
    card_h = cards[0][0].height - 2 * cards[0][1]
    dots_y = CARD_TOP + card_h + 56
    dark, light = _hex(brand.get("foreground", "#3A2517")), _hex(brand.get("background", "#E5D5BA"))
    left = (W - CARD_W) // 2
    step = CARD_W + GAP
    n = len(slides)
    last_p, last = None, None
    for p in timeline(n):
        if p == last_p:      # holding on a slide: the same frame again
            yield last
            continue
        frame = bg.copy()
        for i, (tile, m) in enumerate(cards):
            x = left + round((i - p) * step)
            if x + CARD_W < -m or x > W + m:
                continue
            _paste(frame, tile, x - m, CARD_TOP - m)
        if n > 1:
            d = ImageDraw.Draw(frame)
            r, gap = 9, 30
            x0 = W / 2 - (n - 1) * gap / 2
            for i in range(n):
                near = max(0.0, 1 - abs(i - p))          # the active dot grows and lights up
                rad = r * (0.75 + 0.35 * near)
                mix = 0.35 + 0.65 * near
                col = tuple(round(dark[c] + (light[c] - dark[c]) * mix) for c in range(3))
                cx = x0 + i * gap
                d.ellipse([cx - rad, dots_y - rad, cx + rad, dots_y + rad], fill=(*col, 255))
        last_p, last = p, np.asarray(frame.convert("RGB"))
        yield last


def _paste(frame: Image.Image, tile: Image.Image, x: int, y: int) -> None:
    """alpha_composite refuses negative offsets and overhangs; paste only the part on screen."""
    x0, x1 = max(0, -x), min(tile.width, frame.width - x)
    if x1 > x0:
        frame.alpha_composite(tile.crop((x0, 0, x1, tile.height)), (x + x0, y))


def render(slides: list[Path | Image.Image], out: Path, brand: dict) -> Path:
    """Write the reel to `out` (.mp4) and return it."""
    images = [s if isinstance(s, Image.Image) else Image.open(s) for s in slides]
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_ffmpeg(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-shortest", "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
           "-preset", "slow", "-crf", "23", "-tune", "stillimage", "-g", str(FPS * 5),
           "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for frame in frames(images, brand):
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg skončil s chybou {proc.returncode}")
    return out


def cover(slides: list[Path | Image.Image], out: Path, brand: dict) -> Path:
    """The first frame as the Reel's cover image (shown before playback and in the grid)."""
    images = [s if isinstance(s, Image.Image) else Image.open(s) for s in slides]
    first = next(frames(images, brand))
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(first).save(out, "JPEG", quality=92)
    return out


def duration(n: int) -> float:
    return len(timeline(n)) / FPS
