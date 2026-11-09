import subprocess
from datetime import date

import imageio_ffmpeg
import pytest
from PIL import Image

from igbot import content, music, publish, reel
from igbot.instagram import InstagramError

BRAND = {"background": "#E5D5BA", "foreground": "#3A2517", "accent": "#9C4F28"}


def test_timeline_holds_each_slide_and_swipes_to_the_next():
    pos = reel.timeline(5)
    assert pos[0] == 0 and pos[-1] == 4
    assert all(b >= a for a, b in zip(pos, pos[1:]))          # never swipes back
    assert {0.0, 1.0, 2.0, 3.0, 4.0} <= set(pos)
    assert 10 <= reel.duration(5) <= 20


def test_render_writes_a_9_16_video_with_an_audio_track(tmp_path, monkeypatch):
    monkeypatch.setattr(reel, "HOLD_FIRST", 0.2)
    monkeypatch.setattr(reel, "HOLD", 0.2)
    monkeypatch.setattr(reel, "HOLD_LAST", 0.2)
    slides = [Image.new("RGB", (1080, 1350), c) for c in ("#E5D5BA", "#C9B28F")]
    out = reel.render(slides, tmp_path / "r.mp4", BRAND)
    info = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(out)], capture_output=True, text=True).stderr
    assert "1080x1920" in info and "h264" in info and "Audio: aac" in info
    cover = Image.open(reel.cover(slides, tmp_path / "c.jpg", BRAND))
    assert cover.size == (1080, 1920)


class FakeIG:
    user_id = "1"

    def __init__(self, hot, library=()):
        self.hot, self.lib = hot, list(library)

    def get(self, path, **params):
        assert path == "ig_audio"
        if params.get("search_query"):
            return {"audio": self.lib}
        return {"audio": self.hot}


def track(aid, title, artist="A"):
    return {"audio_id": aid, "title": title, "display_artist": artist}


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "CONTENT_DIR", tmp_path / "content")
    (tmp_path / "music.yaml").write_text(
        "tracks:\n"
        "  - {id: '1', title: Little Life, artist: R, popular: true, moods: [cozy, home, morning]}\n"
        "  - {id: '2', title: What A Wonderful World, artist: L, popular: true, moods: [nostalgic]}\n"
        "  - {id: '3', title: Christmas Market, artist: E, popular: true, moods: [winter, cozy], months: [12]}\n"
        "  - {id: '4', title: Riverbank, artist: G, popular: false, moods: [cozy]}\n", encoding="utf-8")
    monkeypatch.setattr(music, "CURATED", tmp_path / "music.yaml")
    return tmp_path


def post(fmt="moodboard", title="The art of cabin living", **extra):
    return {"id": "2026-11-20-feed-1", "kind": "carousel", "format": fmt, "slides": [{"title": title}], **extra}


def test_music_follows_trends_and_the_post_mood(queue):
    ig = FakeIG([track("1", "Little Life"), track("2", "What A Wonderful World"), track("9", "Party Anthem")])
    then = music.pick(ig, post("then_vs_now", "How we used to live"), today=date(2026, 11, 20))
    assert then["audio_id"] == "2" and then["trending"]
    cozy = music.pick(ig, post(), today=date(2026, 11, 20))
    assert cozy["audio_id"] == "1" and "9" not in [a["audio_id"] for a in cozy["alternatives"]]


def test_music_avoids_recent_songs_and_out_of_season_ones(queue):
    ig = FakeIG([track("1", "Little Life"), track("3", "Christmas Market")])
    nov = music.pick(ig, post(), today=date(2026, 11, 20), taken=["1"])
    assert nov["audio_id"] not in ("1", "3")                  # used lately / Christmas in November
    dec = music.pick(ig, post(title="Winter at home"), today=date(2026, 12, 10), taken=["1"])
    assert dec["audio_id"] == "3"


def test_new_trending_song_counts_only_if_it_sounds_like_the_niche(queue):
    ig = FakeIG([track("7", "Cozy Piano Morning"), track("8", "Club Banger")])
    picked = music.pick(ig, post(), today=date(2026, 11, 20), taken=["1", "4"])
    ids = [picked["audio_id"]] + [a["audio_id"] for a in picked["alternatives"]]
    assert ids[0] == "7" and "8" not in ids


def test_library_is_the_fallback(queue, monkeypatch):
    monkeypatch.setattr(music, "CURATED", queue / "missing.yaml")
    ig = FakeIG([], library=[track("50", "Calm Folk")])
    assert music.pick(ig, post(), today=date(2026, 11, 20))["audio_id"] == "50"


class ReelIG:
    host = "graph.facebook.com"

    def __init__(self, refuse=()):
        self.refuse, self.calls = set(refuse), []

    def publish_reel(self, video_url, caption, cover_url=None, ai_generated=False, paid_partnership=False,
                     audio_id=None):
        self.calls.append(("reel", video_url, cover_url, audio_id))
        if audio_id in self.refuse or "*" in self.refuse:
            raise InstagramError("400 audio not available")
        return "r1"

    def publish_carousel(self, urls, caption, alts, ai_generated=False, paid_partnership=False):
        self.calls.append(("carousel", urls))
        return "c1"


def reel_item(**extra):
    return {"id": "2026-11-20-feed-1", "kind": "carousel", "format": "moodboard", "caption": "Slow 🌿",
            "media": ["https://x/1.jpg", "https://x/2.jpg"], "media_from_slides": True,
            "slides": [{"title": "A"}, {"title": "B"}],
            "reel": {"video": "https://x/v.mp4", "cover": "https://x/c.jpg"},
            "music": {"audio_id": "1", "title": "Little Life", "artist": "R",
                      "alternatives": [{"audio_id": "2", "title": "What A Wonderful World", "artist": "L"}]},
            **extra}


def test_carousel_goes_out_as_a_reel_with_its_song(queue):
    ig, item = ReelIG(), reel_item()
    assert publish.publish_item(ig, item, None, dry_run=False) == ["r1"]
    assert ig.calls == [("reel", "https://x/v.mp4", "https://x/c.jpg", "1")]
    assert item["published_as"] == "reel"


def test_refused_song_falls_back_to_the_next_then_to_the_carousel(queue):
    ig, item = ReelIG(refuse={"1"}), reel_item()
    assert publish.publish_item(ig, item, None, dry_run=False) == ["r1"]
    assert [c[3] for c in ig.calls] == ["1", "2"] and item["music"]["audio_id"] == "2"
    assert item["music"]["requested"] == "Little Life – R"

    ig, item = ReelIG(refuse={"*"}), reel_item()
    assert publish.publish_item(ig, item, None, dry_run=False) == ["c1"]
    assert [c[3] for c in ig.calls[:-1]] == ["1", "2", None] and ig.calls[-1][0] == "carousel"
    assert "audio not available" in item["reel_error"] and "published_as" not in item
