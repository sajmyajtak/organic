"""When to post and which approved post goes next. No fixed dates.

Approved items are a pool. Each publish run (GitHub Actions; in practice its
"every 30 minutes" turns into a run every few hours) asks `pick(now)`.

When: up to `per_day` posts a day (3 with a healthy pool, fewer when it runs
low), at least MIN_GAP apart, only inside posting hours. The day's target
hours come from our own posts' reach by posting hour, blended with a prior
from the niche analysis (@organic__101_ posts 9-14 New York; US evening scroll
19-21). One slot a day explores a less-tested hour so the stats keep
learning. Slots are derived from the date, so every run that day agrees
without shared state, and a late run simply catches up on a passed slot.

What: the pool item whose format did best so far (saves and shares weigh
most, per account reached), shrunk toward a prior while data is thin; never
the same format twice in a row; a bonus for formats not tried yet and for
posts that have waited longer.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from . import content
from .config import DATA_DIR

MIN_GAP = timedelta(hours=3)
FIRST_HOUR, LAST_HOUR = 7, 22          # posting window, account time zone
SHRINK = 3.0                           # how many posts' worth of weight the prior has

# Prior: how good each local hour looks before we have data (1.0 = best).
HOUR_PRIOR = {7: 0.35, 8: 0.55, 9: 0.8, 10: 0.9, 11: 1.0, 12: 1.0, 13: 0.9, 14: 0.8, 15: 0.6,
              16: 0.6, 17: 0.7, 18: 0.8, 19: 0.95, 20: 0.95, 21: 0.75, 22: 0.45}
# Prior per format from the niche analysis (best carousels of the source account).
FORMAT_PRIOR = {"moodboard": 1.0, "list": 0.95, "then_vs_now": 0.9, "this_not_that": 0.9}


def per_day(pool_size: int) -> int:
    """3 a day while the pool lasts two days or more, then slow down rather than run dry."""
    return 3 if pool_size >= 6 else 2 if pool_size >= 2 else 1 if pool_size else 0


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts)) if ts else None
    except ValueError:
        return None


def performance(tz: str) -> list[dict]:
    """Our published posts with their latest stats: hour posted, format, reach, quality."""
    latest: dict[str, dict] = {}
    path = DATA_DIR / "insights.csv"
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                latest[row["media_id"]] = row  # file is in time order: last snapshot wins
    formats = {i["id"]: i.get("format") for i in content.items("published")}
    out = []
    for row in latest.values():
        when = _parse(row.get("published_at"))
        if when is None:
            continue
        num = lambda k: float(row.get(k) or 0)  # noqa: E731
        reach = num("reach")
        out.append({
            "hour": when.astimezone(ZoneInfo(tz)).hour,
            "format": formats.get(row.get("item_id")),
            "reach": reach,
            # what the ranking rewards: saves and shares first, then comments and likes
            "quality": (3 * num("saved") + 4 * num("shares") + 2 * num("comments") + num("likes")) / max(reach, 1),
        })
    return out


def hour_scores(perf: list[dict]) -> dict[int, tuple[float, float]]:
    """{hour: (score, weight of our own data)}; reach is compared to our median post."""
    mid = median([p["reach"] for p in perf]) if perf else 0
    scores = {}
    for h, prior in HOUR_PRIOR.items():
        near = [p for p in perf if abs(p["hour"] - h) <= 1]
        weight = sum(1.0 if p["hour"] == h else 0.5 for p in near)
        observed = sum((1.0 if p["hour"] == h else 0.5) * (p["reach"] / mid if mid else 1.0) for p in near)
        scores[h] = ((prior * SHRINK + observed) / (SHRINK + weight), weight)
    return scores


def slot_plan(day: datetime, n: int, perf: list[dict], tz: str) -> list[tuple[datetime, bool]]:
    """The day's posting times as (time, exploring): the best hours, spaced out, one exploring."""
    if n <= 0:
        return []
    rnd = random.Random(day.strftime("%Y-%m-%d"))
    scores = hour_scores(perf)
    ranked = sorted(scores, key=lambda h: -scores[h][0])
    chosen: list[int] = []
    gap = MIN_GAP.total_seconds() / 3600
    explore = n >= 2  # with one post a day, play it safe
    for h in ranked:
        if len(chosen) >= n - explore:
            break
        if all(abs(h - c) >= gap for c in chosen):
            chosen.append(h)
    explored = None
    if explore:
        # the least-observed of the plausible hours that still fit between the others
        free = [h for h in scores if HOUR_PRIOR[h] >= 0.6 and all(abs(h - c) >= gap for c in chosen)]
        if free:
            least = min(scores[h][1] for h in free)
            explored = rnd.choice([h for h in free if scores[h][1] <= least + 0.5])
            chosen.append(explored)
    zone = ZoneInfo(tz)
    base = day.astimezone(zone).date()
    picked = sorted((datetime.combine(base, time(h, rnd.randrange(0, 46, 5)), zone), h == explored)
                    for h in chosen)
    # Hours are >= 3 apart, but the minute jitter could leave 2:45 between two
    # slots, and a run would then wait for MIN_GAP anyway. Say the real time.
    out: list[tuple[datetime, bool]] = []
    for t, exploring in picked:
        if out and t - out[-1][0] < MIN_GAP:
            t = out[-1][0] + MIN_GAP
        out.append((t, exploring))
    return out


