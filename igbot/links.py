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
Máš metadata (a pokud jsou, čísla, komentáře a náhledový obrázek nebo screenshoty).
Vysvětli česky: o čem obsah je, jaký má háček (parafrázuj, necituj doslova), formát
a stavbu, proč funguje nebo nefunguje, jak si vede vzhledem k velikosti autora (pokud
čísla chybí, řekni to a nehádej), co prozrazují komentáře o publiku. Pokud podklady
obsahují pole youtube_api_data, čísla z nich nepřepočítávej na poměry ani skóre
a publikum neodhaduj: pravidla YouTube API to bez zvláštního souhlasu nedovolují.
Nakonec navrhni 3 původní nápady pro náš účet v naší nice: stejný princip, ale vlastní
téma, vlastní zpracování a vlastní přidaná hodnota. Nikdy nenavrhuj obsah zkopírovat,
přeložit doslova ani přeposlat. Do missing_data vypiš, co v podkladech chybělo."""

# First path segments on instagram.com that are not usernames.
INSTAGRAM_RESERVED = {"share", "explore", "stories", "accounts", "direct", "about", "developer"}


class FetchError(LookupError):
    """A link could not be read; the message is safe to print (no secrets)."""


# -- URL handling ------------------------------------------------------------

def clean_url(url: str) -> str:
    return url.strip().lstrip("﻿").strip()


def classify(url: str) -> tuple[str, dict]:
    """Return (platform, details) for a link; platform is one of
    youtube, tiktok, instagram_post, instagram_share, instagram_profile or unknown."""
    url = clean_url(url)
    if m := YOUTUBE_ID.search(url):
        return "youtube", {"id": m.group(1)}
    if "tiktok.com" in url:
        m = TIKTOK_VIDEO.search(url)
        return "tiktok", {"author": m.group(1), "id": m.group(2)} if m else {}
    if re.search(r"instagram\.com/share/", url):
        return "instagram_share", {}
    if m := INSTAGRAM_POST.search(url):
        username = m.group(1) if m.group(1) not in INSTAGRAM_RESERVED else None
        return "instagram_post", {"username": username, "shortcode": m.group(2)}
    if (m := INSTAGRAM_PROFILE.search(url)) and m.group(1) not in INSTAGRAM_RESERVED:
        return "instagram_profile", {"username": m.group(1)}
    return "unknown", {}


def resolve_short_link(url: str) -> str:
    """Follow redirects of TikTok share links like vm.tiktok.com/..."""
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


def _get_json(url: str, what: str, **kwargs) -> dict:
    """GET returning JSON; errors never echo the request URL (it may hold a key)."""
    try:
        resp = requests.get(url, timeout=30, **kwargs)
    except requests.RequestException as exc:
        raise FetchError(f"{what}: spojení selhalo ({type(exc).__name__})") from None
    if not resp.ok:
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        raise FetchError(f"{what}: HTTP {resp.status_code} {detail}".strip())
    try:
        return resp.json()
    except ValueError:
        raise FetchError(f"{what}: odpověď není JSON") from None


# -- fetchers ----------------------------------------------------------------

def fetch_youtube(video_id: str, url: str) -> dict:
    """Video metadata. Subscriber counts and comments are not fetched: YouTube's
    developer policies forbid deriving metrics or sentiment from them without a
    separate agreement, and API statistics may only be kept for 30 days."""
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    key = env("YOUTUBE_API_KEY")
    if key:
        try:
            data = _get_json("https://www.googleapis.com/youtube/v3/videos", "YouTube Data API",
                             params={"part": "snippet,statistics,contentDetails", "id": video_id},
                             headers={"x-goog-api-key": key})
        except FetchError as exc:
            print(f"{exc}; zkouším oEmbed")
        else:
            items = data.get("items") or []
            if not items:
                raise FetchError(f"Video {video_id} nenalezeno (soukromé nebo smazané?)")
            v = items[0]
            sn, st = v["snippet"], v.get("statistics", {})
            thumbs = sn.get("thumbnails", {})
            thumb = next((thumbs[k]["url"] for k in ("maxres", "standard", "high", "medium", "default")
                          if k in thumbs), None)
            return {
                "platform": "youtube", "id": video_id, "url": url, "source": "youtube-data-api",
                "author": sn.get("channelTitle"), "title": sn.get("title"),
                "description": (sn.get("description") or "")[:3000], "tags": sn.get("tags", [])[:30],
                "published_at": sn.get("publishedAt"),
                "duration_s": _seconds(v.get("contentDetails", {}).get("duration")),
                "youtube_api_data": {"views": _int(st.get("viewCount")), "likes": _int(st.get("likeCount")),
                                     "comments_count": _int(st.get("commentCount"))},
                "thumbnail_url": thumb,
                "missing": ["přepis videa (YouTube API ho u cizích videí neposkytuje)"],
            }
    info = _oembed("https://www.youtube.com/oembed", canonical, "YouTube oEmbed", extra={"format": "json"})
    info.update(url=url, platform="youtube", id=video_id, source="youtube-oembed",
                missing=["čísla a popis (nastav YOUTUBE_API_KEY pro YouTube Data API)"])
    return info


def fetch_tiktok(url: str, details: dict) -> dict:
    """TikTok's oEmbed is being phased out and often returns only the player, so a
    failure here is not fatal: author and id come from the URL itself."""
    try:
        info = _oembed("https://www.tiktok.com/oembed", url, "TikTok oEmbed")
    except FetchError as exc:
        info = {"url": url, "oembed_error": str(exc)}
    info.update(platform="tiktok", id=details.get("id") or info.get("embed_product_id"),
                source="tiktok-oembed",
                missing=["zhlédnutí, lajky a komentáře (TikTok je cizím aplikacím oficiálně neposkytuje)"])
    info["author"] = info.get("author") or details.get("author")
    if not info.get("title"):
        info["missing"].append("popisek a náhled (oEmbed je už nevrací: přilož screenshot přes --image)")
    return info


def fetch_instagram_post(ig, details: dict, account: str | None, url: str, scan: int = 100) -> dict:
    username = details.get("username") or (account or "").lstrip("@") or None
    if not username:
        raise FetchError("U instagramového odkazu potřebuju autora: přidej --account <uživatel>, "
                         "nebo pošli odkaz ve tvaru instagram.com/<uživatel>/reel/<kód>")
    try:
        profile, posts = ig.account_posts(username, scan)
    except RuntimeError as exc:  # InstagramError: personal/private account, wrong host, …
        raise FetchError(f"Business Discovery pro @{username}: {exc}") from None
    code = details["shortcode"]
    post = next((p for p in posts if p.get("shortcode") == code
                 or f"/{code}/" in (p.get("permalink") or "") + "/"), None)
    if not post:
        raise FetchError(f"Příspěvek {code} není mezi posledními {len(posts)} posty @{username}")
    is_video = post.get("media_type") == "VIDEO"
    thumb = post.get("thumbnail_url") if is_video else post.get("media_url")
    return {
        "platform": "instagram", "id": code, "url": url, "source": "instagram-business-discovery",
        "author": username, "author_followers": profile.get("followers_count"),
        "title": (post.get("caption") or "")[:2200],
        "format": post.get("media_product_type") or post.get("media_type"),
        "published_at": post.get("timestamp"),
        "views": post.get("view_count"), "likes": post.get("like_count"),
        "comments_count": post.get("comments_count"),
        "thumbnail_url": thumb,
        "missing": [] if thumb else ["náhled (API ho pro tento příspěvek nevrátilo)"],
    }


def _oembed(endpoint: str, url: str, what: str, extra: dict | None = None) -> dict:
    data = _get_json(endpoint, what, params={"url": url, **(extra or {})})
    info = {"url": url, "title": data.get("title"), "author": data.get("author_name"),
            "author_url": data.get("author_url"), "thumbnail_url": data.get("thumbnail_url"),
            "embed_product_id": data.get("embed_product_id")}
    return {k: v for k, v in info.items() if v}


def fetch(url: str, ig=None, account: str | None = None) -> dict:
    url = resolve_short_link(clean_url(url))
    platform, details = classify(url)
    if platform == "youtube":
        return fetch_youtube(details["id"], url)
    if platform == "tiktok":
        return fetch_tiktok(url, details)
    if platform == "instagram_share":
        raise FetchError("Odkazy instagram.com/share/… nejdou přečíst bez přihlášení. Otevři příspěvek, "
                         "zkopíruj odkaz instagram.com/p/<kód> nebo /reel/<kód> a přidej --account <autor>")
    if platform == "instagram_post":
        if ig is None:
            raise FetchError("Instagram odkazy potřebují připojený účet (IG_USER_ID, IG_ACCESS_TOKEN)")
        return fetch_instagram_post(ig, details, account, url)
    raise FetchError(f"Nepodporovaný odkaz: {url}")


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
    platform, details = classify(url) if url else ("screenshot", {})
    return {"platform": platform.split("_")[0], "url": url or "(jen screenshot)",
            "id": details.get("id") or details.get("shortcode"), "author": details.get("author")
            or details.get("username"), "source": "screenshot", "missing": [reason] if reason else []}


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


def render(info: dict, a: LinkAnalysis, for_file: bool = False) -> str:
    """Markdown report. YouTube API statistics are shown in the terminal only:
    the YouTube developer policies don't allow keeping them longer than 30 days."""
    def bullets(items):
        return "\n".join(f"- {i}" for i in items) or "- –"

    yt = info.get("youtube_api_data")
    if yt and for_file:
        numbers = "Čísla z YouTube API se neukládají (pravidla YouTube), jsou jen ve výpisu v terminálu."
    else:
        src = yt or info
        numbers = (f"zhlédnutí {_num(src.get('views'))} · lajky {_num(src.get('likes'))} · "
                   f"komentáře {_num(src.get('comments_count'))} · sledující autora {_num(info.get('author_followers'))}")
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
        "_Rozbor a hodnocení napsal Claude; nejde o data dané platformy._", "",
    ])


