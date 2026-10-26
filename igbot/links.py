"""Inspect single Instagram / TikTok / YouTube links through official endpoints.

What each platform gives us without logging in or getting around bot checks:

* YouTube: Data API v3 when YOUTUBE_API_KEY is set (title, description, tags,
  duration, views, likes, comment count, channel subscribers, top comments),
  otherwise the public oEmbed endpoint (title, channel, thumbnail).
* TikTok: the public oEmbed endpoint. Since 2026 it returns only the embed
  player (no caption, no thumbnail) and TikTok offers no official way to read
  other people's videos, so attach a screenshot (--image) or a note (--note).
* Instagram: Business Discovery via our connected account (caption, likes,
  comments, views, image). Needs the author's username, which is in newer
  share links or can be passed with --account. Instagram's own oEmbed is not
  used: Meta forbids using its data for analytics.

Any link can carry screenshots and a note; they fill whatever the endpoint
doesn't return (numbers, caption, what happens in the video).

Claude then explains the content (hook, format, structure, why it works) and
proposes original ideas for our niche. Reports go to reports/links/ and a
compact summary to data/inspected_links.jsonl, which the generator reads.
"""

from __future__ import annotations

import base64
import io
import json
import re
from datetime import date
from pathlib import Path

import anthropic
import requests
from PIL import Image
from pydantic import BaseModel

from .config import DATA_DIR, ROOT, env

FALLBACK_BETA = "server-side-fallback-2026-07-01"
REPORTS_DIR = ROOT / "reports" / "links"
LOG_PATH = DATA_DIR / "inspected_links.jsonl"

