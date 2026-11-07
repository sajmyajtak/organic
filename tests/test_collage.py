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
