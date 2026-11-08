import csv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from igbot import content, scheduler

TZ = "America/New_York"


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "CONTENT_DIR", tmp_path / "content")
    monkeypatch.setattr(scheduler, "DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir()
    return tmp_path


def post(n, fmt="moodboard", **extra):
    item = {"id": f"2026-11-{n:02d}-feed-1", "kind": "carousel", "format": fmt,
            "slides": [{"title": f"Post {n}"}, {"title": "2"}], "caption": "Slow 🌿", "hashtags": []}
    item.update(extra)
    return item


def ny(day, h, m=0):
    return datetime(2026, 11, day, h, m, tzinfo=ZoneInfo(TZ))


def write_insights(path, rows):
    fields = ["snapshot", "media_id", "item_id", "published_at", "reach", "likes", "comments", "saved", "shares"]
    with open(path / "data" / "insights.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_posts_per_day_follow_the_pool():
    assert [scheduler.per_day(n) for n in (0, 1, 2, 5, 6, 20)] == [0, 1, 2, 2, 3, 3]


def test_slots_are_spaced_inside_the_window_and_stable_for_the_day():
    a = scheduler.slots(ny(9, 6), 3, [], TZ)
    assert a == scheduler.slots(ny(9, 20), 3, [], TZ)          # every run that day agrees
    hours = [s.hour for s in a]
    assert len(hours) == 3 and all(scheduler.FIRST_HOUR <= h <= scheduler.LAST_HOUR for h in hours)
    assert all(b - a_ >= 3 for a_, b in zip(hours, hours[1:]))


def test_hours_that_reach_more_people_climb():
    perf = [{"hour": 20, "reach": 300, "format": "list", "quality": 0},
            {"hour": 20, "reach": 280, "format": "list", "quality": 0},
            {"hour": 11, "reach": 20, "format": "list", "quality": 0}]
    scores = scheduler.hour_scores(perf)
    assert scores[20][0] > scheduler.HOUR_PRIOR[20] and scores[11][0] < scheduler.HOUR_PRIOR[11]
    assert 20 in [s.hour for s in scheduler.slots(ny(9, 6), 2, perf, TZ)]


def test_rank_learns_formats_and_never_repeats_the_last_one(queue):
    pool = [post(10, "moodboard"), post(11, "list"), post(12, "then_vs_now")]
    perf = [{"hour": 11, "reach": 50, "format": "list", "quality": 0.5},
            {"hour": 14, "reach": 50, "format": "moodboard", "quality": 0.02}]
    assert scheduler.rank(pool, perf, last_format=None)[0]["format"] == "list"
    assert scheduler.rank(pool, perf, last_format="list")[0]["format"] != "list"


def test_plan_respects_quota_gap_and_quiet_hours(queue):
    for n in range(10, 16):
        content.save(post(n), "approved")
    day = scheduler.plan(ny(9, 23), TZ)
    assert day["per_day"] == 3 and len(day["slots"]) == 3
    first = day["slots"][0]
    assert scheduler.plan(first - timedelta(minutes=1), TZ)["due"] is False
    p = scheduler.plan(first + timedelta(minutes=5), TZ)
    assert p["due"] and p["pick"]
    item = p["pick"]
    item["published_at"] = (first + timedelta(minutes=5)).isoformat(timespec="minutes")
    content.save(item, "published")
    late = scheduler.plan(day["slots"][1] + timedelta(minutes=1), TZ)
    assert late["due"] or late["reason"] == "příliš brzy po posledním postu"
    assert scheduler.plan(ny(9, 23, 30), TZ)["reason"] in ("mimo hodiny publikace", "dnes už 1/3",
                                                            "příliš brzy po posledním postu")


def test_performance_reads_the_latest_snapshot_per_post(queue):
    content.save(post(10, "list", published_at="2026-11-08T20:10-05:00"), "published")
    write_insights(queue, [
        {"snapshot": "2026-11-09", "media_id": "1", "item_id": "2026-11-10-feed-1",
         "published_at": "2026-11-08T20:10-05:00", "reach": 10, "likes": 1, "comments": 0, "saved": 0, "shares": 0},
        {"snapshot": "2026-11-10", "media_id": "1", "item_id": "2026-11-10-feed-1",
         "published_at": "2026-11-08T20:10-05:00", "reach": 40, "likes": 4, "comments": 0, "saved": 2, "shares": 1},
    ])
    [p] = scheduler.performance(TZ)
    assert p["hour"] == 20 and p["format"] == "list" and p["reach"] == 40
    assert p["quality"] == pytest.approx((3 * 2 + 4 * 1 + 4) / 40)


def test_day_plan_puts_a_post_on_every_slot_without_repeating_formats(queue):
    fmts = ["moodboard", "moodboard", "list", "list", "then_vs_now", "this_not_that", "moodboard"]
    for n, fmt in enumerate(fmts, start=10):
        content.save(post(n, fmt), "approved")
    morning = scheduler.day_plan(ny(9, 6), TZ)
    today, tomorrow = morning["days"]
    assert today["per_day"] == 3 and [s["status"] for s in today["slots"]] == ["planned"] * 3
    assert [datetime.fromisoformat(s["at"]) for s in today["slots"]] == scheduler.slots(ny(9, 6), 3, [], TZ)
    picked = [s["post_id"] for d in (today, tomorrow) for s in d["slots"]]
    assert len(picked) == len(set(picked))                      # each post once
    formats = [s["format"] for d in (today, tomorrow) for s in d["slots"]]
    assert all(a != b for a, b in zip(formats, formats[1:]))    # never the same format twice in a row
    assert all(s["why"] for s in today["slots"])
    # The first planned post is the one the publish run will pick, and the plan
    # doesn't change with the minute, only with facts.
    first = today["slots"][0]
    assert scheduler.plan(datetime.fromisoformat(first["at"]) + timedelta(minutes=5), TZ)["pick"]["id"] == first["post_id"]
    assert scheduler.day_plan(ny(9, 9, 41), TZ) == morning


def test_day_plan_shows_published_posts_and_keeps_the_gap(queue):
    for n in range(10, 13):
        content.save(post(n, "list" if n % 2 else "moodboard"), "approved")
    slot = scheduler.slots(ny(9, 6), 2, [], TZ)[0]
    late = slot + timedelta(hours=2, minutes=50)                 # GitHub ran late
    item = content.items("approved")[0]
    item["published_at"] = late.isoformat(timespec="minutes")
    content.save(item, "published")
    today = scheduler.day_plan(ny(9, 6), TZ)["days"][0]
    assert today["slots"][0]["status"] == "published" and today["slots"][0]["post_id"] == item["id"]
    nxt = [datetime.fromisoformat(s["at"]) for s in today["slots"][1:]]
    assert all(t - late >= scheduler.MIN_GAP for t in nxt)


def test_day_plan_with_an_empty_pool(queue):
    plan = scheduler.day_plan(ny(9, 6), TZ)
    assert plan["pool"] == 0 and all(d["slots"] == [] and d["per_day"] == 0 for d in plan["days"])
