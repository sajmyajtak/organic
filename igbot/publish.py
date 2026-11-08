"""Publish every approved item whose scheduled time has come."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import content, hosting, scheduler
from .config import BUILD_DIR, ROOT
from .instagram import Instagram
from .render import Theme, render_item

# Items that missed their slot by more than this (e.g. the scheduler was down)
# are not posted late; they go to content/failed for a human to reschedule.
GRACE = timedelta(hours=6)


def media_sources(item: dict, theme: Theme) -> list[Path | str]:
    """Files to upload (Path) or already public URLs (str), in publishing order."""
    if item.get("media"):
        return [m if str(m).startswith(("https://", "http://")) else ROOT / m for m in item["media"]]
    return render_item(item, BUILD_DIR / "media", theme)


def alt_text(slide: dict) -> str:
    """What a blind user should hear: the text, and for a collage the things pictured."""
    text = " ".join(filter(None, [slide.get("title"), slide.get("body")]))
    things = [t.get("label") for t in slide.get("items") or [] if t.get("label")]
    return f"{text}: {', '.join(things)}" if things else text


def publish_item(ig: Instagram, item: dict, theme: Theme, dry_run: bool) -> list[str]:
    sources = media_sources(item, theme)
    files = [s for s in sources if isinstance(s, Path)]
    if dry_run:
        uploaded = [f"https://example.invalid/{f.name}" for f in files]
        print(f"[dry-run] {item['id']}: {len(sources)} médií → "
              f"{[str(s.relative_to(ROOT)) if isinstance(s, Path) else s for s in sources]}")
    else:
        uploaded = hosting.upload(files, prefix=item["id"]) if files else []
    it = iter(uploaded)
    urls = [next(it) if isinstance(s, Path) else s for s in sources]

    caption = content.full_caption(item)
    # Meta's "AI info" label is for AI-generated imagery/video. Text graphics
    # written with AI help and approved by a human don't need it.
    ai_media = bool(item.get("ai_media"))
    paid = bool(item.get("paid_partnership"))
    kind = item["kind"]
    if kind == "story":
        # One story frame per file, published in order.
        return [ig.publish_story(video_url=u, ai_generated=ai_media) if u.lower().split("?")[0].endswith((".mp4", ".mov"))
                else ig.publish_story(image_url=u, ai_generated=ai_media) for u in urls]
    if kind == "reel":
        return [ig.publish_reel(urls[0], caption, cover_url=urls[1] if len(urls) > 1 else None,
                                trial=bool(item.get("trial")), ai_generated=ai_media, paid_partnership=paid)]
    if kind == "carousel" and len(urls) > 1:
        # Alt text must describe what's shown: the slides, unless other media replaced them.
        slides = (item.get("slides") or []) if not item.get("media") or item.get("media_from_slides") else []
        alts = [alt_text(s) for s in slides]
        return [ig.publish_carousel(urls, caption, alts, ai_generated=ai_media, paid_partnership=paid)]
    return [ig.publish_image(urls[0], caption, item.get("alt_text", ""), ai_generated=ai_media,
                             paid_partnership=paid)]


def quota_left(ig: Instagram) -> int | None:
    """Remaining API publications in the rolling 24 h window (Meta docs say 50 or 100)."""
    try:
        quota = ig.publishing_quota()
        total = (quota.get("config") or {}).get("quota_total") or 50
        return int(total) - int(quota.get("quota_usage") or 0)
    except Exception as exc:  # the check is a safeguard, not a reason to stop publishing
        print(f"limit publikací nezjištěn: {exc}")
        return None


def publish_due(cfg: dict, dry_run: bool = False, now: datetime | None = None) -> int:
    tz = cfg["account"]["timezone"]
    now = now or datetime.now(ZoneInfo(tz))
    queue = content.due(tz, now)
    plan = scheduler.plan(now, tz)
    if plan["due"]:
        print(f"plánovač: {plan['pick']['id']} ({plan['pick'].get('format')}), dnes {plan['today'] + 1}/{plan['per_day']}")
        queue.append(plan["pick"])
    else:
        nxt = f", další okno {plan['next_slot']:%H:%M}" if plan["next_slot"] else ""
        print(f"plánovač: teď nic ({plan['reason']}{nxt}; v zásobě {len(plan['pool'])})")
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

    left = None if dry_run else quota_left(ig)
    for item in queue:
        if left is not None and left <= 0:
            print("Denní limit publikací přes API je vyčerpaný, zbytek počká na další běh.")
            break
        if item["kind"] in content.TIMED and now - content.scheduled_at(item, tz) > GRACE:
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
        if left is not None:
            left -= len(ids)
        item["media_ids"] = ids
        item["published_at"] = now.isoformat(timespec="minutes")
        content.save(item, "published")
        published += 1
        print(f"OK {item['id']} → {ids}")
    return published
