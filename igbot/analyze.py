"""Analyze an Instagram account: what it posts, what performs and why.

Two sources of posts:

* the official Business Discovery API (`--limit N`): profile stats, captions,
  likes/comments/views and image URLs of a Business/Creator account,
* screenshots (`--images DIR`): anything you saved from the app - a profile
  grid, single posts, reels. Works before the API is connected.

Claude looks at every image together with its metrics, labels topic, format,
hook and visual style, then writes a report: pillars, what works (with links
as evidence), gaps we can fill and a proposed niche profile that the content
generator uses. Images are only cached locally for the analysis (build/ is
not committed); reports describe patterns in our own words.
"""

from __future__ import annotations

import base64
import io
import json
import re
import statistics
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import requests
import yaml
from PIL import Image
from pydantic import BaseModel

from .config import BUILD_DIR, DATA_DIR, ROOT

FALLBACK_BETA = "server-side-fallback-2026-07-01"
REPORTS_DIR = ROOT / "reports"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
BATCH = 8
WEEKDAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]


# -- structured outputs ----------------------------------------------------

class PostLabel(BaseModel):
    ref: str
    topic: str
    pillar: str
    format_style: str
    hook: str
    visual_style: str
    cta: str
    visible_metrics: str
    why_it_works: str


class Labels(BaseModel):
    posts: list[PostLabel]


class Finding(BaseModel):
    insight: str
    evidence: list[str]


class PillarShare(BaseModel):
    name: str
    share: float
    description: str


class NicheProfile(BaseModel):
    name: str
    description: str
    audience: str
    voice: str
    pillars: list[PillarShare]
    formats: list[str]
    avoid: list[str]


class Report(BaseModel):
    summary: str
    audience: str
    voice: str
    pillars: list[PillarShare]
    formats_that_work: list[Finding]
    topics_that_work: list[Finding]
    weak_spots: list[Finding]
    posting_pattern: str
    monetization_signals: list[str]
    opportunities_for_us: list[str]
    similar_account_keywords: list[str]
    niche_profile: NicheProfile


LABEL_SYSTEM = """Analyzuješ obsah instagramového účtu pro konkurenční analýzu. U každého
příspěvku (obrázek + metriky + začátek popisku) urči téma, obsahový pilíř, formát
(např. textový karusel, fotka s nadpisem, recept krok za krokem, talking-head reel,
meme, před/po), háček (parafrázuj vlastními slovy česky, necituj doslova), vizuální
styl (barvy, typografie, fotky vs. grafika), výzvu k akci a proč příspěvek nejspíš
funguje nebo nefunguje. Pokud je obrázek screenshot mřížky profilu, popiš opakující
se vzorce a do visible_metrics napiš čísla, která jsou na screenshotu vidět.
Odpovídej česky. Pole ref zkopíruj přesně z podkladů."""

REPORT_SYSTEM = """Jsi stratég obsahu na Instagramu. Z označených příspěvků a statistik
napiš analýzu účtu v češtině: konkrétně, s čísly a s odkazy (permalinky nebo ref)
jako důkazy. Odliš, co je doložené daty, a co je odhad. Návrhy pro náš účet musí
stavět na vlastním, původním obsahu ve stejné nice: jiný úhel pohledu, lepší
zpracování nebo mezery, které zdrojový účet nepokrývá. Nikdy nenavrhuj kopírování
nebo přeposílání jeho příspěvků ani napodobování jeho značky."""


# -- data collection -------------------------------------------------------

def from_api(ig, username: str, limit: int) -> tuple[dict, list[dict]]:
    profile, raw = ig.account_posts(username, limit)
    followers = profile.get("followers_count") or 0
    posts = []
    for n, m in enumerate(raw, start=1):
        likes, comments = m.get("like_count"), m.get("comments_count")
        engagement = (likes or 0) + (comments or 0)
        posts.append({
            "ref": f"p{n}",
            "permalink": m.get("permalink"),
            "timestamp": m.get("timestamp"),
            "format": m.get("media_product_type") or m.get("media_type"),
            "media_type": m.get("media_type"),
            "caption": m.get("caption") or "",
            "likes": likes, "comments": comments, "views": m.get("view_count"),
            "engagement_rate": round(engagement / followers, 4) if followers else None,
            # Reels: media_url is the video file (and is omitted for licensed audio),
            # so use the thumbnail for the vision step.
            "image_url": m.get("thumbnail_url") if m.get("media_type") == "VIDEO" else m.get("media_url"),
        })
    return profile, posts


