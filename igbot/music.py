"""Popular music for a Reel, chosen for the niche and the post.

What the Audio API gives us (GET /ig_audio, audio_type=music):
  - without a query: what is trending now (real hits, the account's region),
  - with search_query: only the royalty-free library; hits can't be found by name.

So the choice is made from data/music.yaml (trending songs that fit slow,
cozy, nostalgic living, each with moods) plus whatever is trending right now
and sounds like the niche by its title. A track that is trending today wins;
the post's moods decide among them; a song isn't repeated within the last few
posts. If nothing fits, the library is searched by mood. Instagram adds the
song itself when the Reel is created (`audio_configuration`), so nothing is
downloaded and the licence is Instagram's.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

import yaml

from . import content
from .config import DATA_DIR

CURATED = DATA_DIR / "music.yaml"
TRENDING_PAGES = 2
RECENT = 4            # don't repeat a song within this many posts
# A trending track not in music.yaml is used only if its title sounds like the niche.
# Only words that say what the music is like; a title like "Golden Brown" (a song about
# heroin) must not slip in because it contains a nice word.
NICHE = re.compile(r"\b(autumn|november|winter|snow|cozy|cosy|piano|acoustic|lullaby|morning|"
                   r"rain|coffee|candle|fireplace|cabin|forest|meadow|folk)\b", re.I)
# Trending songs never suggested, whatever their title says.
BLOCKED = re.compile(r"golden brown|heroin|cocaine|weed|drunk|sex|kill", re.I)
SEASONAL = re.compile(r"christmas|xmas|santa|jingle|sleigh", re.I)
LIBRARY_QUERIES = {"cozy": "cozy folk", "calm": "soft piano", "home": "slow living", "morning": "morning coffee",
                   "autumn": "autumn", "winter": "winter piano", "cabin": "acoustic guitar calm",
                   "nostalgic": "nostalgic"}


def curated() -> list[dict]:
    if not CURATED.exists():
        return []
    return [dict(t, id=str(t["id"])) for t in (yaml.safe_load(CURATED.read_text(encoding="utf-8")) or {}).get("tracks") or []]


def trending(ig) -> list[dict]:
    """What is trending now (first pages of GET /ig_audio without a query)."""
    out, after = [], None
    for _ in range(TRENDING_PAGES):
        params = {"ig_user_id": ig.user_id, "audio_type": "music"}
        if after:
            params["after"] = after
        page = ig.get("ig_audio", **params)
        out += page.get("audio") or []
        after = ((page.get("paging") or {}).get("cursors") or {}).get("after")
        if not after:
            break
    return out


def library(ig, query: str) -> list[dict]:
    return ig.get("ig_audio", ig_user_id=ig.user_id, audio_type="music", search_query=query).get("audio") or []


def moods_for(item: dict) -> list[str]:
    """The post's moods: set by hand (`music_moods`), else from the format and the title."""
    if item.get("music_moods"):
        return list(item["music_moods"])
    title = " ".join(str(s.get("title") or "") for s in (item.get("slides") or [])[:2]).lower()
    moods = {"then_vs_now": ["nostalgic"], "this_not_that": ["calm", "home"]}.get(item.get("format"), ["cozy"])
    for words, mood in ((r"autumn|fall|harvest|pumpkin", "autumn"), (r"winter|nordic|snow|hygge|christmas", "winter"),
                        (r"morning|breakfast", "morning"), (r"cabin|forest|woods|mountain", "cabin"),
                        (r"kitchen|home|pantry|bedroom", "home"), (r"then|used to|grandm|old", "nostalgic")):
        if re.search(words, title):
            moods.append(mood)
    return list(dict.fromkeys(moods))


def recently_used(exclude: str | None = None) -> list[str]:
    """Songs of the last RECENT published posts and of every post waiting in the queue."""
    published = sorted(content.items("published"), key=lambda i: i.get("published_at") or "", reverse=True)
    waiting = [i for state in ("approved", "drafts") for i in content.items(state)]
    return [str((i.get("music") or {}).get("audio_id")) for i in published[:RECENT] + waiting
            if (i.get("music") or {}).get("audio_id") and i["id"] != exclude]


def _in_season(track: dict, today: date) -> bool:
    months = track.get("months")
    if months:
        return today.month in months
    return not SEASONAL.search(track.get("title") or "") or today.month == 12


def pick(ig, item: dict, today: date | None = None, taken: list[str] | None = None) -> dict | None:
    """The song for this post, with alternatives (Instagram may refuse one), or None."""
    today = today or date.today()
    moods = moods_for(item)
    taken = set(recently_used(item["id"]) if taken is None else taken)
    hot = {str(t["audio_id"]): t for t in trending(ig)}
    tracks = {t["id"]: t for t in curated()}
    for aid, t in hot.items():   # new trending songs that sound like the niche
        title = t.get("title") or ""
        if aid not in tracks and NICHE.search(title) and not BLOCKED.search(title):
            tracks[aid] = {"id": aid, "title": t.get("title"), "artist": t.get("display_artist"),
                           "popular": True, "moods": ["cozy", "calm"]}

    def score(t: dict) -> float:
        tie = int(hashlib.sha1(f"{item['id']}{t['id']}".encode()).hexdigest()[:6], 16) / 0xFFFFFF
        return (3.0 * (t["id"] in hot) + 1.0 * bool(t.get("popular")) + 2.0 * len(set(moods) & set(t.get("moods") or []))
                - 6.0 * (t["id"] in taken) + 0.5 * tie)

    ranked = sorted((t for t in tracks.values() if _in_season(t, today)), key=score, reverse=True)
    if not ranked or score(ranked[0]) < 2:
        for mood in moods:
            for t in library(ig, LIBRARY_QUERIES.get(mood, mood))[:3]:
                aid = str(t["audio_id"])
                if aid not in taken and aid not in tracks:
                    ranked.append({"id": aid, "title": t.get("title"), "artist": t.get("display_artist"),
                                   "popular": False, "moods": [mood]})
    if not ranked:
        return None
    def entry(t: dict) -> dict:
        return {"audio_id": t["id"], "title": t.get("title"), "artist": t.get("artist"), "trending": t["id"] in hot}

    return {**entry(ranked[0]), "moods": moods, "alternatives": [entry(t) for t in ranked[1:4]]}


def label(music: dict | None) -> str | None:
    """"Title – Artist" for people (KLAPKA, logs)."""
    if not music:
        return None
    return " – ".join(filter(None, [music.get("title"), music.get("artist")]))
