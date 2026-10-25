"""Publish every approved item whose scheduled time has come."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import content, hosting
from .config import BUILD_DIR, ROOT
from .instagram import Instagram
from .render import Theme, render_item

# Items that missed their slot by more than this (e.g. the scheduler was down)
# are not posted late; they go to content/failed for a human to reschedule.
GRACE = timedelta(hours=6)


def media_files(item: dict, theme: Theme) -> list[Path]:
    if item.get("media"):
        return [ROOT / m for m in item["media"]]
    return render_item(item, BUILD_DIR / "media", theme)


def publish_item(ig: Instagram, item: dict, theme: Theme, dry_run: bool) -> list[str]:
    files = media_files(item, theme)
    if dry_run:
        urls = [f"https://example.invalid/{f.name}" for f in files]
        print(f"[dry-run] {item['id']}: {len(files)} soubor(ů) → {[str(f.relative_to(ROOT)) for f in files]}")
    else:
        urls = hosting.upload(files, prefix=item["id"])

    caption = content.full_caption(item)
    # Meta's "AI info" label is for AI-generated imagery/video. Text graphics
    # written with AI help and approved by a human don't need it.
    ai_media = bool(item.get("ai_media"))
    kind = item["kind"]
    if kind == "story":
        # One story frame per file, published in order.
        return [ig.publish_story(video_url=u, ai_generated=ai_media) if u.endswith(".mp4")
                else ig.publish_story(image_url=u, ai_generated=ai_media) for u in urls]
    if kind == "reel":
        return [ig.publish_reel(urls[0], caption, cover_url=urls[1] if len(urls) > 1 else None,
                                trial=bool(item.get("trial")), ai_generated=ai_media)]
    if kind == "carousel" and len(urls) > 1:
        return [ig.publish_carousel(urls, caption, ai_generated=ai_media)]
    return [ig.publish_image(urls[0], caption, item.get("alt_text", ""), ai_generated=ai_media)]


def publish_due(cfg: dict, dry_run: bool = False, now: datetime | None = None) -> int:
    tz = cfg["account"]["timezone"]
    now = now or datetime.now(ZoneInfo(tz))
    queue = content.due(tz, now)
    if not queue:
        return 0
    theme = Theme.from_config(cfg)
    ig = Instagram.from_env(dry_run=dry_run)
    published = 0

    def fail(item: dict, error: str) -> None:
        print(f"CHYBA {item['id']}: {error}")
        if not dry_run:
            item["error"] = error
            content.save(item, "failed")

    for item in queue:
        if now - content.scheduled_at(item, tz) > GRACE:
            fail(item, f"zmeškaný termín (publikace neproběhla do {GRACE})")
            continue
        problems = content.validate(item)
        if problems:
            fail(item, "; ".join(problems))
            continue
        try:
            ids = publish_item(ig, item, theme, dry_run)
        except Exception as exc:  # keep going with the rest of the queue
            fail(item, str(exc))
            continue
        if dry_run:
            continue
        item["media_ids"] = ids
        item["published_at"] = now.isoformat(timespec="minutes")
        content.save(item, "published")
        published += 1
        print(f"OK {item['id']} → {ids}")
    return published