YOUTUBE_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})")
TIKTOK_VIDEO = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)/(?:video|photo)/(\d+)")
INSTAGRAM_POST = re.compile(r"instagram\.com/(?:([A-Za-z0-9_.]+)/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
INSTAGRAM_PROFILE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)/?(?:[?#].*)?$")
ISO_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


class LinkAnalysis(BaseModel):
    summary: str
    hook: str
    format: str
    structure: list[str]
    why_it_works: list[str]
    performance_read: str
    audience_signals: list[str]
    ideas_for_us: list[str]
    missing_data: list[str]


SYSTEM = """Rozebíráš jeden příspěvek ze sociální sítě pro tvůrce českého Instagram účtu.
Máš metadata (a pokud jsou, čísla, komentáře a náhledový obrázek). Vysvětli česky:
o čem obsah je, jaký má háček (parafrázuj, necituj doslova), formát a stavbu,
proč funguje nebo nefunguje, jak si vede vzhledem k velikosti autora (pokud čísla
chybí, řekni to a nehádej), co prozrazují komentáře o publiku. Nakonec navrhni
3 původní nápady pro náš účet v naší nice: stejný princip, ale vlastní téma,
vlastní zpracování a vlastní přidaná hodnota. Nikdy nenavrhuj obsah zkopírovat,
přeložit doslova ani přeposlat. Do missing_data vypiš, co v podkladech chybělo."""


# -- URL handling ------------------------------------------------------------

def classify(url: str) -> tuple[str, dict]:
    """Return (platform, details) for a link; platform is one of
    youtube, tiktok, instagram_post, instagram_profile or unknown."""
    url = url.strip()
    if m := YOUTUBE_ID.search(url):
        return "youtube", {"id": m.group(1)}
    if "tiktok.com" in url:
        m = TIKTOK_VIDEO.search(url)
        return "tiktok", {"author": m.group(1), "id": m.group(2)} if m else {}
    if m := INSTAGRAM_POST.search(url):
        return "instagram_post", {"username": m.group(1), "shortcode": m.group(2)}
    if m := INSTAGRAM_PROFILE.search(url):
        return "instagram_profile", {"username": m.group(1)}
    return "unknown", {}


def resolve_short_link(url: str) -> str:
    """Follow redirects of share links like vm.tiktok.com/... or youtu.be shorteners."""
    if not re.search(r"//(vm|vt)\.tiktok\.com/|//www\.tiktok\.com/t/", url):
        return url
    try:
        return requests.head(url, allow_redirects=True, timeout=20).url
    except requests.RequestException:
        return url


def _seconds(iso: str | None) -> int | None:
    m = ISO_DURATION.fullmatch(iso or "")
    if not m or not iso:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def _int(value) -> int | None:
    return int(value) if value not in (None, "") else None


# -- fetchers ----------------------------------------------------------------

def fetch_youtube(video_id: str, url: str, comments: bool = True) -> dict:
    key = env("YOUTUBE_API_KEY")
    if not key:
        info = _oembed("https://www.youtube.com/oembed", url, extra={"format": "json"})
        info.update(platform="youtube", id=video_id, source="youtube-oembed",
                    missing=["čísla, popis a komentáře (nastav YOUTUBE_API_KEY pro YouTube Data API)"])
        return info

    api = "https://www.googleapis.com/youtube/v3"
    resp = requests.get(f"{api}/videos", params={"part": "snippet,statistics,contentDetails",
                                                 "id": video_id, "key": key}, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("items") or []
    if not items:
        raise LookupError(f"Video {video_id} nenalezeno (soukromé nebo smazané?)")
    v = items[0]
    sn, st = v["snippet"], v.get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    thumb = next((thumbs[k]["url"] for k in ("maxres", "standard", "high", "medium", "default") if k in thumbs), None)
    info = {
        "platform": "youtube", "id": video_id, "url": url, "source": "youtube-data-api",
        "author": sn.get("channelTitle"), "title": sn.get("title"),
        "description": (sn.get("description") or "")[:3000], "tags": sn.get("tags", [])[:30],
        "published_at": sn.get("publishedAt"),
        "duration_s": _seconds(v.get("contentDetails", {}).get("duration")),
        "views": _int(st.get("viewCount")), "likes": _int(st.get("likeCount")),
        "comments_count": _int(st.get("commentCount")), "thumbnail_url": thumb, "missing": [],
    }
    ch = requests.get(f"{api}/channels", params={"part": "statistics", "id": sn.get("channelId"), "key": key},
                      timeout=30)
    if ch.ok and ch.json().get("items"):
        stats = ch.json()["items"][0].get("statistics", {})
        info["author_followers"] = _int(stats.get("subscriberCount"))
    if comments:
        ct = requests.get(f"{api}/commentThreads", params={
            "part": "snippet", "videoId": video_id, "order": "relevance", "maxResults": 20,
            "textFormat": "plainText", "key": key}, timeout=30)
        if ct.ok:
            info["top_comments"] = [
                {"text": c["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:300],
                 "likes": c["snippet"]["topLevelComment"]["snippet"].get("likeCount")}
                for c in ct.json().get("items", [])]
        else:
            info["missing"].append("komentáře (vypnuté nebo nedostupné)")
    info["missing"].append("přepis videa (YouTube API ho u cizích videí neposkytuje)")
    return info


def fetch_tiktok(url: str, details: dict) -> dict:
    info = _oembed("https://www.tiktok.com/oembed", url)
    info.update(platform="tiktok", id=details.get("id") or info.get("embed_product_id"),
                source="tiktok-oembed",
                missing=["zhlédnutí, lajky a komentáře (TikTok je cizím aplikacím oficiálně neposkytuje)"])
    info["author"] = info.get("author") or details.get("author")
    if not info.get("title"):
        info["missing"].append("popisek a náhled (oEmbed je už nevrací: přilož screenshot přes --image)")
    return info


def fetch_instagram_post(ig, details: dict, account: str | None, url: str, scan: int = 100) -> dict:
    username = details.get("username") or account
    if not username:
        raise LookupError("U instagramového odkazu potřebuju autora: přidej --account <uživatel>, "
                          "nebo pošli odkaz ve tvaru instagram.com/<uživatel>/reel/<kód>")
    profile, posts = ig.account_posts(username, scan)
    code = details["shortcode"]
    post = next((p for p in posts if f"/{code}" in (p.get("permalink") or "")), None)
    if not post:
        raise LookupError(f"Příspěvek {code} není mezi posledními {len(posts)} posty @{username}")
    return {
        "platform": "instagram", "id": code, "url": url, "source": "instagram-business-discovery",
        "author": username, "author_followers": profile.get("followers_count"),
        "title": (post.get("caption") or "")[:2200],
        "format": post.get("media_product_type") or post.get("media_type"),
        "published_at": post.get("timestamp"),
        "views": post.get("view_count"), "likes": post.get("like_count"),
        "comments_count": post.get("comments_count"),
        "thumbnail_url": post.get("media_url") if post.get("media_type") != "VIDEO" else None,
        "missing": [] if post.get("media_type") != "VIDEO" else ["náhled videa (API dává jen soubor videa)"],
    }


def _oembed(endpoint: str, url: str, extra: dict | None = None) -> dict:
    resp = requests.get(endpoint, params={"url": url, **(extra or {})}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    info = {"url": url, "title": data.get("title"), "author": data.get("author_name"),
            "author_url": data.get("author_url"), "thumbnail_url": data.get("thumbnail_url"),
            "embed_product_id": data.get("embed_product_id")}
    return {k: v for k, v in info.items() if v}


def fetch(url: str, ig=None, account: str | None = None) -> dict:
    url = resolve_short_link(url)
    platform, details = classify(url)
    if platform == "youtube":
        return fetch_youtube(details["id"], url)
    if platform == "tiktok":
        return fetch_tiktok(url, details)
    if platform == "instagram_post":
        if ig is None:
            raise LookupError("Instagram odkazy potřebují připojený účet (IG_USER_ID, IG_ACCESS_TOKEN)")
        return fetch_instagram_post(ig, details, account, url)
    raise LookupError(f"Nepodporovaný odkaz: {url}")


# -- analysis ----------------------------------------------------------------

def _image_block(img: Image.Image) -> dict:
    img = img.convert("RGB")
    img.thumbnail((1000, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def _thumbnail_block(url: str | None) -> dict | None:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return _image_block(Image.open(io.BytesIO(resp.content)))
    except (requests.RequestException, OSError):
        return None


def screenshot_only(url: str, reason: str) -> dict:
    """Info for a link we couldn't fetch, to be analyzed from attached screenshots."""
    platform = classify(url)[0] if url else "screenshot"
    return {"platform": platform.split("_")[0], "url": url or "(jen screenshot)",
            "source": "screenshot", "missing": [reason] if reason else []}


def analyze(info: dict, cfg: dict, client=None, images: list[Path] | None = None,
            note: str | None = None) -> LinkAnalysis:
    client = client or anthropic.Anthropic()
    gen = cfg.get("generation", {})
    payload = {k: v for k, v in info.items() if k != "thumbnail_url"}
    if note:
        payload["poznamka_od_uzivatele"] = note
    if images:
        payload["prilozene_screenshoty"] = len(images)
    content: list[dict] = [{"type": "text", "text": json.dumps(
        {"nase_nika": cfg.get("niche", {}), "prispevek": payload}, ensure_ascii=False)}]
    if block := _thumbnail_block(info.get("thumbnail_url")):
        content.append(block)
    for path in images or []:
        content.append(_image_block(Image.open(path)))
    response = client.beta.messages.parse(
        model=gen.get("model", "claude-opus-5-5"),
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": gen.get("effort", "medium")},
        output_format=LinkAnalysis,
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model odmítl požadavek: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Odpověď se nevešla do max_tokens.")
    return response.parsed_output


def _num(n) -> str:
    return f"{n:,}".replace(",", " ") if isinstance(n, int) else "–"


def render(info: dict, a: LinkAnalysis) -> str:
    def bullets(items):
        return "\n".join(f"- {i}" for i in items) or "- –"

    numbers = (f"zhlédnutí {_num(info.get('views'))} · lajky {_num(info.get('likes'))} · "
               f"komentáře {_num(info.get('comments_count'))} · sledující autora {_num(info.get('author_followers'))}")
    return "\n".join([
        f"# {info['platform'].capitalize()}: {info.get('author') or 'neznámý autor'}", "",
        f"{info['url']}  ",
        f"Zdroj dat: {info['source']} · staženo {date.today().isoformat()}  ",
        numbers, "",
        a.summary, "",
        f"**Háček:** {a.hook}  ", f"**Formát:** {a.format}", "",
        "## Stavba", bullets(a.structure), "",
        "## Proč to funguje", bullets(a.why_it_works), "",
        "## Výkon", a.performance_read, "",
        "## Publikum (z komentářů)", bullets(a.audience_signals), "",
        "## Nápady pro náš účet", bullets(a.ideas_for_us), "",
        "## Chybějící data", bullets(a.missing_data + info.get("missing", [])), "",
    ])


def save(info: dict, a: LinkAnalysis, text: str) -> Path:
    today = date.today().isoformat()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{today}-{info['platform']}-{info.get('id') or 'link'}.md"
    path.write_text(text, encoding="utf-8")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"date": today, "platform": info["platform"], "url": info["url"],
                             "format": a.format, "hook": a.hook, "why_it_works": a.why_it_works,
                             "ideas_for_us": a.ideas_for_us}, ensure_ascii=False) + "\n")
    return path


def recent_inspections(limit: int = 15) -> list[dict]:
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in lines if line.strip()]
