from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from igbot import content, discover, publish
from igbot.render import FEED_SIZE, STORY_SIZE, Theme, render_item

TZ = "Europe/Prague"


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "CONTENT_DIR", tmp_path / "content")
    monkeypatch.setattr(publish, "BUILD_DIR", tmp_path / "build")
    return tmp_path


def carousel(**overrides):
    item = {
        "id": "2026-11-02-feed-1", "date": "2026-11-02", "time": "18:30", "kind": "carousel",
        "slides": [{"title": "Háček", "body": ""}, {"title": "1. Tip", "body": "Text tipu 😀"}],
        "caption": "Popisek", "hashtags": ["zdravi", "#etikety"], "sponsored": False,
    }
    item.update(overrides)
    return item


def test_full_caption_appends_normalized_hashtags():
    assert content.full_caption(carousel()) == "Popisek\n\n#zdravi #etikety"


def test_validate_flags_instagram_limits():
    assert content.validate(carousel()) == []
    assert "chybí popisek" in content.validate(carousel(caption=""))
    assert content.validate(carousel(hashtags=[f"t{i}" for i in range(5)])) == []
    assert any("5 hashtagů" in p for p in content.validate(carousel(hashtags=[f"t{i}" for i in range(6)])))
    assert any("2–20" in p for p in content.validate(carousel(slides=[{"title": "x"}])))
    assert any("Reklama" in p for p in content.validate(carousel(sponsored=True)))
    # the label must open the post, not hide at the end
    assert any("Reklama" in p for p in content.validate(carousel(sponsored=True, caption="Popisek #reklama")))
    assert content.validate(carousel(sponsored=True, caption="#reklama Popisek")) == []
    assert content.validate(carousel(sponsored=True, caption="Placené partnerství s X\nPopisek")) == []


def test_reel_needs_video_and_ai_media_gets_disclosure():
    reel = carousel(kind="reel", slides=[], script={"hook": "x"})
    assert any("chybí video" in p for p in content.validate(reel))
    assert content.validate(carousel(kind="reel", slides=[], media=["media/r.mp4"])) == []
    assert "Vytvořeno s pomocí AI." in content.full_caption(carousel(ai_media=True))
    assert "Vytvořeno s pomocí AI." not in content.full_caption(carousel())


def test_story_needs_no_caption():
    story = {"id": "s", "date": "2026-11-02", "time": "08:00", "kind": "story", "slides": [{"title": "Ahoj"}]}
    assert content.validate(story) == []


def test_render_sizes_and_jpeg(tmp_path):
    paths = render_item(carousel(), tmp_path, Theme(handle="ucet"))
    assert len(paths) == 2
    with Image.open(paths[0]) as img:
        assert img.size == FEED_SIZE and img.format == "JPEG"
    story = {"id": "s", "kind": "story", "slides": [{"title": "Ahoj", "body": "Jak se máš?"}]}
    with Image.open(render_item(story, tmp_path, Theme())[0]) as img:
        assert img.size == STORY_SIZE


def test_due_and_dry_run_publish_do_not_move_files(queue):
    content.save(carousel(), "approved")
    later = datetime(2026, 11, 2, 18, 45, tzinfo=ZoneInfo(TZ))
    earlier = datetime(2026, 11, 2, 18, 0, tzinfo=ZoneInfo(TZ))
    assert content.due(TZ, earlier) == []
    assert [i["id"] for i in content.due(TZ, later)] == ["2026-11-02-feed-1"]

    cfg = {"account": {"timezone": TZ, "handle": "ucet"}, "brand": {}}
    assert publish.publish_due(cfg, dry_run=True, now=later) == 0
    assert [p.name for p in (queue / "content" / "approved").glob("*.yaml")] == ["2026-11-02-feed-1.yaml"]


