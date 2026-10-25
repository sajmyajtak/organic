from PIL import Image

from igbot import analyze


class FakeIG:
    def __init__(self):
        self.calls = []

    def business_discovery(self, username, media_limit=25, after=None):
        self.calls.append(after)
        pages = {
            None: {"data": [self._post(1, "IMAGE", 90, 10), self._post(2, "CAROUSEL_ALBUM", 40, 0)],
                   "paging": {"cursors": {"after": "c1"}}},
            "c1": {"data": [self._post(3, "VIDEO", 5, 5, views=3000)], "paging": {"cursors": {}}},
        }
        return {"username": username, "followers_count": 1000, "media_count": 3, "media": pages[after]}

    def account_posts(self, username, limit):
        from igbot.instagram import Instagram
        return Instagram.account_posts(self, username, limit)

    @staticmethod
    def _post(n, media_type, likes, comments, views=None):
        return {"media_type": media_type, "like_count": likes, "comments_count": comments,
                "view_count": views, "caption": f"Post {n} #tip #Zdravi",
                "permalink": f"https://www.instagram.com/p/{n}/",
                "timestamp": f"2026-10-0{n}T16:00:00+0000", "media_url": f"https://cdn.example/{n}.jpg"}


def test_from_api_follows_pagination_and_computes_rates():
    ig = FakeIG()
    profile, posts = analyze.from_api(ig, "zdroj", limit=10)
    assert ig.calls == [None, "c1"]
    assert profile["followers_count"] == 1000 and "media" not in profile
    assert [p["ref"] for p in posts] == ["p1", "p2", "p3"]
    assert posts[0]["engagement_rate"] == 0.1
    assert posts[2]["views"] == 3000


def test_compute_stats_groups_formats_and_hashtags():
    profile, posts = analyze.from_api(FakeIG(), "zdroj", limit=10)
    stats = analyze.compute_stats(profile, posts, "Europe/Prague")
    assert stats["posts_analyzed"] == 3
    assert stats["top_posts"][0]["ref"] == "p1"
    assert set(stats["by_format"]) == {"IMAGE", "CAROUSEL_ALBUM", "VIDEO"}
    assert ("tip", 3) in stats["top_hashtags"] and ("zdravi", 3) in stats["top_hashtags"]
    assert stats["hour_counts"] == {18: 3}  # 16:00 UTC is 18:00 in Prague (summer time)


def test_screenshot_mode_and_full_report(tmp_path, monkeypatch):
    shots = tmp_path / "shots"
    shots.mkdir()
    Image.new("RGB", (1080, 1920), "white").save(shots / "grid.png")
    (shots / "notes.txt").write_text("ignored")
    posts = analyze.from_images(shots)
    assert [p["ref"] for p in posts] == ["grid.png"]

    def fake_call(client, cfg, system, content, schema):
        if schema is analyze.Labels:
            assert any(block["type"] == "image" for block in content)
            return analyze.Labels(posts=[analyze.PostLabel(
                ref="grid.png", topic="recepty", pillar="Recepty", format_style="foto s nadpisem",
                hook="rychlá večeře", visual_style="světlé fotky", cta="ulož si",
                visible_metrics="1,2 tis. lajků", why_it_works="praktické")])
        pillar = analyze.PillarShare(name="Recepty", share=0.6, description="rychlé recepty")
        return analyze.Report(
            summary="Účet o rychlých receptech.", audience="mladé rodiny", voice="přátelský",
            pillars=[pillar], formats_that_work=[analyze.Finding(insight="karusely", evidence=["grid.png"])],
            topics_that_work=[], weak_spots=[], posting_pattern="denně", monetization_signals=[],
            opportunities_for_us=["česká sezónní verze"], similar_account_keywords=["recepty"],
            niche_profile=analyze.NicheProfile(name="Rychlé recepty", description="...", audience="rodiny",
                                               voice="přátelský", pillars=[pillar], formats=["karusel"],
                                               avoid=["kopírování"]))

    monkeypatch.setattr(analyze, "_call", fake_call)
    monkeypatch.setattr(analyze, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(analyze, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(analyze.anthropic, "Anthropic", lambda: None)

    md = analyze.run({"account": {"timezone": "Europe/Prague"}}, "zdroj", images=shots)
    text = md.read_text(encoding="utf-8")
    assert "# Analýza @zdroj" in text and "karusely (grid.png)" in text
    assert "Rychlé recepty" in (tmp_path / "data" / "niche_profile.yaml").read_text(encoding="utf-8")
