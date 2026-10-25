"""Find and watch similar accounts through the official Business Discovery API.

Each run:
  1. reads public profile stats and recent posts of every tracked account,
  2. ranks their posts by engagement rate and saves topic/format signals to
     data/inspiration.json (short caption excerpts only, never media),
  3. collects @mentions from those captions as new candidate accounts and
     promotes the most-mentioned ones into tracking - so the list of sources
     keeps growing on its own ("search further and further").

Only Business/Creator accounts can be looked up; personal accounts are skipped.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import date

from .config import DATA_DIR
from .instagram import Instagram, InstagramError

TRACKED = DATA_DIR / "tracked_accounts.txt"
MENTION = re.compile(r"@([A-Za-z0-9_.]{2,30})")
HASHTAG = re.compile(r"#(\w+)")


def tracked(seeds: list[str]) -> list[str]:
    names = list(dict.fromkeys(seeds))
    if TRACKED.exists():
        names += [n.strip().lstrip("@") for n in TRACKED.read_text(encoding="utf-8").splitlines()
                  if n.strip() and not n.startswith("#")]
    return list(dict.fromkeys(names))


def run(ig: Instagram, seeds: list[str], own_handle: str = "", promote: int = 5, max_accounts: int = 40) -> dict:
    today = date.today().isoformat()
    accounts = tracked(seeds)[:max_accounts]
    stats, posts, mentions = [], [], Counter()

    for username in accounts:
        try:
            bd = ig.business_discovery(username)
        except InstagramError as exc:
            print(f"přeskočeno @{username}: {exc}")
            continue
        followers = bd.get("followers_count") or 0
        media = (bd.get("media") or {}).get("data", [])
        rates = []
        for m in media:
            engagement = (m.get("like_count") or 0) + (m.get("comments_count") or 0)
            rate = engagement / followers if followers else 0
            rates.append(rate)
            caption = m.get("caption") or ""
            mentions.update(u.lower().rstrip(".") for u in MENTION.findall(caption))
            posts.append({
                "account": username,
                "format": m.get("media_product_type") or m.get("media_type"),
                "topic_hint": caption.split("\n")[0][:140],
                "hashtags": HASHTAG.findall(caption)[:10],
                "engagement_rate": round(rate, 4),
                "views": m.get("view_count"),
                "permalink": m.get("permalink"),
                "timestamp": m.get("timestamp"),
            })
        stats.append({
            "snapshot": today, "username": username, "followers": followers,
            "media_count": bd.get("media_count"),
            "avg_engagement_rate": round(sum(rates) / len(rates), 4) if rates else 0,
            "website": bd.get("website") or "",
        })

    # Within each account, posts that beat that account's own average are the signal.
    by_account = {s["username"]: s["avg_engagement_rate"] for s in stats}
    for p in posts:
        avg = by_account.get(p["account"]) or 0
        p["vs_account_avg"] = round(p["engagement_rate"] / avg, 2) if avg else 0
    top = sorted(posts, key=lambda p: p["vs_account_avg"], reverse=True)[:40]

    known = {a.lower() for a in accounts} | {own_handle.lower()}
    candidates = [(u, n) for u, n in mentions.most_common() if u not in known]
    promoted = [u for u, n in candidates if n >= 2][:promote]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "inspiration.json").write_text(
        json.dumps({"updated": today, "top_posts": top}, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_csv(DATA_DIR / "competitors.csv", stats)
    _write_csv(DATA_DIR / "candidates.csv",
               [{"snapshot": today, "username": u, "mentions": n} for u, n in candidates[:100]])
    if promoted:
        with open(TRACKED, "a", encoding="utf-8") as fh:
            fh.writelines(f"{u}\n" for u in promoted)
    return {"accounts": len(stats), "posts": len(posts), "promoted": promoted}


def _write_csv(path, rows):
    if not rows:
        return
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        if new:
            writer.writeheader()
        writer.writerows(rows)
