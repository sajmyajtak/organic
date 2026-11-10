from datetime import datetime, timedelta, timezone

import pytest

from igbot import content, klapka, scheduler
from igbot.klapka import (F_ACCOUNT, F_CAPTION, F_CHANGED, F_DECISION, F_ERROR, F_KIND, F_PLANNED, F_POST_ID,
                          F_STATE, HEARTBEAT_POST_ID, HEARTBEAT_RECORD, Airtable)


class FakeAirtable(Airtable):
    """In-memory Airtable table that behaves like the REST API for our calls."""

    def __init__(self):
        super().__init__("token")
        # KLAPKA made the heartbeat row itself.
        self.table: dict[str, dict] = {HEARTBEAT_RECORD: {F_POST_ID: HEARTBEAT_POST_ID, F_ACCOUNT: "naturizz"}}
        self.log: list[str] = []
        self._n = 0

    def _request(self, method, params=None, body=None):
        self.log.append(method)
        if method == "GET":
            wanted = params.get("fields[]") or []
            recs = [{"id": rid, "fields": {k: v for k, v in f.items() if k in wanted}}
                    for rid, f in self.table.items()]
            return 200, {"records": recs}
        if method == "POST":
            out = []
            for rec in body["records"]:
                self._n += 1
                rid = f"rec{self._n:014d}"
                self.table[rid] = dict(rec["fields"])
                out.append({"id": rid, "fields": rec["fields"]})
            return 200, {"records": out}
        if method == "PATCH":
            if any(r["id"] not in self.table for r in body["records"]):
                return 404, {"error": {"type": "NOT_FOUND", "message": "Could not find what you are looking for"}}
            for r in body["records"]:
                for k, v in r["fields"].items():
                    if v is None:
                        self.table[r["id"]].pop(k, None)
                    else:
                        self.table[r["id"]][k] = v
            return 200, {"records": body["records"]}
        if method == "DELETE":
            for rid in params["records[]"]:
                self.table.pop(rid, None)
            return 200, {}
        raise AssertionError(method)

    def queue_rows(self):
        return {r: f for r, f in self.table.items() if f.get(F_POST_ID) != HEARTBEAT_POST_ID}

    def beat(self):
        return self.row(HEARTBEAT_POST_ID)

    def row(self, post_id):
        found = [f for f in self.table.values() if f.get(F_POST_ID) == post_id]
        return found[0] if found else None


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "CONTENT_DIR", tmp_path / "content")
    monkeypatch.setattr(klapka, "load_config",
                        lambda: {"account": {"timezone": "America/New_York", "handle": "naturizz"}})
    monkeypatch.setattr(klapka.time, "sleep", lambda s: None)
    monkeypatch.setattr(scheduler, "DATA_DIR", tmp_path / "data")  # our real stats would move the slots
    return tmp_path


def post(n=1, day="2026-11-10", **extra):
    item = {"id": f"{day}-feed-{n}", "date": day, "time": "11:30", "kind": "carousel",
            "slides": [{"title": f"The art of thing {n}", "body": ""}, {"title": "2", "body": ""}],
            "caption": "Slow mornings 🍂", "hashtags": ["slowliving"], "sponsored": False, "lang": "en"}
    item.update(extra)
    return item


T0 = datetime(2026, 11, 9, 13, 7, tzinfo=timezone.utc)


def at_hour(h: float) -> datetime:
    return T0 + timedelta(hours=h)


def test_first_sync_creates_rows_then_sends_only_changes(queue):
    at = FakeAirtable()
    content.save(post(1), "drafts")
    content.save(post(2), "approved")

    result = klapka.sync("cli", client=at)
    assert result["created"] == 2 and at.log == ["GET", "POST", "PATCH"]  # PATCH = heartbeat
    row = at.row("2026-11-10-feed-1")
    assert row[F_STATE] == "koncept" and row[F_KIND] == "karusel" and row[F_ACCOUNT] == "naturizz"
    assert F_PLANNED not in row  # no fixed date: the scheduler picks the moment
    assert at.row("2026-11-10-feed-2")[F_STATE] == "schváleno"

    at.log.clear()
    assert klapka.sync("approve", client=at)["calls"] == 0  # nothing changed, nothing sent

    item = content.items("drafts")[0]
    item["caption"] = "New caption"
    content.save(item, "drafts")
    assert klapka.sync("approve", client=at)["updated"] == 1 and at.log == ["PATCH"]


