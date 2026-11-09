"""Find licensed photos for collage items.

Providers, best first:
  pexels     needs PEXELS_API_KEY. Pexels licence: free commercial use,
             modifications allowed, no attribution required.
  commons    no key. Wikimedia Commons files whose structured data says CC0
             or public domain (museum object photos, CC0 Unsplash imports).
  openverse  no key. Only CC0 and Public Domain Mark works, which may be used
             commercially without attribution. Only stock-photo sources:
             Flickr returned scenes, people and even adult photos for
             everyday words ("wool sweater"), so it is never searched.

Search responses and downloaded images are cached under build/cache, and every
photo keeps its provenance (licence, source page, author) so a post can always
be traced back to the licences of the photos in it. Photos rejected when a
collage was reviewed are listed in data/photo_rejects.txt and never used again.
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

from .config import BUILD_DIR, ROOT, env

CACHE = BUILD_DIR / "cache"
REJECTS = ROOT / "data" / "photo_rejects.txt"
OPENVERSE = "https://api.openverse.org/v1/images/"
OPENVERSE_SOURCES = "stocksnap,wordpress,rawpixel"
PEXELS = "https://api.pexels.com/v1/search"
COMMONS = "https://commons.wikimedia.org/w/api.php"
# Commons structured data: licence CC0 (P275=Q6938433) or copyright status public domain (P6216=Q19652).
COMMONS_FREE = "haswbstatement:P275=Q6938433|P6216=Q19652"
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


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _commons(query: str, limit: int) -> list[Candidate]:
    data = _cached_json(f"commons-{slug(query)}", lambda: _get(COMMONS, headers=UA, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 30,
        "gsrsearch": f"{query} filetype:bitmap {COMMONS_FREE}",
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 800,
        "iiextmetadatafilter": "LicenseShortName|ImageDescription|Categories|Artist"}).json())
    pages = sorted(((data.get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 99))
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licence = (meta.get("LicenseShortName") or {}).get("value", "")
        if not re.search(r"cc0|public domain", licence, re.I):
            continue  # the search filter is a hint, the file page is the truth
        width, height = info.get("width") or 0, info.get("height") or 0
        if min(width, height) < 600 or not info.get("thumburl"):
            continue
        title = p["title"].split(":", 1)[-1].rsplit(".", 1)[0]
        cats = _strip_html((meta.get("Categories") or {}).get("value", "")).replace("|", " ")
        desc = _strip_html((meta.get("ImageDescription") or {}).get("value", ""))[:300]
        # The full image as a ~1800 px thumbnail; Commons can't upscale, so small files are used as is.
        full = info["thumburl"].replace("/800px-", "/1800px-") if width > 1800 else info["url"]
        out.append(Candidate("commons", str(p["pageid"]), info["thumburl"], full, licence,
                             info.get("descriptionurl", ""),
                             _strip_html((meta.get("Artist") or {}).get("value", ""))[:120], title,
                             keywords=f"{title} {cats} {desc}", width=min(width, 1800)))
    return out[:limit]


def _openverse(query: str, limit: int) -> list[Candidate]:
    data = _cached_json(f"openverse-{OPENVERSE_SOURCES.replace(',', '-')}-{slug(query)}", lambda: _get(
        OPENVERSE, headers=UA, params={"q": query, "license": "cc0,pdm", "category": "photograph",
                                       "source": OPENVERSE_SOURCES, "page_size": 20, "mature": "false"}).json())
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
                        r"illustration|clip[\s_-]?art|drawing|render(ing)?\b|3d\b|"
                        # artworks and documents in museum/archive collections (Commons, rawpixel)
                        r"painting|watercolou?r|engraving|lithograph|etching|woodcut|herbarium|botanical|"
                        r"\bplate \d|köhler|\bmaps?\b|diagram|poster|advert|\blogo\b|\bicon\b|shader|"
                        r"\bNGA\b|\(c\. ?\d{4}|\bc\. ?1[0-9]{3}\b|nude|nudity|erotic|sexy", re.I)


# Product shots of a brand: logos on a sticker read as an ad (or a trademark problem).
# Commons titles name the brand ("Umbro slippers", "Barnes Naturals Apple Cider Vinegar").
BRANDS = re.compile(r"\b(nike|adidas|umbro|puma|reebok|converse|vans|new balance|ugg|crocs|ikea|starbucks|"
                    r"coca[\s-]?cola|pepsi|nestl[eé]|heinz|kellogg|lindt|cadbury|nutella|barnes naturals|"
                    r"bragg|lego|apple inc|samsung|walmart|costco|target|amazon|sony|philips|braun|bosch|"
                    r"kitchenaid|nespresso|keurig|lavazza|kerrygold|droste|bretel|equal exchange|jeno'?s|"
                    r"gail'?s|for sale|brand|ads?|®|™)\b", re.I)


def relevance(candidate: Candidate, query: str) -> int:
    """0 = reject, 1 = the photo's text names the object, 2 = its title is about it.

    Search engines match loosely ("apple pie" returns pumpkin pies), and a label
    that doesn't match the photo looks careless. The last word is the object and
    must appear; of the other words at least half."""
    if NOT_PHOTOS.search(f"{candidate.title} {candidate.keywords}") or BRANDS.search(candidate.title):
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
    for provider in (_pexels, _commons, _openverse):
        if len(found) >= max(3, limit // 2):
            break  # Pexels gave enough: the free archives are slower and rougher
        try:
            ranked = [(relevance(c, query), c) for c in provider(query, limit * 2)]
            found += [c for r, c in sorted(ranked, key=lambda rc: -rc[0]) if r][:limit]
        except requests.RequestException as exc:  # one provider down shouldn't stop a post
            print(f"  {provider.__name__.lstrip('_')}: {str(exc)[:80]}")
    return found


def key(candidate_or_meta) -> str:
    """"provider:id", the form used in data/photo_rejects.txt."""
    get = candidate_or_meta.get if isinstance(candidate_or_meta, dict) else lambda k: getattr(candidate_or_meta, k)
    return f"{get('provider')}:{get('id')}"


def rejected() -> set[str]:
    """Photos thrown out when a collage was reviewed ("provider:id  # why" per line)."""
    if not REJECTS.exists():
        return set()
    lines = (line.split("#", 1)[0].strip() for line in REJECTS.read_text(encoding="utf-8").splitlines())
    return {line for line in lines if line}


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