def test_missed_slot_goes_to_failed(queue, monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "1")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setattr(publish, "quota_left", lambda ig: None)
    content.save(carousel(), "approved")
    cfg = {"account": {"timezone": TZ}, "brand": {}}
    publish.publish_due(cfg, now=datetime(2026, 11, 3, 9, 0, tzinfo=ZoneInfo(TZ)))
    failed = content.items("failed")
    assert failed and "zmeškaný" in failed[0]["error"]


class FakeIG:
    def business_discovery(self, username):
        posts = {
            "seed": [
                {"caption": "Tip dne s @friend_acc a @other.acc", "like_count": 90, "comments_count": 10},
                {"caption": "Druhý post @friend_acc", "like_count": 10, "comments_count": 0},
            ],
        }
        return {"followers_count": 1000, "media_count": 2, "media": {"data": posts.get(username, [])}}


def test_discover_ranks_posts_and_promotes_repeated_mentions(tmp_path, monkeypatch):
    monkeypatch.setattr(discover, "DATA_DIR", tmp_path)
    monkeypatch.setattr(discover, "TRACKED", tmp_path / "tracked_accounts.txt")
    result = discover.run(FakeIG(), ["seed"], own_handle="me")
    assert result["promoted"] == ["friend_acc"]
    assert (tmp_path / "tracked_accounts.txt").read_text().split() == ["friend_acc"]
    assert discover.tracked(["seed"]) == ["seed", "friend_acc"]
    inspiration = (tmp_path / "inspiration.json").read_text(encoding="utf-8")
    assert "Tip dne" in inspiration


class RecordingIG:
    host = "graph.facebook.com"

    def __init__(self, used):
        self.calls, self.used = [], used

    def publishing_quota(self):
        return {"quota_usage": self.used, "config": {"quota_total": 50}}

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return f"m{len(self.calls)}"
        return record


@pytest.mark.parametrize("used,expected", [(48, ["publish_story", "publish_reel"]), (49, ["publish_story"])])
def test_publish_uses_public_media_urls_and_respects_quota(queue, monkeypatch, used, expected):
    reel = carousel(id="2026-11-02-feed-1", kind="reel", slides=[], paid_partnership=True,
                    caption="Reklama: popisek", sponsored=True, media=["https://pub.example/r.mp4"])
    story = {"id": "2026-11-02-story-1", "date": "2026-11-02", "time": "18:00", "kind": "story",
             "slides": [{"title": "Ahoj"}]}
    content.save(reel, "approved")
    content.save(story, "approved")
    ig = RecordingIG(used)
    monkeypatch.setattr(publish.Instagram, "from_env", classmethod(lambda cls, dry_run=False: ig))
    monkeypatch.setattr(publish.hosting, "upload", lambda files, prefix: [f"https://pub.example/{f.name}" for f in files])

    n = publish.publish_due({"account": {"timezone": TZ}, "brand": {}},
                            now=datetime(2026, 11, 2, 18, 45, tzinfo=ZoneInfo(TZ)))
    assert [c[0] for c in ig.calls] == expected and n == len(expected)
    assert ig.calls[0][2]["image_url"].endswith(".jpg")  # story graphic rendered and uploaded
    if len(expected) == 2:
        args, kwargs = ig.calls[1][1], ig.calls[1][2]
        assert args[0] == "https://pub.example/r.mp4" and kwargs["paid_partnership"] is True
    assert len(content.items("published")) == len(expected)


def test_attach_uploads_and_schedules(queue, monkeypatch, tmp_path):
    from argparse import Namespace

    from igbot.__main__ import attach_media
    import igbot.hosting as hosting
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"\x00")
    reel = carousel(kind="reel", slides=[], script={"hook_spoken": "x"}, media=[])
    content.save(reel, "drafts")
    monkeypatch.setattr(hosting, "upload", lambda files, prefix: [f"https://pub.example/{prefix}/{f.name}" for f in files])
    attach_media(Namespace(id=reel["id"], files=[video], ai=False))
    item = content.items("drafts")[0]
    assert item["media"] == [f"https://pub.example/{reel['id']}/reel.mp4"]
    assert "problems" not in item
