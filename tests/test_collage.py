import numpy as np
import pytest
from PIL import Image, ImageDraw

from igbot import collage, cutout, photos


def _blob(path, size=(400, 300), color=(180, 90, 40), shape="ellipse"):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    getattr(d, shape)([10, 10, size[0] - 10, size[1] - 10], fill=(*color, 255))
    img.save(path)
    return path


def _cand(title="", keywords=""):
    return photos.Candidate("openverse", "x", "u", "u", "cc0", "", "", title, keywords)


@pytest.mark.parametrize("query,title,keywords,expected", [
    ("apple pie", "Apple Pie", "food pie", 2),
    ("apple pie", "Pumpkin pie for supper", "pie", 0),
    ("basket of apples", "Red apples at the market", "", 2),
    ("apple pie", "Made apple pie and pumpkin pie for supper tonight with the family", "", 1),
    ("candle", "Candle AI generated", "", 0),
    ("knitted sweater", "Hand knit sweaters", "", 1),
    ("cup of tea", "Black tea in a cup", "", 2),
])
def test_relevance(query, title, keywords, expected):
    assert photos.relevance(_cand(title, keywords), query) == expected


def test_score_prefers_whole_single_objects():
    def cut(mask):
        a = np.zeros((200, 200, 4), np.uint8)
        a[..., 3] = mask * 255
        return Image.fromarray(a, "RGBA")

    yy, xx = np.mgrid[0:200, 0:200]
    centred = ((xx - 100) ** 2 + (yy - 100) ** 2 < 60 ** 2).astype(np.uint8)
    cut_off = ((xx - 190) ** 2 + (yy - 100) ** 2 < 60 ** 2).astype(np.uint8)
    empty = np.zeros((200, 200), np.uint8)
    assert cutout.score(cut(centred)) > 0.6
    assert cutout.score(cut(cut_off)) < cutout.score(cut(centred)) - 0.3
    assert cutout.score(cut(empty)) == 0


def test_clean_drops_specks_and_trims():
    a = np.zeros((300, 300, 4), np.uint8)
    a[50:150, 60:200, 3] = 255     # object
    a[280:283, 280:283, 3] = 255   # speck far away
    out = cutout.clean(Image.fromarray(a, "RGBA"))
    assert out.size == (140, 100)


def test_render_slide_places_every_item(tmp_path, capsys):
    items = [(f"Thing {n}", _blob(tmp_path / f"{n}.png", (300 + 20 * n, 260),
                                  shape="ellipse" if n % 2 else "rectangle")) for n in range(13)]
    out = collage.render_slide("The art of autumn living 🍂", items, tmp_path / "s.jpg", handle="naturizz")
    img = Image.open(out)
    assert img.size == collage.SIZE and img.format == "JPEG"
    assert "bez místa" not in capsys.readouterr().out


def test_packer_never_overlaps():
    occ = np.zeros((40, 40), bool)
    occ[:, :20] = True
    fp = np.ones((10, 10), bool)
    import random
    y, x = collage._place(occ, fp, random.Random(0))
    assert x >= 20 and not occ[y:y + 10, x:x + 10].any()
    occ[:] = True
    assert collage._place(occ, fp, random.Random(0)) is None


def test_render_post_with_credits_and_no_duplicate_photos(tmp_path):
    calls = []

    def fake_find(query, exclude=None):
        calls.append((query, set(exclude or ())))
        n = len(calls)
        return {"id": f"id{n}", "score": 0.9, "license": "cc0", "path": _blob(tmp_path / f"c{n}.png")}

    plan = {"slides": [{"title": "The autumn kitchen",
                        "items": [{"label": "Sourdough", "queries": ["sourdough bread"]},
                                  {"label": "Honey", "query": "honey jar"}]}],
            "cta": {"title": "Save this", "body": "Follow for more.", "items": [{"label": "Mug"}]}}
    paths, credits = collage.render_post(plan, tmp_path / "out", handle="naturizz", find=fake_find)
    assert [p.name for p in paths] == ["01.jpg", "02.jpg"]
    assert [c["label"] for c in credits] == ["Sourdough", "Honey", "Mug"]
    assert calls[2][1] == {"id1", "id2"}  # later items can't reuse earlier photos
    assert "path" not in credits[0]


