import json
from types import SimpleNamespace

import pytest
from PIL import Image

from igbot import links


@pytest.mark.parametrize("url,platform,details", [
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=3", "youtube", {"id": "jNQXAC9IVRw"}),
    ("https://youtu.be/jNQXAC9IVRw?si=x", "youtube", {"id": "jNQXAC9IVRw"}),
    ("https://youtube.com/shorts/jNQXAC9IVRw", "youtube", {"id": "jNQXAC9IVRw"}),
    ("https://www.tiktok.com/@some.user/video/7312345678901234567?lang=cs", "tiktok",
     {"author": "some.user", "id": "7312345678901234567"}),
    ("https://www.instagram.com/p/C1abcDEF/", "instagram_post", {"username": None, "shortcode": "C1abcDEF"}),
    ("https://www.instagram.com/organic__101_/reel/DA1b2C3/", "instagram_post",
     {"username": "organic__101_", "shortcode": "DA1b2C3"}),
    ("https://www.instagram.com/organic__101_/?igsh=abc", "instagram_profile", {"username": "organic__101_"}),
    ("https://example.com/x", "unknown", {}),
])
def test_classify(url, platform, details):
    assert links.classify(url) == (platform, details)


def test_iso_duration():
    assert links._seconds("PT1M3S") == 63
    assert links._seconds("PT2H") == 7200
    assert links._seconds(None) is None


class FakeResponse:
    def __init__(self, data, ok=True):
        self._data, self.ok = data, ok

    def json(self):
        return self._data

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("http error")


def test_youtube_data_api(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("/videos"):
            return FakeResponse({"items": [{
                "snippet": {"title": "T", "description": "D", "channelId": "C", "channelTitle": "Kanál",
                            "publishedAt": "2026-10-01T10:00:00Z", "tags": ["a"],
                            "thumbnails": {"high": {"url": "https://i.ytimg.com/h.jpg"}}},
                "statistics": {"viewCount": "1500", "likeCount": "90", "commentCount": "12"},
                "contentDetails": {"duration": "PT45S"}}]})
        if url.endswith("/channels"):
            return FakeResponse({"items": [{"statistics": {"subscriberCount": "3000"}}]})
        return FakeResponse({}, ok=False)  # comments disabled

    monkeypatch.setattr(links.requests, "get", fake_get)
    info = links.fetch_youtube("jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw")
    assert calls == ["videos", "channels", "commentThreads"]
    assert (info["views"], info["likes"], info["comments_count"], info["author_followers"]) == (1500, 90, 12, 3000)
    assert info["duration_s"] == 45 and info["thumbnail_url"].endswith("h.jpg")
    assert any("komentáře" in m for m in info["missing"])


def test_youtube_without_key_uses_oembed(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(links.requests, "get", lambda url, params=None, timeout=None: FakeResponse(
        {"title": "T", "author_name": "A", "thumbnail_url": "https://i.ytimg.com/x.jpg"}))
    info = links.fetch_youtube("jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw")
    assert info["source"] == "youtube-oembed" and info["author"] == "A"


def test_tiktok_oembed_without_metadata_falls_back_to_url_author(monkeypatch):
    monkeypatch.setattr(links.requests, "get", lambda url, params=None, timeout=None: FakeResponse(
        {"html": "<iframe>", "embed_product_id": "731"}))
    url = "https://www.tiktok.com/@some.user/video/731"
    info = links.fetch_tiktok(url, links.classify(url)[1])
    assert info["author"] == "some.user" and info["id"] == "731"
    assert any("screenshot" in m for m in info["missing"])


class FakeIG:
    def account_posts(self, username, limit):
        return {"followers_count": 2000}, [
            {"permalink": "https://www.instagram.com/p/OTHER/", "media_type": "IMAGE"},
            {"permalink": "https://www.instagram.com/reel/DA1b2C3/", "media_type": "VIDEO",
             "media_product_type": "REELS", "caption": "Popisek", "like_count": 50,
             "comments_count": 4, "view_count": 9000, "timestamp": "2026-10-01T10:00:00+0000"},
        ]


def test_instagram_post_found_by_shortcode():
    url = "https://www.instagram.com/organic__101_/reel/DA1b2C3/"
    info = links.fetch(url, ig=FakeIG())
    assert (info["views"], info["likes"], info["author_followers"], info["format"]) == (9000, 50, 2000, "REELS")


def test_instagram_post_needs_author():
    with pytest.raises(LookupError, match="--account"):
        links.fetch("https://www.instagram.com/p/C1abcDEF/", ig=FakeIG())
    with pytest.raises(LookupError, match="není mezi"):
        links.fetch("https://www.instagram.com/p/MISSING/", ig=FakeIG(), account="someone")


class FakeClient:
    def __init__(self):
        self.content = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self.parse))

    def parse(self, **kwargs):
        self.content = kwargs["messages"][0]["content"]
        assert kwargs["fallbacks"] == "default"
        result = links.LinkAnalysis(
            summary="Krátký tip.", hook="otázka v prvních 2 s", format="talking head",
            structure=["háček", "tip", "výzva"], why_it_works=["konkrétní"], performance_read="nad průměrem",
            audience_signals=[], ideas_for_us=["náš vlastní tip"], missing_data=[])
        return SimpleNamespace(stop_reason="end_turn", parsed_output=result)


def test_analyze_with_screenshot_render_and_log(tmp_path, monkeypatch):
    monkeypatch.setattr(links, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(links, "LOG_PATH", tmp_path / "inspected.jsonl")
    shot = tmp_path / "shot.png"
    Image.new("RGB", (1080, 1920), "white").save(shot)

    url = "https://www.tiktok.com/@some.user/video/731"
    info = links.screenshot_only(url, "oEmbed bez popisku")
    client = FakeClient()
    analysis = links.analyze(info, {"niche": {"name": "test"}}, client=client, images=[shot], note="1,2 mil. zhlédnutí")
    payload = json.loads(client.content[0]["text"])
    assert payload["prispevek"]["poznamka_od_uzivatele"] == "1,2 mil. zhlédnutí"
    assert [b["type"] for b in client.content] == ["text", "image"]

    text = links.render(info, analysis)
    assert "# Tiktok: neznámý autor" in text and "oEmbed bez popisku" in text
    path = links.save(info, analysis, text)
    assert path.exists()
    assert links.recent_inspections()[0]["ideas_for_us"] == ["náš vlastní tip"]