def from_images(folder: Path) -> list[dict]:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    return [{"ref": f.name, "image_path": f, "caption": "", "format": "screenshot"} for f in files]


def cache_images(posts: list[dict], cache: Path) -> None:
    """Download post images (video thumbnails for reels) for the vision step."""
    cache.mkdir(parents=True, exist_ok=True)
    for post in posts:
        if post.get("image_path") or not post.get("image_url"):
            continue
        dest = cache / f"{post['ref']}.jpg"
        if not dest.exists():
            try:
                resp = requests.get(post["image_url"], timeout=30)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            except requests.RequestException as exc:
                print(f"obrázek {post['ref']} nestažen: {exc}")
                continue
        post["image_path"] = dest


def _image_block(path: Path) -> dict:
    img = Image.open(path).convert("RGB")
    img.thumbnail((800, 1000))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


# -- statistics ------------------------------------------------------------

def compute_stats(profile: dict, posts: list[dict], tz: str) -> dict:
    with_rate = [p for p in posts if p.get("engagement_rate") is not None]
    if not with_rate:
        return {"posts_analyzed": len(posts), "note": "bez metrik (screenshoty)"}

    by_format: dict[str, list[float]] = {}
    for p in with_rate:
        by_format.setdefault(p["format"], []).append(p["engagement_rate"])

    times = [datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00")).astimezone(ZoneInfo(tz))
             for p in posts if p.get("timestamp")]
    span_days = max(1, (max(times) - min(times)).days) if len(times) > 1 else 1
    hashtags = Counter(t.lower() for p in posts for t in re.findall(r"#(\w+)", p.get("caption", "")))
    lengths = [len(p.get("caption", "")) for p in posts]
    views = [p["views"] for p in posts if p.get("views")]
    ranked = sorted(with_rate, key=lambda p: p["engagement_rate"], reverse=True)

    return {
        "followers": profile.get("followers_count"),
        "media_count": profile.get("media_count"),
        "posts_analyzed": len(posts),
        "posts_per_week": round(len(times) / span_days * 7, 1),
        "median_engagement_rate": round(statistics.median(p["engagement_rate"] for p in with_rate), 4),
        "by_format": {f: {"posts": len(r), "median_engagement_rate": round(statistics.median(r), 4)}
                      for f, r in sorted(by_format.items(), key=lambda kv: -len(kv[1]))},
        "median_views": int(statistics.median(views)) if views else None,
        "weekday_counts": dict(Counter(WEEKDAYS[t.weekday()] for t in times)),
        "hour_counts": dict(sorted(Counter(t.hour for t in times).items())),
        "median_caption_length": int(statistics.median(lengths)) if lengths else 0,
        "top_hashtags": hashtags.most_common(15),
        "top_posts": [{"ref": p["ref"], "permalink": p["permalink"], "format": p["format"],
                       "engagement_rate": p["engagement_rate"], "views": p.get("views")}
                      for p in ranked[:8]],
        "bottom_posts": [{"ref": p["ref"], "permalink": p["permalink"], "format": p["format"],
                          "engagement_rate": p["engagement_rate"]} for p in ranked[-5:]],
    }


# -- Claude ----------------------------------------------------------------