def test_brand_colours_drive_the_style():
    style = collage.Style.from_brand({"background": "#101010", "foreground": "#202020", "accent": "#303030"})
    assert (style.paper, style.ink, style.label, style.accent) == ("#101010", "#202020", "#202020", "#303030")
    assert collage.Style.from_brand(None) == collage.STYLE


def test_queue_item_with_items_renders_as_collage_with_credits(tmp_path, monkeypatch):
    from igbot import publish, render

    def fake_find(query, exclude=None):
        n = len(exclude or ())
        return {"id": f"{query}-{n}", "score": 0.9, "license": "cc0", "path": _blob(tmp_path / f"{query}.png")}

    monkeypatch.setattr(cutout, "find_cutout", fake_find)
    things = [{"label": f"Thing {n}", "queries": [f"thing{n}"]} for n in range(4)]
    item = {"id": "2026-11-10-feed-1", "kind": "carousel", "date": "2026-11-10", "time": "11:30",
            "slides": [{"title": "The art of slow mornings", "items": things},
                       {"title": "Save this", "body": "Follow @naturizz", "items": things[:3]}],
            "caption": "Slow mornings ☕", "hashtags": []}
    paths = render.render_item(item, tmp_path / "out", render.Theme(handle="naturizz"))
    assert [p.name for p in paths] == ["2026-11-10-feed-1-1.jpg", "2026-11-10-feed-1-2.jpg"]
    assert Image.open(paths[0]).size == collage.SIZE
    assert [c["label"] for c in item["photo_credits"]] == [t["label"] for t in things] + ["Thing 0", "Thing 1", "Thing 2"]
    assert publish.alt_text(item["slides"][0]) == "The art of slow mornings: Thing 0, Thing 1, Thing 2, Thing 3"

    from igbot import content
    assert content.validate(item) == []
    item["slides"][0]["items"] = things[:2]
    assert any("2 předmětů" in p for p in content.validate(item))


def test_find_cutout_skips_photos_clip_says_are_not_the_object(tmp_path, monkeypatch):
    from igbot import cutout, photos, relevance

    cyclist = photos.Candidate("commons", "1", "u1", "u1", "cc0", "s", "a", "With Bicycle at Walnut Beach")
    nuts = photos.Candidate("commons", "2", "u2", "u2", "cc0", "s", "a", "Walnuts in a bowl")
    monkeypatch.setattr(photos, "search", lambda q, limit: [cyclist, nuts])
    monkeypatch.setattr(photos, "rejected", lambda: set())
    seen = []
    monkeypatch.setattr(relevance, "match", lambda img, what: seen.append(img.mode) or
                        (0.05 if img.mode == "RGB" and img.getpixel((0, 0)) == (0, 0, 0) else 0.9))
    cut = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    cut.paste((120, 80, 40, 255), (150, 150, 450, 450))
    monkeypatch.setattr(cutout, "remove_background", lambda img: cut.copy())
    monkeypatch.setattr(photos, "download", lambda url, max_side=0: Image.new("RGB", (600, 600),
                                                                             "black" if url == "u1" else "white"))
    found = cutout.find_cutout("walnuts", cache=tmp_path)
    assert found["id"] == "2" and found["match"] == 0.9
    assert seen.count("RGB") == 2 and seen.count("RGBA") == 1  # both thumbnails screened, only nuts cut


def test_rejected_photos_are_never_used(tmp_path, monkeypatch):
    from igbot import photos

    monkeypatch.setattr(photos, "REJECTS", tmp_path / "rejects.txt")
    assert photos.rejected() == set()
    photos.REJECTS.write_text("# komentář\ncommons:1  # cyklista\n\nopenverse:abc\n", encoding="utf-8")
    assert photos.rejected() == {"commons:1", "openverse:abc"}
    assert photos.key(photos.Candidate("commons", "1", "", "", "", "", "")) == "commons:1"
    assert photos.key({"provider": "openverse", "id": "abc"}) == "openverse:abc"


