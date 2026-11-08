"""Content queue stored as YAML files in git.

    content/drafts/     generated, waiting for a human to approve
    content/approved/   scheduled; the publisher posts them when due
    content/published/  done (keeps the Instagram media id for analytics)
    content/failed/     publishing failed; see the `error` field

Moving a file between folders is the whole workflow, so it can be done from
the GitHub web UI or phone as well as with `python -m igbot approve`.
"""

from __future__ import annotations

from datetime import datetime
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .config import CONTENT_DIR

STATES = ("drafts", "approved", "published", "failed")
KINDS = ("carousel", "image", "story", "reel")
TIMED = ("story", "reel")  # published at their own date/time; feed posts go to the pool


def folder(state: str) -> Path:
    path = CONTENT_DIR / state
    path.mkdir(parents=True, exist_ok=True)
    return path


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        item = yaml.safe_load(fh)
    item["_path"] = path
    return item


def save(item: dict, state: str) -> Path:
    data = {k: v for k, v in item.items() if not k.startswith("_")}
    dest = folder(state) / f"{data['id']}.yaml"
    with open(dest, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False, width=100)
    old = item.get("_path")
    if old and Path(old) != dest and Path(old).exists():
        Path(old).unlink()
    item["_path"] = dest
    return dest


def exists(item_id: str) -> bool:
    return any((folder(state) / f"{item_id}.yaml").exists() for state in STATES)


def items(state: str) -> list[dict]:
    return sorted((load(p) for p in folder(state).glob("*.yaml")),
                  key=lambda i: (str(i.get("date") or ""), str(i.get("time") or ""), i["id"]))


def scheduled_at(item: dict, tz: str) -> datetime:
    return datetime.fromisoformat(f"{item['date']}T{item['time']}").replace(tzinfo=ZoneInfo(tz))


def due(tz: str, now: datetime | None = None) -> list[dict]:
    """Approved items with a fixed slot that has come (stories, reels). Feed posts
    have no slot: scheduler.plan picks them from the pool."""
    now = now or datetime.now(ZoneInfo(tz))
    return [i for i in items("approved") if i["kind"] in TIMED and i.get("date") and i.get("time")
            and scheduled_at(i, tz) <= now]


MAX_HASHTAGS = 5  # Instagram's cap since Dec 2025; the API docs still say 30
HASHTAG = re.compile(r"#\w*[^\W\d_]\w*")  # needs a letter, so "#1" in a list doesn't count
# Disclosure has to open the post, in the post's language (ČOI's position as
# reported by law firms; the FTC likewise wants it up front).
AD_LABEL = re.compile(r"(#?reklama|placené partnerství|sponzorovaný obsah|#?ad|#?advertisement"
                      r"|paid partnership|sponsored)(?!\w)")
AI_DISCLOSURE = {"cs": "Vytvořeno s pomocí AI.", "en": "Created with the help of AI."}
MISSING_VIDEO = "chybí video: natoč ho podle scénáře a připoj přes `igbot attach`"


def validate(item: dict) -> list[str]:
    """Return a list of problems that would make Instagram reject the item."""
    problems = []
    kind = item.get("kind")
    if kind not in KINDS:
        problems.append(f"neznámý typ '{kind}'")
    caption = item.get("caption") or ""
    if kind != "story":
        full = full_caption(item)
        if len(full) > 2200:
            problems.append(f"popisek má {len(full)} znaků (max 2200)")
        if len(HASHTAG.findall(full)) > MAX_HASHTAGS:
            problems.append(f"víc než {MAX_HASHTAGS} hashtagů")
        if full.count("@") > 20:
            problems.append("víc než 20 zmínek @")
        if not caption.strip():
            problems.append("chybí popisek")
    slides = item.get("slides") or []
    media = item.get("media") or []
    if kind == "reel":
        if not media:
            problems.append(MISSING_VIDEO)
    elif not slides and not media:
        problems.append("chybí slidy i média")
    if kind in ("carousel", "image") and not media and any(s.get("items") for s in slides):
        for n, slide in enumerate(slides, start=1):
            things = slide.get("items") or []
            role = slide_layout(slides, n - 1)
            if role == "cta":
                if len(things) > 8:
                    problems.append(f"slide {n}: závěrečný slide má {len(things)} předmětů (max 8)")
            elif not 3 <= len(things) <= 15:
                problems.append(f"slide {n}: {len(things)} předmětů (koláž potřebuje 3–15)")
            if any(not (t.get("queries") or t.get("query")) for t in things):
                problems.append(f"slide {n}: předmět bez hledání fotky")
            # Cover and closing slide show no labels; inner slides do (the label is the content).
            if role == "board" and any(not t.get("label") for t in things):
                problems.append(f"slide {n}: předmět bez popisku")
            if ":" in str(slide.get("title") or ""):
                problems.append(f"slide {n}: nadpis s dvojtečkou (použij `kicker` nad nadpisem)")
    # Attached media wins over generated slides when publishing.
    if kind == "carousel" and not 2 <= len(media or slides) <= 20:
        problems.append("karusel musí mít 2–20 položek")
    # "Spolupráce s…" / "in collaboration with…" alone is not enough.
    first_line = caption.strip().split("\n", 1)[0].lower()
    if item.get("sponsored") and not AD_LABEL.match(first_line):
        problems.append("placený/affiliate obsah musí začínat označením „Ad“ / „#ad“ (česky „Reklama“)")
    return problems


def slide_layout(slides: list[dict], index: int) -> str:
    """How a collage slide is laid out: "cover" (first slide of a carousel: pure
    mood, no labels), "cta" (closing slide with a body line: call to follow, no
    labels) or "board" (title with labelled photos). `layout` on the slide wins."""
    slide = slides[index]
    if slide.get("layout") in ("cover", "cta", "board"):
        return slide["layout"]
    if len(slides) > 1 and index == 0:
        return "cover"
    if index > 0 and index == len(slides) - 1 and slide.get("body"):
        return "cta"
    return "board"


def full_caption(item: dict) -> str:
    caption = (item.get("caption") or "").strip()
    disclosure = AI_DISCLOSURE.get(item.get("lang", "cs"), AI_DISCLOSURE["en"])
    if item.get("ai_media") and disclosure not in caption:
        caption = f"{caption}\n\n{disclosure}"
    tags = " ".join(f"#{t.lstrip('#')}" for t in item.get("hashtags") or [])
    return f"{caption}\n\n{tags}".strip() if tags else caption