def test_decisions_from_klapka_approve_and_reject_drafts(queue):
    at = FakeAirtable()
    content.save(post(1), "drafts")
    content.save(post(2), "drafts")
    klapka.sync("cli", client=at)
    at.row("2026-11-10-feed-1")[F_DECISION] = "schválit"
    at.row("2026-11-10-feed-2")[F_DECISION] = "zamítnout"

    result = klapka.sync("cli", client=at)
    assert result["approved"] == 1 and result["rejected"] == 1
    assert [i["id"] for i in content.items("approved")] == ["2026-11-10-feed-1"]
    assert content.items("drafts") == []                       # rejected draft is gone
    assert at.row("2026-11-10-feed-2") is None                 # and so is its row
    row = at.row("2026-11-10-feed-1")
    assert row[F_STATE] == "schváleno" and F_DECISION not in row  # decision done and cleared


def test_decision_for_an_item_this_checkout_does_not_have_is_left_alone(queue):
    at = FakeAirtable()
    at.table["recFOREIGN000000"] = {F_POST_ID: "2026-11-11-feed-1", F_ACCOUNT: "naturizz",
                                    F_DECISION: "schválit"}
    content.save(post(1), "drafts")
    klapka.sync("cli", client=at)
    assert at.table["recFOREIGN000000"][F_DECISION] == "schválit"


def test_row_deleted_in_klapka_is_never_sent_again(queue):
    at = FakeAirtable()
    content.save(post(1), "approved")
    content.save(post(2), "approved")
    klapka.sync("cli", client=at)

    # Deleted while we weren't looking: the next update finds out.
    rid = next(r for r, f in at.table.items() if f[F_POST_ID] == "2026-11-10-feed-1")
    del at.table[rid]
    for item in content.items("approved"):
        item["caption"] = "changed"
        content.save(item, "approved")
    result = klapka.sync("approve", client=at)
    assert result["gone"] == 1 and result["updated"] == 1
    assert klapka.sync("cli", client=at)["created"] == 0
    assert at.row("2026-11-10-feed-1") is None

    # Deleted and noticed by the full read.
    rid = next(r for r, f in at.table.items() if f[F_POST_ID] == "2026-11-10-feed-2")
    del at.table[rid]
    assert klapka.sync("cli", client=at)["gone"] == 1
    assert at.queue_rows() == {} and at.beat()  # the heartbeat row is never touched by cleanup


def test_automatic_run_paces_itself_but_sends_new_posts_and_errors_now(queue):
    at = FakeAirtable()
    content.save(post(1), "approved")
    assert klapka.sync("publish", now=T0, client=at)["created"] == 1   # first run: nothing sent yet

    item = content.items("approved")[0]
    item["caption"] = "edited"
    content.save(item, "approved")
    result = klapka.sync("publish", now=at_hour(2), client=at)
    assert result["waiting"] == 1 and result["calls"] == 0          # pushed 2 h ago: waits
    assert klapka.sync("publish", now=at_hour(9), client=at)["updated"] == 1   # 8 h passed

    item = content.items("approved")[0]
    item["published_at"] = "2026-11-09T19:00-05:00"
    content.save(item, "published")
    assert klapka.sync("publish", now=at_hour(10), client=at, published=1)["updated"] == 1  # new post: now

    item = content.items("published")[0]
    item["error"] = "Instagram odmítl médium"
    content.save(item, "failed")
    assert klapka.sync("publish", now=at_hour(11), client=at)["updated"] == 1   # error: now
    assert at.row("2026-11-10-feed-1")[klapka.F_STATE] == "chyba"
    assert "Instagram odmítl médium" in at.beat()[F_ERROR]  # red bar in KLAPKA right away


def test_automatic_run_reads_decisions_only_with_drafts_every_two_hours(queue):
    at = FakeAirtable()
    content.save(post(1), "approved")
    klapka.sync("publish", now=T0, client=at)
    assert "GET" not in at.log
    content.save(post(2), "drafts")
    klapka.sync("publish", now=at_hour(1), client=at)
    assert at.log.count("GET") == 1
    klapka.sync("publish", now=at_hour(2), client=at)
    assert at.log.count("GET") == 1    # read an hour ago
    klapka.sync("publish", now=at_hour(3.5), client=at)
    assert at.log.count("GET") == 2    # an approval in KLAPKA counts within two hours


