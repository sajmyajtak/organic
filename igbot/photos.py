"""Find licensed photos for collage items.

Providers, best first:
  pexels     needs PEXELS_API_KEY. Pexels licence: free commercial use,
             modifications allowed, no attribution required.
  openverse  no key. Only CC0 and Public Domain Mark works, which may be used
             commercially without attribution.

Search responses and downloaded images are cached under build/cache, and every
photo keeps its provenance (licence, source page, author) so a post can always
be traced back to the licences of the photos in it.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from PIL import Image

from .config import BUILD_DIR, env

CACHE = BUILD_DIR / "cache"
OPENVERSE = "https://api.openverse.org/v1/images/"
PEXELS = "https://api.pexels.com/v1/search"
UA = {"User-Agent": "naturizz-igbot/1.0 (+https://github.com/sajmyajtak/organic)"}


@dataclass
class Candidate:
    provider: str
    id: str
    preview_url: str   # smaller image, used to score the cut-out
    full_url: str      # bigger image, used for the final cut-out
    license: str
    source: str        # landing page of the photo
    creator: str
    title: str = ""
    keywords: str = ""  # title, tags or alt text, used for the relevance check
    width: int = 0      # width of full_url's image, if known


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _get(url: str, **kwargs) -> requests.Response:
    """GET with one polite retry on rate limiting."""
    for attempt in range(3):
        resp = requests.get(url, timeout=30, **kwargs)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        time.sleep(float(resp.headers.get("Retry-After") or 0) or 5 * (attempt + 1))
    resp.raise_for_status()
    return resp


def _cached_json(name: str, fetch) -> dict:
    path = CACHE / "search" / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _pexels(query: str, limit: int) -> list[Candidate]:
    key = env("PEXELS_API_KEY")
    if not key:
        return []
    data = _cached_json(f"pexels-{slug(query)}", lambda: _get(
        PEXELS, params={"query": query, "per_page": limit}, headers={"Authorization": key, **UA}).json())
    return [Candidate("pexels", str(p["id"]), p["src"]["large"], p["src"]["large2x"], "pexels",
                      p.get("url", ""), p.get("photographer", ""), p.get("alt") or "",
                      keywords=f"{p.get('alt') or ''} {p.get('url', '')}", width=1880)
            for p in data.get("photos", [])[:limit]]


def _openverse(query: str, limit: int) -> list[Candidate]:
    data = _cached_json(f"openverse-{slug(query)}", lambda: _get(
        OPENVERSE, headers=UA, params={"q": query, "license": "cc0,pdm", "category": "photograph",
                                       "page_size": 20, "mature": "false"}).json())
    out = []
    for r in data.get("results", []):
        if min(r.get("width") or 0, r.get("height") or 0) < 400:
            continue
        tags = " ".join(t.get("name", "") for t in r.get("tags") or [])
        out.append(Candidate("openverse", r["id"], r.get("thumbnail") or r["url"], r["url"],
                             r.get("license", ""), r.get("foreign_landing_url") or "",
                             r.get("creator") or "", r.get("title") or "",
                             keywords=f"{r.get('title') or ''} {tags}", width=min(r.get("width") or 0, 1024)))
    return out[:limit]


# Words that describe the shot rather than the object; not required in a match.
FILLER = {"a", "an", "the", "of", "and", "with", "isolated", "fresh", "homemade", "stack", "cup",
          "jar", "basket", "bowl", "mug", "old", "lit", "hot", "pile", "bunch", "close", "up"}


def _stem(word: str) -> str:
    return word[:max(4, len(word) - 3)]


# We want real photos only: AI images would need an "AI info" label.
NOT_PHOTOS = re.compile(r"ai[\s_-]?generated|midjourney|stable[\s_-]?diffusion|dall[\s_-]?e|\bnft\b|"
                        r"illustration|clip[\s_-]?art|drawing|render(ing)?\b|3d\b", re.I)


def relevance(candidate: Candidate, query: str) -> int:
    """0 = reject, 1 = the photo's text names the object, 2 = its title is about it.

    Search engines match loosely ("apple pie" returns pumpkin pies), and a label
    that doesn't match the photo looks careless. The last word is the object and
    must appear; of the other words at least half."""
    if NOT_PHOTOS.search(f"{candidate.title} {candidate.keywords}"):
        return 0
    words = [w for w in re.findall(r"[a-z]+", query.lower()) if w not in FILLER]
    if not words:
        return 1
    text = f"{candidate.title} {candidate.keywords}".lower()
    head, rest = words[-1], words[:-1]
    if _stem(head) not in text or (rest and sum(_stem(w) in text for w in rest) < len(rest) / 2):
        return 0
    title = candidate.title.lower()
    return 2 if " ".join(words) in title and len(title.split()) <= len(words) + 4 else 1


def search(query: str, limit: int = 8) -> list[Candidate]:
    """Relevant candidates from every configured provider, best provider and best match first."""
    found: list[Candidate] = []
    for provider in (_pexels, _openverse):
        try:
            ranked = [(relevance(c, query), c) for c in provider(query, limit * 2)]
            found += [c for r, c in sorted(ranked, key=lambda rc: -rc[0]) if r][:limit]
        except requests.RequestException as exc:  # one provider down shouldn't stop a post
            print(f"  {provider.__name__.lstrip('_')}: {exc}")
    return found


def download(url: str, max_side: int = 1400) -> Image.Image | None:
    """Image from `url` (cached), downscaled so its longer side is <= max_side."""
    path = CACHE / "img" / f"{hashlib.sha1(url.encode()).hexdigest()[:20]}.jpg"
    if path.exists():
        return Image.open(path).convert("RGB")
    try:
        img = Image.open(io.BytesIO(_get(url, headers=UA).content)).convert("RGB")
    except (requests.RequestException, OSError):
        return None
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=92)
    return img


def provenance(candidate: Candidate, query: str) -> dict:
    return {"query": query, **asdict(candidate)}


def save_credits(photos: list[dict], out: Path) -> Path:
    """Licence trail for one post; kept next to the rendered slides."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(photos, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
