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
    def __init__(self, data, ok=True, status=200):
        self._data, self.ok, self.status_code = data, ok, status if ok else (status if status != 200 else 400)

    def json(self):
        return self._data

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("http error")


def test_youtube_data_api_sends_key_in_header(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "SECRET")
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url.rsplit("/", 1)[-1])
        assert "key" not in (params or {}) and headers == {"x-goog-api-key": "SECRET"}
        return FakeResponse({"items": [{
            "snippet": {"title": "T", "description": "D", "channelId": "C", "channelTitle": "Kanál",
                        "publishedAt": "2026-10-01T10:00:00Z", "tags": ["a"],
                        "thumbnails": {"high": {"url": "https://i.ytimg.com/h.jpg"}}},
            "statistics": {"viewCount": "1500", "likeCount": "90", "commentCount": "12"},
            "contentDetails": {"duration": "PT45S"}}]})

    monkeypatch.setattr(links.requests, "get", fake_get)
    info = links.fetch_youtube("jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw")
    assert calls == ["videos"]  # no subscriber counts or comments (YouTube derived-metrics policy)
    assert info["youtube_api_data"] == {"views": 1500, "likes": 90, "comments_count": 12}
    assert info["duration_s"] == 45 and info["thumbnail_url"].endswith("h.jpg")


def test_youtube_api_error_hides_key_and_falls_back_to_oembed(monkeypatch, capsys):
    monkeypatch.setenv("YOUTUBE_API_KEY", "SECRET")
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append((url, params))
        if "googleapis" in url:
            return FakeResponse({"error": {"message": "quota exceeded"}}, ok=False, status=403)
        return FakeResponse({"title": "T", "author_name": "A"})

    monkeypatch.setattr(links.requests, "get", fake_get)
    info = links.fetch_youtube("jNQXAC9IVRw", "https://www.youtube.com/embed/jNQXAC9IVRw")
    out = capsys.readouterr().out
    assert "SECRET" not in out and "HTTP 403 quota exceeded" in out
    assert info["source"] == "youtube-oembed"
    # oEmbed gets the canonical watch URL (it 404s on /embed/ links)
    assert seen[-1][1]["url"] == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert info["url"] == "https://www.youtube.com/embed/jNQXAC9IVRw"


def test_youtube_without_key_uses_oembed(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(links.requests, "get", lambda url, params=None, timeout=None, **kw: FakeResponse(
        {"title": "T", "author_name": "A", "thumbnail_url": "https://i.ytimg.com/x.jpg"}))
    info = links.fetch_youtube("jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw")
    assert info["source"] == "youtube-oembed" and info["author"] == "A"


def test_tiktok_oembed_without_metadata_falls_back_to_url_author(monkeypatch):
    monkeypatch.setattr(links.requests, "get", lambda url, params=None, timeout=None, **kw: FakeResponse(
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
    assert "# Tiktok: some.user" in text and "oEmbed bez popisku" in text
    first, second = links.save(info, analysis), links.save(info, analysis)
    assert first.name.endswith("-tiktok-731.md") and second.name.endswith("-tiktok-731-2.md")
    assert links.recent_inspections()[0]["ideas_for_us"] == ["náš vlastní tip"]


def test_classify_instagram_share_and_reserved_paths():
    assert links.classify("https://www.instagram.com/share/reel/BAxyz12345/") == ("instagram_share", {})
    assert links.classify("https://www.instagram.com/explore/") == ("unknown", {})
    assert links.classify("\ufeffhttps://youtu.be/jNQXAC9IVRw ") == ("youtube", {"id": "jNQXAC9IVRw"})
    with pytest.raises(links.FetchError, match="share"):
        links.fetch("https://www.instagram.com/share/reel/BAxyz12345/", ig=FakeIG())


def test_account_flag_accepts_at_sign():
    info = links.fetch("https://www.instagram.com/reel/DA1b2C3/", ig=FakeIG(), account="@organic__101_")
    assert info["author"] == "organic__101_"


def test_youtube_numbers_are_not_written_to_report_files(tmp_path, monkeypatch):
    monkeypatch.setattr(links, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(links, "LOG_PATH", tmp_path / "inspected.jsonl")
    info = {"platform": "youtube", "id": "jNQXAC9IVRw", "url": "u", "source": "youtube-data-api",
            "author": "Kanál", "youtube_api_data": {"views": 123456, "likes": 1, "comments_count": 2}}
    analysis = FakeClient().parse(messages=[{"content": []}], fallbacks="default").parsed_output
    assert "123 456" in links.render(info, analysis)
    saved = links.save(info, analysis).read_text(encoding="utf-8")
    assert "123 456" not in saved and "neukládají" in saved


def test_prune_youtube_and_robust_log(tmp_path, monkeypatch):
    from datetime import date
    reports, log = tmp_path / "reports", tmp_path / "inspected.jsonl"
    monkeypatch.setattr(links, "REPORTS_DIR", reports)
    monkeypatch.setattr(links, "LOG_PATH", log)
    reports.mkdir()
    (reports / "2026-09-01-youtube-old.md").write_text("x")
    (reports / "2026-10-20-youtube-new.md").write_text("x")
    (reports / "2026-09-01-tiktok-1.md").write_text("x")
    log.write_text("\n".join([
        json.dumps({"date": "2026-09-01", "platform": "youtube", "hook": "old"}),
        "{broken",
        json.dumps({"date": "2026-10-20", "platform": "youtube", "hook": "new\u2028line"}, ensure_ascii=False),
        json.dumps({"date": "2026-09-01", "platform": "tiktok", "hook": "tt"}),
    ]) + "\n", encoding="utf-8")
    links.prune_youtube(date(2026, 10, 26))
    assert sorted(p.name for p in reports.iterdir()) == ["2026-09-01-tiktok-1.md", "2026-10-20-youtube-new.md"]
    assert [r["hook"] for r in links.recent_inspections()] == ["new\u2028line", "tt"]


def test_cli_batch_continues_without_instagram_credentials(tmp_path, monkeypatch, capsys):
    from argparse import Namespace

    from igbot.__main__ import inspect_links
    monkeypatch.delenv("IG_USER_ID", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(links.requests, "get", lambda url, params=None, timeout=None, **kw: FakeResponse(
        {"title": "T", "author_name": "A"}))
    lst = tmp_path / "links.txt"
    lst.write_text("\ufeffhttps://youtu.be/jNQXAC9IVRw\n   # komentář\nhttps://www.instagram.com/u/reel/ABC/\n",
                   encoding="utf-8")
    args = Namespace(urls=[], file=lst, account=None, image=[], note=None, raw=True)
    with pytest.raises(SystemExit):
        inspect_links({}, args)
    out = capsys.readouterr().out
    assert '"source": "youtube-oembed"' in out  # YouTube still processed
    assert "CHYBA https://www.instagram.com/u/reel/ABC/" in out and "komentář" not in out
