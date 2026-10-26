"""Pull post and account metrics into CSV files that the generator learns from."""

from __future__ import annotations

import csv
from datetime import date

from . import content
from .config import DATA_DIR
from .instagram import Instagram, InstagramError

# Per media type, as documented for Graph API v26 (impressions/plays were
# replaced by views in 2025). Asking for a metric a type doesn't support fails
# the whole request, so the lists differ.
FEED_METRICS = ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions",
                "follows", "profile_visits"]
REEL_METRICS = ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions",
                "ig_reels_avg_watch_time", "reels_skip_rate"]
STORY_METRICS = ["reach", "views", "shares", "total_interactions", "navigation", "replies"]
METRICS = {"story": STORY_METRICS, "reel": REEL_METRICS}

FIELDS = ["snapshot", "media_id", "item_id", "kind", "pillar", "title", "published_at",
          "reach", "views", "likes", "comments", "saved", "shares", "total_interactions",
          "follows", "profile_visits", "ig_reels_avg_watch_time", "reels_skip_rate",
          "replies", "navigation"]


def collect(ig: Instagram) -> int:
    today = date.today().isoformat()
    rows = []
    for item in content.items("published"):
        metrics = METRICS.get(item["kind"], FEED_METRICS)
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
                "title": (item.get("slides") or [{}])[0].get("title", "")
                         or (item.get("script") or {}).get("hook_on_screen", ""),
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