def test_slide_layout_by_position_and_override():
    from igbot import content
    slides = [{"title": "The art of cabin living"}, {"title": "Cabin evenings"},
              {"title": "Follow for more slow living", "body": "Save this"}]
    assert [content.slide_layout(slides, n) for n in range(3)] == ["cover", "board", "cta"]
    assert content.slide_layout([{"title": "Natural home essentials"}], 0) == "board"  # single image
    assert content.slide_layout([{"title": "A", "layout": "board"}, {"title": "B"}], 0) == "board"


def test_cover_and_closing_slide_need_no_labels_but_inner_slides_do():
    from igbot import content
    things = [{"queries": [f"thing {n}"]} for n in range(4)]
    item = {"id": "x", "kind": "carousel", "caption": "Slow ☕", "hashtags": [],
            "slides": [{"title": "The art of slow mornings", "items": things},
                       {"kicker": "This", "title": "A slow morning",
                        "items": [{"label": f"Thing {n}", "queries": ["q"]} for n in range(4)]},
                       {"title": "Follow for slower mornings", "body": "Send this to a friend"}]}
    assert content.validate(item) == []
    item["slides"][1]["items"][0]["label"] = ""
    assert any("bez popisku" in p for p in content.validate(item))
    item["slides"][1]["items"][0]["label"] = "Teapot"
    item["slides"][1]["title"] = "This: a slow morning"
    assert any("dvojtečkou" in p for p in content.validate(item))


def test_cover_and_closing_slide_print_no_labels_and_closing_reuses_stickers(tmp_path, monkeypatch):
    calls = []

    def fake_find(query, exclude=None):
        calls.append(query)
        n = len(calls)
        return {"id": f"id{n}", "score": 0.9, "license": "cc0",
                "path": _blob(tmp_path / f"c{n}.png", (260 + 15 * (n % 4), 220))}

    printed = []
    real = collage._prepare
    monkeypatch.setattr(collage, "_prepare", lambda label, *a, **kw: printed.append(label) or real(label, *a, **kw))
    slides = [{"title": "The art of cabin living", "items": [{"label": f"Mood {n}", "queries": [f"m{n}"]} for n in range(9)]},
              {"title": "Cabin evenings", "items": [{"label": f"Thing {n}", "queries": [f"t{n}"]} for n in range(5)]},
              {"title": "Follow for more slow living", "body": "Save this", "echo": ["Mood 2", "Thing 1", "Nope"]}]
    paths, credits = collage.render_slides(slides, tmp_path / "out", handle="naturizz", find=fake_find)
    assert len(paths) == 3 and all(Image.open(p).size == collage.SIZE for p in paths)
    assert len(calls) == 14 and len(credits) == 14          # the closing slide searched and credited nothing
    assert set(printed) - {""} <= {f"Thing {n}" for n in range(5)}  # labels only on the inner slide
    assert {f"Thing {n}" for n in range(5)} <= set(printed)


def test_kicker_is_small_spaced_capitals_in_the_accent_colour():
    lines = collage._title_lines("A slow kitchen", "", collage.STYLE, 900, 138, kicker="Not this")
    assert lines[0].text == "NOT THIS" and lines[0].fill == collage.STYLE.accent and lines[0].tracking > 0
    assert lines[0].font.size < lines[1].font.size
    assert lines[0].width > collage._text_w(lines[0].font, "NOT THIS")


def test_closing_fan_stays_inside_the_page(tmp_path):
    import random
    cuts = [Image.open(_blob(tmp_path / f"{n}.png", (600, 200))).convert("RGBA") for n in range(6)]
    items = collage._fan(cuts, collage.STYLE, random.Random(0))
    assert len(items) == collage.FAN_MAX
    left = min(i.pos[0] for i in items) + collage.SIZE[0] / 2
    right = max(i.pos[0] + i.image.width for i in items) + collage.SIZE[0] / 2
    assert left >= 0 and right <= collage.SIZE[0]