def test_only_the_newest_published_rows_stay(queue):
    at = FakeAirtable()
    for n in range(1, 36):
        content.save(post(n, published_at=f"2026-10-{n % 28 + 1:02d}T11:30-05:00" if n <= 28
                          else f"2026-11-{n - 27:02d}T11:30-05:00", media_ids=[str(n)]), "published")
    assert klapka.sync("cli", client=at)["created"] == klapka.KEEP_PUBLISHED
    assert len(at.queue_rows()) == klapka.KEEP_PUBLISHED

    # Ten newer posts: their rows come in, the ten oldest rows go out in one call.
    for n in range(36, 46):
        content.save(post(n, day="2026-11-20", published_at=f"2026-11-20T{n - 30:02d}:00-05:00"), "published")
    result = klapka.sync("publish", now=T0, client=at)
    assert result["created"] == 10 and result["deleted"] == 10
    assert len(at.queue_rows()) == klapka.KEEP_PUBLISHED and at.beat()
    assert klapka.sync("cli", client=at)["created"] == 0   # retired posts never come back


def test_without_token_sync_is_skipped(queue, monkeypatch):
    monkeypatch.delenv("AIRTABLE_TOKEN", raising=False)
    assert klapka.sync("publish") == {"skipped": "chybí AIRTABLE_TOKEN"}


def test_status_sentence_and_error(queue):
    tz = "America/New_York"
    morning = datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc)   # 8:00 in New York
    for n in (1, 2):
        content.save(post(n), "drafts")
    for n in (3, 4, 5):
        content.save(post(n), "approved")
    line, error = klapka.status(klapka._local(), tz, morning)
    assert line.startswith("2 koncepty, 3 v zásobě, dnes 0/2, další okno ") and line.endswith(" NY")
    assert error is None
    for path in queue.glob("content/*/*.yaml"):
        path.unlink()
    assert klapka.status({}, tz, morning) == ("Zásoba schválených je prázdná", None)
    content.save(post(1, error="token vypršel"), "failed")
    assert klapka.status(klapka._local(), tz, morning)[1] == "1 položka selhala, poslední 2026-11-10-feed-1: token vypršel"


def test_heartbeat_goes_out_every_8_hours_even_with_a_quiet_queue(queue):
    at = FakeAirtable()
    content.save(post(1), "approved")
    klapka.sync("publish", now=T0, client=at)
    at.log.clear()
    assert klapka.sync("publish", now=at_hour(3), client=at)["calls"] == 0
    result = klapka.sync("publish", now=at_hour(9), client=at)
    assert result["calls"] == 1 and result["heartbeat"] and at.log == ["PATCH"]
    beat = at.beat()
    assert beat[F_CHANGED] == "2026-11-09T22:07:00Z"
    assert beat[F_CAPTION].startswith("1 v zásobě, dnes 0/1, ") and F_ERROR not in beat


def test_heartbeat_row_deleted_in_klapka_is_recreated_once(queue):
    at = FakeAirtable()
    del at.table[HEARTBEAT_RECORD]
    klapka.sync("cli", client=at)
    new_id = next(r for r, f in at.table.items() if f.get(F_POST_ID) == HEARTBEAT_POST_ID)
    assert (queue / "content" / ".klapka-automat").read_text().strip() == new_id
    at.log.clear()
    klapka.sync("cli", client=at)
    assert at.log == ["GET", "PATCH"]  # straight to the new row, nothing created
    assert [f for f in at.table.values() if f.get(F_POST_ID) == HEARTBEAT_POST_ID] == [at.table[new_id]]


def test_failed_sync_turns_the_bar_red(queue, monkeypatch):
    sent = []
    monkeypatch.setenv("AIRTABLE_TOKEN", "t")
    monkeypatch.setattr(klapka, "sync", lambda trigger, **kw: (_ for _ in ()).throw(RuntimeError("Airtable 503")))
    monkeypatch.setattr(Airtable, "_request", lambda self, m, params=None, body=None: (sent.append(body), (200, {}))[1])
    klapka.after("approve")
    assert sent[0]["records"][0]["id"] == HEARTBEAT_RECORD
    assert "Airtable 503" in sent[0]["records"][0]["fields"][F_ERROR]


def test_preview_goes_out_only_once_the_file_is_online(queue, monkeypatch):
    online = set()
    monkeypatch.setattr(klapka, "_reachable", {})
    monkeypatch.setattr(klapka.requests, "head",
                        lambda url, **kw: type("R", (), {"status_code": 200 if url in online else 404})())
    at = FakeAirtable()
    url = "https://raw.example/media/2026-11-10-feed-1-1.jpg"
    content.save(post(1, media=[url], media_from_slides=True), "drafts")
    klapka.sync("cli", client=at)
    assert klapka.F_PREVIEW not in at.row("2026-11-10-feed-1")   # not pushed yet: no broken preview

    online.add(url)
    monkeypatch.setattr(klapka, "_reachable", {})
    assert klapka.sync("approve", client=at)["updated"] == 1      # pushed: now it goes out
    assert at.row("2026-11-10-feed-1")[klapka.F_PREVIEW] == [{"url": url}]


