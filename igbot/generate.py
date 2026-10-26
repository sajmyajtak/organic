"""Generate original post and story drafts with Claude.

The model gets the niche definition from config/account.yaml plus two
feedback signals: what performed best on our own account (data/insights.csv)
and which topics/formats are working for similar accounts
(data/inspiration.json, built by `discover`). It is told to use those only as
signals for topics and formats and to write everything from scratch.
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from typing import Literal

import anthropic
import yaml
from pydantic import BaseModel

from . import content
from .links import recent_inspections
from .config import DATA_DIR

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class Slide(BaseModel):
    title: str
    body: str


class FeedPost(BaseModel):
    date: str
    pillar: str
    kind: Literal["carousel", "image"]
    slides: list[Slide]
    caption: str
    hashtags: list[str]
    alt_text: str
    sponsored: bool
    inspired_by: str


class ReelScript(BaseModel):
    date: str
    pillar: str
    hook_spoken: str
    hook_on_screen: str
    shots: list[str]
    voiceover: str
    on_screen_text: list[str]
    duration_s: int
    filming_tips: str
    caption: str
    hashtags: list[str]
    sponsored: bool
    inspired_by: str


class Story(BaseModel):
    date: str
    slot: int
    purpose: Literal["engagement", "traffic", "teaser", "behind_the_scenes", "question"]
    title: str
    body: str
    sticker_idea: str


class Plan(BaseModel):
    feed: list[FeedPost]
    reels: list[ReelScript]
    stories: list[Story]


SYSTEM = """You are the content strategist and copywriter of an Instagram account.
Write every post in the language given in `language`. Write only original content:
never reuse text, graphics or specific phrasing from other accounts. Data about
other accounts is only a signal of which topics and formats people care about;
cover the topic in your own words, with your own structure and your own added
value. Since April 2026 Instagram stops recommending accounts that mostly post
other people's photos, carousels or reels, so originality is a condition of reach.

What Instagram's published ranking explainers say it measures: time spent on a
post, swiping through the whole carousel, saves, likes per reach and shares by DM
(the share model favours informative posts: how-tos, comparisons, reviews). So:
- CAROUSELS are the main format: 6-10 slides. Slide 1 is the hook (a concrete
  benefit or curiosity gap, max ~8 words). Slide 2 must also work as an opener,
  because Instagram shows it first to some people. One idea per slide, short
  sentences, no filler. The last slide sums up and gives one clear call to action
  (save / send to a friend / comment). Cite a source for factual claims.