def slots(day: datetime, n: int, perf: list[dict], tz: str) -> list[datetime]:
    """The day's posting times: the best hours, spaced out, one of them exploring."""
    return [t for t, _ in slot_plan(day, n, perf, tz)]


def format_scores(perf: list[dict]) -> dict[str, list[float]]:
    """{format: [each post as "how it did against our typical post", 1.0 = typical]}.

    Half engagement quality, half reach, so it is on the same scale as the prior."""
    mid_q = median([p["quality"] for p in perf]) if perf else 0
    mid_r = median([p["reach"] for p in perf]) if perf else 0
    by_format: dict[str, list[float]] = {}
    for p in perf:
        if p["format"]:
            rel_q = p["quality"] / mid_q if mid_q else 1.0
            rel_r = p["reach"] / mid_r if mid_r else 1.0
            by_format.setdefault(p["format"], []).append(0.5 * rel_q + 0.5 * rel_r)
    return by_format


def rank(pool: list[dict], perf: list[dict], last_format: str | None) -> list[dict]:
    """Pool items, best first."""
    by_format = format_scores(perf)

    def score(item: dict) -> float:
        fmt = item.get("format") or ""
        seen = by_format.get(fmt, [])
        prior = FORMAT_PRIOR.get(fmt, 0.8)
        base = (prior * SHRINK + sum(seen)) / (SHRINK + len(seen))
        bonus = 0.15 if not seen else 0.0
        repeat = 0.35 if fmt and fmt == last_format else 0.0
        jitter = random.Random(item["id"]).random() * 0.05
        return base + bonus - repeat + jitter

    # Older approved ideas first among equals (ids start with their intended date).
    return sorted(sorted(pool, key=lambda i: i["id"]), key=score, reverse=True)


def plan(now: datetime, tz: str) -> dict:
    """Today's picture: pool, quota, slots, what is due now and which item would go."""
    zone = ZoneInfo(tz)
    now = now.astimezone(zone)
    pool = [i for i in content.items("approved") if i["kind"] not in content.TIMED and not content.validate(i)]
    published = [i for i in content.items("published") if i["kind"] not in content.TIMED]
    times = sorted(t for t in (_parse(i.get("published_at")) for i in published) if t)
    today = [t for t in times if t.astimezone(zone).date() == now.date()]
    perf = performance(tz)
    n = per_day(len(pool) + len(today))
    day_slots = slots(now, n, perf, tz)
    passed = [s for s in day_slots if s <= now]
    last = times[-1] if times else None
    last_format = None
    if published:
        newest = max(published, key=lambda i: i.get("published_at") or "")
        last_format = newest.get("format")
    reason = None
    if not pool:
        reason = "zásoba schválených je prázdná"
    elif len(today) >= n:
        reason = f"dnes už {len(today)}/{n}"
    elif len(passed) <= len(today):
        reason = "další okno ještě nenastalo"
    elif last and now - last < MIN_GAP:
        reason = "příliš brzy po posledním postu"
    elif now.hour > LAST_HOUR or now.hour < FIRST_HOUR:
        reason = "mimo hodiny publikace"
    if reason is None:
        next_slot = now
    elif len(today) < n:
        earliest = max(now, last + MIN_GAP) if last else now
        next_slot = next((s for s in day_slots if s > earliest), None)
    else:
        next_slot = None  # tomorrow
    return {
        "pool": pool, "per_day": n, "today": len(today), "slots": day_slots,
        "next_slot": next_slot,
        "due": reason is None, "reason": reason,
        "pick": rank(pool, perf, last_format)[0] if pool and reason is None else None,
    }