def test_preview_carries_the_whole_carousel_once_every_slide_is_online(queue, monkeypatch):
    urls = [f"https://raw.example/media/2026-11-10-feed-1-{n}.jpg" for n in (1, 2, 3)]
    online = set(urls[:2])
    monkeypatch.setattr(klapka, "_reachable", {})
    monkeypatch.setattr(klapka.requests, "head",
                        lambda url, **kw: type("R", (), {"status_code": 200 if url in online else 404})())
    at = FakeAirtable()
    content.save(post(1, media=urls, media_from_slides=True), "drafts")
    klapka.sync("cli", client=at)
    assert klapka.F_PREVIEW not in at.row("2026-11-10-feed-1")   # slide 3 not online yet
    online.add(urls[2])
    monkeypatch.setattr(klapka, "_reachable", {})
    klapka.sync("approve", client=at)
    assert at.row("2026-11-10-feed-1")[klapka.F_PREVIEW] == [{"url": u} for u in urls]


def test_heartbeat_carries_the_day_plan_and_a_new_plan_goes_out_right_away(queue):
    import json

    at = FakeAirtable()
    content.save(post(1, format="list"), "approved")
    klapka.sync("publish", now=T0, client=at)
    plan = json.loads(at.beat()[klapka.F_DAY_PLAN])
    [today, tomorrow] = plan["days"]
    assert today["date"] == "2026-11-09" and [s["post_id"] for s in today["slots"]] == ["2026-11-10-feed-1"]
    assert tomorrow["slots"] == []
    assert klapka.F_DAY_PLAN not in at.row("2026-11-10-feed-1")   # only the technical row has it

    at.log.clear()
    assert klapka.sync("publish", now=at_hour(2), client=at)["calls"] == 0   # same plan: nothing to send
    content.save(post(2, format="moodboard"), "approved")                  # approved locally: new plan
    result = klapka.sync("publish", now=at_hour(3), client=at)
    assert result["heartbeat"] and result["created"] == 1
    plan = json.loads(at.beat()[klapka.F_DAY_PLAN])
    assert len(plan["days"][0]["slots"]) == 2
    at.log.clear()
    assert klapka.sync("publish", now=at_hour(4), client=at)["calls"] == 0
    # A new day is a new plan, sent with the first run after midnight in New York.
    assert klapka.sync("publish", now=at_hour(10), client=at)["calls"] == 0     # 18:07 NY, still today
    assert klapka.sync("publish", now=at_hour(16), client=at)["heartbeat"]      # 00:07 NY, next day


def test_a_carousel_going_out_as_a_reel_shows_as_a_reel_with_its_song(queue, monkeypatch):
    monkeypatch.setattr(klapka, "_is_public", lambda url: True)
    item = post(1, reel={"video": "https://x/v.mp4", "cover": "https://x/c.jpg"},
                music={"audio_id": "1", "title": "Little Life", "artist": "Robert Gromotka"})
    fields = klapka.fields_for(item, "approved", "America/New_York", "naturizz")
    assert fields[F_KIND] == "reel" and fields[klapka.F_MUSIC] == "Little Life – Robert Gromotka"
    assert fields[klapka.F_VIDEO] == "https://x/v.mp4"
    # Published as a carousel after all (Reel refused): it shows as what it is.
    done = dict(item, reel_error="refused", published_at="2026-11-10T11:30-05:00")
    fields = klapka.fields_for(done, "published", "America/New_York", "naturizz")
    assert fields[F_KIND] == "karusel"
    assert fields[klapka.F_MUSIC] == "Little Life – Robert Gromotka"   # to add in the app


def test_published_carousel_carries_its_song_and_link_for_the_app(queue):
    item = post(1, published_at="2026-11-10T11:30-05:00", permalink="https://www.instagram.com/p/x/",
                music={"audio_id": "1", "title": "Yellow", "artist": "Coldplay"})
    fields = klapka.fields_for(item, "published", "America/New_York", "naturizz")
    assert fields[klapka.F_MUSIC] == "Yellow – Coldplay" and fields[klapka.F_LINK] == "https://www.instagram.com/p/x/"
    assert klapka.F_MUSIC_DONE not in fields      # Simon's box: never written by the sync
