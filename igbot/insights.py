"""Pull post and account metrics into CSV files that the generator learns from."""

from __future__ import annotations

import csv
from datetime import date

from . import content
from .config import DATA_DIR
from .instagram import Instagram, InstagramError

# Metric names changed in 2025 (impressions/plays → views). Override with
# IG_FEED_METRICS / IG_STORY_METRICS if Meta renames them again.
FEED_METRICS = ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions"]
STORY_METRICS = ["reach", "views", "replies", "shares", "navigation"]

FIELDS = ["snapshot", "media_id", "item_id", "kind", "pillar", "title", "published_at",
          "reach", "views", "likes", "comments", "saved", "shares", "total_interactions",
          "replies", "navigation"]


def collect(ig: Instagram) -> int:
    today = date.today().isoformat()
    rows = []
    for item in content.items("published"):
        metrics = STORY_METRICS if item["kind"] == "story" else FEED_METRICS
        for media_id in item.get("media_ids") or []:
            try:
                values = ig.media_insights(media_id, metrics)
            except InstagramError as exc:
                # Story insights disappear 24 h after the story expires; that's expected.
                print(f"přeskočeno {item['id']} ({media_id}): {exc}")
                continue
            rows.append({
                "snapshot": today, "media_id": media_id, "item_id": item["id"],
                "kind": item["kind"], "pillar": item.get("pillar", ""),
                "title": (item.get("slides") or [{}])[0].get("title", ""),
                "published_at": item.get("published_at", ""), **values,
            })
    _append(DATA_DIR / "insights.csv", FIELDS, rows)

    account = ig.account()
    _append(DATA_DIR / "account.csv", ["snapshot", "followers_count", "follows_count", "media_count"],
            [{"snapshot": today, **{k: account.get(k) for k in ("followers_count", "follows_count", "media_count")}}])
    return len(rows)


def _append(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if new:
            writer.writeheader()
        writer.writerows(rows)