- CAPTION: first line is a hook with searchable keywords, the end is a question
  or a call to action. At most 5 specific hashtags (Instagram allows no more),
  no generic ones (#love, #instagood).
- STORIES are seen by followers only: short, personal, ask for DM replies or tease
  the new post. Stickers (poll, link, question) cannot be added through the API,
  so put a sticker idea in sticker_idea (added by hand) and write the text so it
  works without it.
- REELS only if the task asks for them: hook in the first 2 seconds, 7-45 s,
  one idea, own voice, no watermarks, text never covering most of the frame.

Legal rules (the creator is an EU business; audiences in the US/UK/EU), binding:
- No disease or cure claims (treats, cures, prevents, "detox" against illness),
  no fear-mongering. Food health claims only in EU-authorised wording (Regulation
  1924/2006); if unsure, leave the claim out. Never imply that a non-medicinal
  product improves health or that skipping it harms health.
- Food supplements are always called "food supplement".
- Do not promote raw milk.
- Product recommendations and affiliate links: sponsored=true and the caption's
  first line starts with "Ad" (or "#ad" / "Paid partnership").
- Alt text describes the graphic for blind users."""


def _recent_captions(limit: int = 30) -> list[str]:
    done = content.items("published")[-limit:]
    titles = [(i.get("slides") or [{}])[0].get("title", "") or (i.get("script") or {}).get("hook_on_screen", "")
              for i in done if i["kind"] != "story"]
    return [t for t in titles if t]


def _top_performers(limit: int = 8) -> list[dict]:
    path = DATA_DIR / "insights.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    latest = {}
    for row in rows:  # keep the newest snapshot of each post
        latest[row["media_id"]] = row

    def score(r):
        reach = float(r.get("reach") or 0) or 1.0
        return (float(r.get("saved") or 0) + 2 * float(r.get("shares") or 0)) / reach

    best = sorted(latest.values(), key=score, reverse=True)[:limit]
    return [{"title": r.get("title"), "kind": r.get("kind"), "reach": r.get("reach"),
             "saved": r.get("saved"), "shares": r.get("shares")} for r in best]


def _inspiration() -> list[dict]:
    path = DATA_DIR / "inspiration.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("top_posts", [])[:25]


def _niche_profile() -> dict | None:
    """Niche profile proposed by `analyze` from real posts of the source account."""
    path = DATA_DIR / "niche_profile.yaml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def build_prompt(cfg: dict, start: date, days: int) -> str:
    sched = cfg["schedule"]
    mix = sched.get("weekly_mix", {"carousel": 7})
    dates = [(start + timedelta(days=d)).isoformat() for d in range(days)]
    reels = max(0, round(mix.get("reel", 0) * days / 7))
    carousels = max(0, round(mix.get("carousel", 0) * days / 7))
    return json.dumps({
        "task": (f"Plan content for {dates[0]} to {dates[-1]}: {carousels} carousels or single "
                 f"images (field feed) and {reels} reel scripts (field reels), at most one feed post "
                 f"per day, spread evenly. Every day {sched['stories_per_day']} stories "
                 f"(slot 1..{sched['stories_per_day']}). Rotate pillars by their shares. "
                 "Carousel 6-10 slides, single image 1 slide, story 1 slide."),
        "language": cfg.get("account", {}).get("language", "en"),
        "days": dates,
        "niche": cfg["niche"],
        "niche_from_source_account_analysis": _niche_profile(),
        "monetization": cfg.get("monetization", {}),
        "already_published_do_not_repeat": _recent_captions(),
        "our_best_posts": _top_performers(),
        "what_works_for_similar_accounts_signal_only": _inspiration(),
        "inspected_links_signal_only": recent_inspections(),
    }, ensure_ascii=False, indent=1)


def generate(cfg: dict, start: date, days: int) -> list[dict]:
    gen = cfg.get("generation", {})
    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=gen.get("model", "claude-opus-5-5"),
        max_tokens=32000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(cfg, start, days)}],
        output_config={"effort": gen.get("effort", "medium")},
        output_format=Plan,
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model odmítl požadavek: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Odpověď se nevešla do max_tokens, zkus menší počet dní.")
    plan: Plan = response.parsed_output

    sched = cfg["schedule"]
    lang = cfg.get("account", {}).get("language", "en")
    state = "approved" if gen.get("auto_approve") else "drafts"
    created = []
    taken: set[str] = set()

    def new_id(day: str, kind: str) -> str:
        """Next free id for the day; never reuses one already in any queue folder,
        so re-running generate can't overwrite drafts with attached videos."""
        n = 1
        while f"{day}-{kind}-{n}" in taken or content.exists(f"{day}-{kind}-{n}"):
            n += 1
        taken.add(f"{day}-{kind}-{n}")
        return f"{day}-{kind}-{n}"

    for post in plan.feed:
        item = {
            "id": new_id(post.date, "feed"),
            "date": post.date,
            "time": sched["feed_time"],
            "kind": post.kind,
            "pillar": post.pillar,
            "slides": [s.model_dump() for s in post.slides],
            "caption": post.caption,
            "hashtags": post.hashtags,
            "alt_text": post.alt_text,
            "sponsored": post.sponsored,
            "inspired_by": post.inspired_by,
            "lang": lang,
            "ai_generated": True,
        }
        created.append(item)
    for reel in plan.reels:
        created.append({
            "id": new_id(reel.date, "feed"),
            "date": reel.date,
            "time": sched["feed_time"],
            "kind": "reel",
            "pillar": reel.pillar,
            "script": {
                "hook_spoken": reel.hook_spoken, "hook_on_screen": reel.hook_on_screen,
                "shots": reel.shots, "voiceover": reel.voiceover,
                "on_screen_text": reel.on_screen_text, "duration_s": reel.duration_s,
                "filming_tips": reel.filming_tips,
            },
            "media": [],
            "caption": reel.caption,
            "hashtags": reel.hashtags,
            "sponsored": reel.sponsored,
            "inspired_by": reel.inspired_by,
            "lang": lang,
            "ai_generated": True,
        })
    for story in plan.stories:
        slot = max(1, min(story.slot, len(sched["story_times"])))
        created.append({
            "id": new_id(story.date, "story"),
            "date": story.date,
            "time": sched["story_times"][slot - 1],
            "kind": "story",
            "purpose": story.purpose,
            "slides": [{"title": story.title, "body": story.body}],
            "sticker_idea": story.sticker_idea,
            "lang": lang,
            "ai_generated": True,
        })
    for item in created:
        problems = content.validate(item)
        if problems:
            item["problems"] = problems
        content.save(item, "drafts" if problems else state)
    return created