def _slug(value) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "link")).strip("-")[:60] or "link"


def save(info: dict, a: LinkAnalysis) -> Path:
    today = date.today()
    prune_youtube(today)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{today.isoformat()}-{_slug(info['platform'])}-{_slug(info.get('id'))}"
    path = REPORTS_DIR / f"{base}.md"
    n = 2
    while path.exists():  # same link twice a day, or several screenshot-only reports
        path = REPORTS_DIR / f"{base}-{n}.md"
        n += 1
    path.write_text(render(info, a, for_file=True), encoding="utf-8")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"date": today.isoformat(), "platform": info["platform"], "url": info["url"],
                             "format": a.format, "hook": a.hook, "why_it_works": a.why_it_works,
                             "ideas_for_us": a.ideas_for_us}) + "\n")
    return path


def _read_log() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a broken line must not take down the generator
    return rows


def prune_youtube(today: date, keep_days: int = 30) -> None:
    """Delete YouTube-derived reports and log rows older than 30 days (YouTube
    API developer policies: refresh or delete stored API data after 30 days)."""
    if REPORTS_DIR.exists():
        for path in REPORTS_DIR.glob("*-youtube-*.md"):
            try:
                if (today - date.fromisoformat(path.name[:10])).days > keep_days:
                    path.unlink()
            except ValueError:
                continue
    rows = _read_log()
    kept = [r for r in rows if not (r.get("platform") == "youtube"
                                    and (today - date.fromisoformat(r.get("date", today.isoformat()))).days > keep_days)]
    if len(kept) != len(rows):
        LOG_PATH.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")


def recent_inspections(limit: int = 15) -> list[dict]:
    return _read_log()[-limit:]