def _call(client, cfg: dict, system: str, content: list[dict], schema):
    gen = cfg.get("generation", {})
    response = client.beta.messages.parse(
        model=gen.get("model", "claude-opus-5-5"),
        max_tokens=32000,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": gen.get("effort", "medium")},
        output_format=schema,
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model odmítl požadavek: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Odpověď se nevešla do max_tokens.")
    return response.parsed_output


def label_posts(client, cfg: dict, posts: list[dict]) -> list[dict]:
    labels = []
    for start in range(0, len(posts), BATCH):
        content: list[dict] = []
        for post in posts[start:start + BATCH]:
            meta = {k: post.get(k) for k in ("ref", "format", "likes", "comments", "views",
                                             "engagement_rate", "timestamp")}
            meta["caption_start"] = post.get("caption", "")[:300]
            content.append({"type": "text", "text": json.dumps(meta, ensure_ascii=False)})
            if post.get("image_path"):
                content.append(_image_block(post["image_path"]))
        content.append({"type": "text", "text": "Označ každý příspěvek výše."})
        labels += [label.model_dump() for label in _call(client, cfg, LABEL_SYSTEM, content, Labels).posts]
        print(f"označeno {min(start + BATCH, len(posts))}/{len(posts)}")
    return labels


def write_report(client, cfg: dict, username: str, profile: dict, stats: dict, labels: list[dict],
                 update_niche_profile: bool = True) -> Path:
    payload = {"ucet": username, "profil": {k: profile.get(k) for k in
                                             ("biography", "website", "followers_count", "media_count")},
               "statistiky": stats, "prispevky": labels}
    report: Report = _call(client, cfg, REPORT_SYSTEM,
                           [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], Report)

    today = date.today().isoformat()
    out_dir = REPORTS_DIR / username
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{today}.json").write_text(json.dumps(
        {"stats": stats, "labels": labels, "report": report.model_dump()}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    if update_niche_profile:
        profile_path = DATA_DIR / "niche_profile.yaml"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(yaml.safe_dump(
            {"source": f"analýza @{username} {today}", **report.niche_profile.model_dump()},
            allow_unicode=True, sort_keys=False), encoding="utf-8")

    md = out_dir / f"{today}.md"
    md.write_text(render_markdown(username, today, stats, report), encoding="utf-8")
    return md


def render_markdown(username: str, today: str, stats: dict, report: Report) -> str:
    def findings(items: list[Finding]) -> str:
        return "\n".join(f"- {f.insight}" + (f" ({', '.join(f.evidence)})" if f.evidence else "")
                         for f in items) or "- (nic)"

    lines = [f"# Analýza @{username} ({today})", "", report.summary, "",
             "## Čísla", ""]
    for key in ("followers", "posts_analyzed", "posts_per_week", "median_engagement_rate",
                "median_views", "median_caption_length"):
        if stats.get(key) is not None:
            lines.append(f"- **{key}**: {stats[key]}")
    if stats.get("by_format"):
        lines += ["", "| Formát | Postů | Medián engagement |", "|---|---|---|"]
        lines += [f"| {f} | {v['posts']} | {v['median_engagement_rate']:.2%} |" for f, v in stats["by_format"].items()]
    lines += ["", "## Publikum a tón", "", f"- **Publikum:** {report.audience}", f"- **Tón:** {report.voice}",
              f"- **Rytmus publikace:** {report.posting_pattern}", "",
              "## Obsahové pilíře", ""]
    lines += [f"- **{p.name}** ({p.share:.0%}): {p.description}" for p in report.pillars]
    lines += ["", "## Formáty, které fungují", "", findings(report.formats_that_work),
              "", "## Témata, která fungují", "", findings(report.topics_that_work),
              "", "## Slabá místa", "", findings(report.weak_spots),
              "", "## Monetizace, kterou účet používá", ""]
    lines += [f"- {m}" for m in report.monetization_signals] or ["- (nic viditelného)"]
    lines += ["", "## Příležitosti pro náš účet", ""]
    lines += [f"- {o}" for o in report.opportunities_for_us]
    lines += ["", "## Klíčová slova pro hledání podobných účtů", "",
              ", ".join(report.similar_account_keywords), "",
              "Navržený profil niky je v JSON reportu (pole niche_profile); u zdrojového účtu se"
              " ukládá i do `data/niche_profile.yaml` pro generátor.", ""]
    return "\n".join(lines)


def run(cfg: dict, username: str, limit: int = 60, images: Path | None = None, ig=None,
        update_niche_profile: bool = True) -> Path:
    tz = cfg["account"]["timezone"]
    if images:
        profile, posts = {}, from_images(images)
    else:
        profile, posts = from_api(ig, username, limit)
        cache_images(posts, BUILD_DIR / "analysis" / username)
    if not posts:
        raise SystemExit("Žádné příspěvky k analýze.")
    stats = compute_stats(profile, posts, tz)
    client = anthropic.Anthropic()
    labels = label_posts(client, cfg, posts)
    return write_report(client, cfg, username, profile, stats, labels, update_niche_profile)
