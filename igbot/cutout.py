"""Cut the main object out of a photo (rembg, runs on the CPU) and judge the result.

A collage needs clean "sticker" objects: one thing, fully in frame, with a
confident mask. `score` turns that into a number so the best of several
candidate photos can be picked automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from . import photos, relevance

MODEL = "isnet-general-use"
_session = None


def _rembg_session():
    global _session
    if _session is None:
        try:
            from rembg import new_session  # heavy import, only when cutting
        except ImportError as exc:
            raise RuntimeError("chybí rembg: koláže se renderují lokálně "
                               "(pip install -r requirements-render.txt)") from exc
        _session = new_session(MODEL)
    return _session


def remove_background(img: Image.Image) -> Image.Image:
    from rembg import remove
    return remove(img, session=_rembg_session(), post_process_mask=True).convert("RGBA")


def clean(rgba: Image.Image) -> Image.Image:
    """Keep the main object: drop faint alpha and specks, then trim to the object."""
    arr = np.array(rgba)
    alpha = arr[..., 3].astype(np.float32)
    alpha[alpha < 24] = 0
    labels, n = ndimage.label(alpha > 127)
    if n > 1:
        sizes = ndimage.sum(np.ones_like(alpha), labels, range(1, n + 1))
        keep = np.isin(labels, 1 + np.flatnonzero(sizes >= 0.04 * sizes.max()))
        # Soft edge pixels next to a kept part stay; everything else goes.
        near = ndimage.binary_dilation(keep, iterations=3)
        alpha[~near] = 0
    arr[..., 3] = alpha.astype(np.uint8)
    out = Image.fromarray(arr, "RGBA")
    box = out.getchannel("A").getbbox()
    return out.crop(box) if box else out


def score(rgba: Image.Image) -> float:
    """0..1: how usable the cut-out is as a sticker (before `clean`)."""
    a = np.asarray(rgba.getchannel("A"), dtype=np.float32) / 255.0
    fg = a > 0.5
    frac = fg.mean()
    if frac < 0.03 or frac > 0.85:
        return 0.0
    # Objects cut off by the photo's edge look broken as stickers.
    edge = max(2, int(0.01 * min(a.shape)))
    border = np.concatenate([fg[:edge].ravel(), fg[-edge:].ravel(), fg[:, :edge].ravel(), fg[:, -edge:].ravel()])
    border_frac = border.mean()
    labels, n = ndimage.label(fg)
    largest = ndimage.sum(fg, labels, range(1, n + 1)).max() / fg.sum() if n else 0.0
    soft = ((a > 0.1) & (a < 0.9)).sum() / max(1, fg.sum())
    size_fit = 1.0 - min(1.0, abs(frac - 0.35) / 0.5)  # objects filling ~1/3 of the photo cut best
    s = 1.0 - 3.0 * border_frac - 0.5 * (1 - largest) - 1.2 * soft + 0.25 * size_fit - 0.25
    # A mask that fills its bounding box is usually the photo's background kept as a block.
    ys, xs = np.nonzero(fg)
    box_fill = fg.sum() / ((np.ptp(ys) + 1) * (np.ptp(xs) + 1))
    if box_fill > 0.93:
        s -= 0.35
    # Black-and-white or washed-out photos look dead next to colourful ones.
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.float32)[fg] / 255.0
    mx, mn = rgb.max(axis=1), rgb.min(axis=1)
    saturation = float(np.mean((mx - mn) / np.maximum(mx, 1e-3)))
    if saturation < 0.12:
        s -= 0.3 * (1 - saturation / 0.12)
    return float(max(0.0, min(1.0, s)))


def _object_box(rgba: Image.Image) -> tuple[int, int, int, int] | None:
    return rgba.getchannel("A").point(lambda v: 255 if v > 127 else 0).getbbox()


def _hires(cut: Image.Image, full: Image.Image) -> Image.Image | None:
    """Cut the same object again from the full-size photo, cropped around it.

    The preview cut picks the photo; this one gives a sticker sharp enough for
    the slide. Cropping first also lets the model see the object bigger."""
    box = _object_box(cut)
    if not box:
        return None
    sx, sy = full.width / cut.width, full.height / cut.height
    x0, y0, x1, y1 = box
    px, py = (x1 - x0) * 0.12, (y1 - y0) * 0.12
    crop = full.crop((max(0, int((x0 - px) * sx)), max(0, int((y0 - py) * sy)),
                      min(full.width, int((x1 + px) * sx)), min(full.height, int((y1 + py) * sy))))
    if max(crop.size) < max(x1 - x0, y1 - y0) * 1.3:
        return None  # not meaningfully sharper
    hi = remove_background(crop)
    a = np.asarray(hi.getchannel("A"), dtype=np.float32) / 255.0
    fg = (a > 0.5).mean()
    soft = ((a > 0.1) & (a < 0.9)).sum() / max(1, (a > 0.5).sum())
    return hi if 0.12 < fg < 0.97 and soft < 0.35 else None


MIN_SIDE = 320  # px, longer side of a usable sticker
MIN_MATCH = 0.6  # CLIP: below this the photo is more likely a person/scene/artwork than the object


def find_cutout(query: str, cache: Path | None = None, candidates: int = 5,
                good_enough: float = 0.72, exclude: set[str] | None = None, cuts: int = 2) -> dict | None:
    """Best cut-out for `query`: {"path": PNG, "score": .., provenance...}, cached by query.

    Screens up to 2x`candidates` thumbnails with CLIP and cuts out at most `cuts`
    of the best (rembg takes seconds per photo on the Intel Mac)."""
    cache = cache or photos.CACHE / "cutouts"
    png = cache / f"{photos.slug(query)}.png"
    meta_path = png.with_suffix(".json")
    bad = photos.rejected()
    if png.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (not exclude or meta.get("id") not in exclude) and photos.key(meta) not in bad:
            return {**meta, "path": png}
    # Look at more photos than we cut: CLIP on a thumbnail is ~20x cheaper than rembg.
    pool = []
    for cand in photos.search(query, limit=candidates * 2):
        if (exclude and cand.id in exclude) or photos.key(cand) in bad:
            continue
        img = photos.download(cand.preview_url, max_side=1000)
        if img is None:
            continue
        m = relevance.match(img, query)
        if m is not None and m < MIN_MATCH:
            continue  # the photo isn't of the thing (a person, a scene, a painting...)
        pool.append((m, cand, img))
    if pool and pool[0][0] is not None:
        pool.sort(key=lambda p: -p[0])
    best = None
    for m, cand, img in pool[:cuts if pool and pool[0][0] is not None else candidates]:
        cut = remove_background(img)
        s = score(cut)
        box = _object_box(cut)
        # How big the object can get from the full-size photo.
        reach = max(box[2] - box[0], box[3] - box[1]) * max(1.0, (cand.width or img.width) / img.width) if box else 0
        if reach < MIN_SIDE:
            s -= 0.3 * (1 - reach / MIN_SIDE)
        # The cut-out can keep the wrong part of a good photo (the table, not the teapot).
        mc = relevance.match(cut, query)
        if mc is not None:
            s = 0.7 * s + 0.3 * mc - (0.6 if mc < MIN_MATCH else 0)
        if best is None or s > best[0]:
            best = (s, cand, cut, mc)
        if s >= good_enough:
            break
    if best is None:
        return None
    s, cand, cut, mc = best
    if cand.full_url != cand.preview_url:
        full = photos.download(cand.full_url, max_side=1800)
        hi = _hires(cut, full) if full is not None else None
        if hi is not None:
            cut = hi
    final = clean(cut)
    if max(final.size) < MIN_SIDE:  # would look soft on the slide; let the next query win
        s -= 0.4 * (1 - max(final.size) / MIN_SIDE)
    cache.mkdir(parents=True, exist_ok=True)
    final.save(png)
    meta = {**photos.provenance(cand, query), "score": round(s, 3), "size": list(final.size)}
    if mc is not None:
        meta["match"] = round(mc, 3)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**meta, "path": png}


SCENE_MIN = 0.22   # CLIP cosine below which a photo most likely shows something else


def _brightness(img: Image.Image) -> float:
    """0..1: light and colourful (1) versus dark or grey (0)."""
    arr = np.asarray(img.convert("RGB").resize((64, 64)), dtype=np.float32) / 255.0
    lum = float(arr.mean())
    sat = float(np.mean((arr.max(axis=2) - arr.min(axis=2)) / np.maximum(arr.max(axis=2), 1e-3)))
    return max(0.0, min(1.0, 0.6 * min(1.0, lum / 0.55) + 0.4 * min(1.0, sat / 0.35)))


def find_photo(query: str, cache: Path | None = None, candidates: int = 8,
               exclude: set[str] | None = None) -> dict | None:
    """Best rectangular photo for a scene or activity ("lake swimming", "farmers market"):
    {"path": JPEG, "score": .., provenance...}, cached by query. Not cut out: the
    whole picture is the point. Pexels first (sharp, people and landscapes)."""
    cache = cache or photos.CACHE / "photos"
    jpg = cache / f"{photos.slug(query)}.jpg"
    meta_path = jpg.with_suffix(".json")
    bad = photos.rejected()
    if jpg.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (not exclude or meta.get("id") not in exclude) and photos.key(meta) not in bad:
            return {**meta, "path": jpg}
    best = None
    for cand in photos.search(query, limit=candidates):
        if (exclude and cand.id in exclude) or photos.key(cand) in bad:
            continue
        img = photos.download(cand.preview_url, max_side=800)
        if img is None or min(img.size) < 300:
            continue
        sim = relevance.similarity(img, query)
        s = 0.5 if sim is None else max(0.0, min(1.0, (sim - 0.17) / 0.15))
        if sim is not None and sim < SCENE_MIN:
            s *= 0.5
        s += 0.15 * _brightness(img)   # bright, colourful pictures carry a slide; dark ones sink
        if best is None or s > best[0]:
            best = (s, cand, sim)
    if best is None:
        return None
    s, cand, sim = best
    full = photos.download(cand.full_url, max_side=1600) or photos.download(cand.preview_url, max_side=1600)
    if full is None:
        return None
    cache.mkdir(parents=True, exist_ok=True)
    full.save(jpg, "JPEG", quality=92)
    meta = {**photos.provenance(cand, query), "score": round(s, 3), "size": list(full.size)}
    if sim is not None:
        meta["match"] = round(sim, 3)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**meta, "path": jpg}