FORMAT_NAMES = {"moodboard": "moodboard", "list": "seznam", "then_vs_now": "dřív a dnes",
                "this_not_that": "tohle, ne tamto"}


def _kind(item: dict) -> dict:
    """How the post goes (or went) out, and its song if it is a Reel."""
    from .music import label

    reel = item.get("published_as") == "reel" or ("published_at" not in item and (item.get("reel") or {}).get("video"))
    # A carousel's song is added in the app after it goes out; a Reel gets it from Instagram.
    return {"kind": "reel" if reel else item.get("kind"), "music": label(item.get("music")),
            "permalink": item.get("permalink")}


def _title(item: dict) -> str:
    slides = item.get("slides") or []
    return str((slides[0].get("title") if slides else "") or item["id"])


def _hour_why(hour: int, scores: dict[int, tuple[float, float]], exploring: bool) -> str:
    if exploring:
        return "test méně ověřené hodiny"
    if scores[hour][1] >= 1:
        return "nejlepší zásah našich postů"
    return "silná hodina podle rozboru niky"


def _post_why(item: dict, by_format: dict[str, list[float]]) -> str:
    fmt = item.get("format") or ""
    name = FORMAT_NAMES.get(fmt, fmt or "post")
    seen = by_format.get(fmt)
    if not seen:
        return f"formát {name} ještě nemá data, zkoušíme ho"
    return f"formát {name} zatím {sum(seen) / len(seen):.1f}× náš průměr"


def day_plan(now: datetime, tz: str, days: int = 2) -> dict:
    """Today's (and tomorrow's) posting times with the post planned for each.

    The same rules as `plan`: per_day from the pool, the day's slots, MIN_GAP
    after the previous post, best-ranked pool item for each slot, never the same
    format twice in a row. Times are windows: a run publishes at the first run
    after one (GitHub starts the job every few hours). Nothing here depends on
    the current minute, so the result only changes when facts change (a post,
    an approval, new stats, a new day), and so does its fingerprint."""
    zone = ZoneInfo(tz)
    now = now.astimezone(zone)
    pool = [i for i in content.items("approved") if i["kind"] not in content.TIMED and not content.validate(i)]
    remaining = list(pool)
    published = [i for i in content.items("published") if i["kind"] not in content.TIMED and _parse(i.get("published_at"))]
    published.sort(key=lambda i: _parse(i["published_at"]))
    perf = performance(tz)
    scores = hour_scores(perf)
    by_format = format_scores(perf)
    last_time = _parse(published[-1]["published_at"]) if published else None
    last_format = published[-1].get("format") if published else None
    out = []
    for offset in range(days):
        date = now.date() + timedelta(days=offset)
        noon = datetime.combine(date, time(12), zone)
        done = [i for i in published if _parse(i["published_at"]).astimezone(zone).date() == date]
        n = per_day(len(remaining) + len(done))
        entries = [{"at": _parse(i["published_at"]).astimezone(zone).isoformat(timespec="minutes"),
                    "status": "published", "post_id": i["id"], "title": _title(i), "format": i.get("format"),
                    "why": None, **_kind(i)} for i in done]
        for slot, exploring in slot_plan(noon, n, perf, tz)[len(done):]:
            if not remaining:
                break
            at = max(slot, last_time + MIN_GAP) if last_time else slot
            if at.astimezone(zone).date() != date or at.astimezone(zone).hour > LAST_HOUR:
                break  # pushed past the posting hours by a late post: nothing more that day
            pick = rank(remaining, perf, last_format)[0]
            remaining.remove(pick)
            entries.append({"at": at.astimezone(zone).isoformat(timespec="minutes"), "status": "planned",
                            "post_id": pick["id"], "title": _title(pick), "format": pick.get("format"),
                            "why": f"{_hour_why(slot.hour, scores, exploring)}; {_post_why(pick, by_format)}",
                            **_kind(pick)})
            last_time, last_format = at, pick.get("format")
        out.append({"date": date.isoformat(), "per_day": n, "slots": entries})
    return {"tz": tz, "pool": len(pool), "days": out, "left_after": len(remaining)}
