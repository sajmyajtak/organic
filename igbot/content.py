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
    return sorted((load(p) for p in folder(state).glob("*.yaml")), key=lambda i: (i["date"], i["time"]))


def scheduled_at(item: dict, tz: str) -> datetime:
    return datetime.fromisoformat(f"{item['date']}T{item['time']}").replace(tzinfo=ZoneInfo(tz))


def due(tz: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(ZoneInfo(tz))
    return [i for i in items("approved") if scheduled_at(i, tz) <= now]


MAX_HASHTAGS = 5  # Instagram's cap since Dec 2025; the API docs still say 30
HASHTAG = re.compile(r"#\w*[^\W\d_]\w*")  # needs a letter, so "#1" in a list doesn't count
AD_LABEL = re.compile(r"(#?reklama|placené partnerství|sponzorovaný obsah)(?!\w)")
AI_DISCLOSURE = "Vytvořeno s pomocí AI."
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
    # Attached media wins over generated slides when publishing.
    if kind == "carousel" and not 2 <= len(media or slides) <= 20:
        problems.append("karusel musí mít 2–20 položek")
    # Label at the very start of the post, in Czech (ČOI's position as reported
    # by law firms; "Spolupráce s…" alone is not enough).
    first_line = caption.strip().split("\n", 1)[0].lower()
    if item.get("sponsored") and not AD_LABEL.match(first_line):
        problems.append("placený/affiliate obsah musí začínat označením „Reklama“ nebo „#reklama“")
    return problems


def full_caption(item: dict) -> str:
    caption = (item.get("caption") or "").strip()
    if item.get("ai_media") and AI_DISCLOSURE not in caption:
        caption = f"{caption}\n\n{AI_DISCLOSURE}"
    tags = " ".join(f"#{t.lstrip('#')}" for t in item.get("hashtags") or [])
    return f"{caption}\n\n{tags}".strip() if tags else caption
