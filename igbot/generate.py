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


SYSTEM = """Jsi obsahový stratég a copywriter českého Instagram účtu. Píšeš výhradně
původní obsah v češtině. Nikdy nepřebíráš texty, grafiku ani konkrétní formulace
jiných účtů: data o konkurenci ber jen jako signál, která témata a formáty lidi
zajímají, a téma pak zpracuj vlastními slovy, vlastní strukturou a s vlastní
přidanou hodnotou. Instagram od dubna 2026 přestává doporučovat účty, které
převážně přebírají cizí obsah, takže originalita je podmínka dosahu.

Co Instagram podle oficiálních popisů doporučování měří: dokoukání a čas strávený
u příspěvku, sdílení do zpráv (u lidí, kteří nás nesledují, nejdůležitější signál),
uložení, lajky na dosah, swipnutí celého karuselu. Návody, tipy a srovnání se sdílejí
nejvíc. Proto:
- REELS (hlavní motor růstu i jediný formát, který jde zpeněžit): háček v prvních
  2 s mluveným slovem i textem na obrazovce, délka 7–45 s, jedna myšlenka, vlastní
  hlas, záběry, které zvládne natočit jeden člověk s telefonem; text nesmí zakrývat
  většinu obrazu; žádné vodoznaky jiných aplikací; konec s výzvou poslat/uložit.
- KARUSELY: 5–10 slidů, slide 1 háček (max ~8 slov), slide 2 funguje i jako začátek
  (Instagram ho někomu ukáže první), každý slide jedna myšlenka, poslední slide
  shrnutí a jedna výzva. Uvádějte zdroje u faktických tvrzení.
- POPISEK: první řádek háček s klíčovými slovy (hledání), konec otázka nebo výzva.
  Maximálně 5 konkrétních hashtagů (Instagram víc nedovolí), žádné obecné (#love).
- STORIES vidí jen sledující: osobní, krátké, otázky na odpověď do DM, upoutávka na
  nový příspěvek. Nálepky (anketa, odkaz, otázka) přes API dát nejde, proto nápad na
  nálepku dej do sticker_idea (přidá se ručně) a samotný text formuluj tak, aby
  fungoval i bez ní.

Právní pravidla (Česko/EU), závazná:
- Žádná léčebná tvrzení (léčí, vyléčí, detox proti nemocem) a žádné strašení.
  Zdravotní tvrzení o potravinách jen v podobě schválené EU (nařízení 1924/2006);
  když si nejsi jistý, tvrzení vynech.
- U doplňků stravy vždy text „doplněk stravy“.
- Syrové mléko nepropaguj; pokud se téma objeví, uveď povinné upozornění
  „před použitím tepelně opracovat nebo pasterovat“.
- Produktová doporučení a affiliate: sponsored=true a popisek začíná slovem „Reklama“.
  Alt text popisuje obsah grafiky pro nevidomé."""


def _recent_captions(limit: int = 30) -> list[str]:
    done = content.items("published")[-limit:]
    return [(i.get("slides") or [{}])[0].get("title", "") for i in done if i["kind"] != "story"]


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
    niche = cfg["niche"]
    sched = cfg["schedule"]
    mix = sched.get("weekly_mix", {"reel": 4, "carousel": 3})
    dates = [(start + timedelta(days=d)).isoformat() for d in range(days)]
    reels = round(mix.get("reel", 0) * days / 7)
    return json.dumps({
        "ukol": (f"Naplánuj obsah na dny {dates[0]} až {dates[-1]}. Každý den právě jeden příspěvek "
                 f"do feedu: celkem {reels} scénářů reelů (pole reels) a {days - reels} karuselů nebo "
                 f"obrázků (pole feed), rozložených rovnoměrně. Každý den {sched['stories_per_day']} "
                 f"stories (slot 1..{sched['stories_per_day']}). Střídej pilíře podle podílů. "
                 "Karusel 5–10 slidů, single image 1 slide, story 1 slide."),
        "dny": dates,
        "nika": niche,
        "nika_podle_analyzy_zdrojoveho_uctu": _niche_profile(),
        "monetizace": cfg.get("monetization", {}),
        "uz_jsme_publikovali_neopakuj": _recent_captions(),
        "nase_nejlepsi_prispevky": _top_performers(),
        "co_funguje_u_podobnych_uctu_jen_jako_signal": _inspiration(),
        "rozebrane_odkazy_jen_jako_signal": recent_inspections(),
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
    state = "approved" if gen.get("auto_approve") else "drafts"
    created = []
    per_day: dict[str, int] = {}
    for post in plan.feed:
        per_day[post.date] = per_day.get(post.date, 0) + 1
        item = {
            "id": f"{post.date}-feed-{per_day[post.date]}",
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
            "ai_generated": True,
        }
        created.append(item)
    for reel in plan.reels:
        per_day[reel.date] = per_day.get(reel.date, 0) + 1
        created.append({
            "id": f"{reel.date}-feed-{per_day[reel.date]}",
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
            "ai_generated": True,
        })
    for story in plan.stories:
        slot = max(1, min(story.slot, len(sched["story_times"])))
        created.append({
            "id": f"{story.date}-story-{slot}",
            "date": story.date,
            "time": sched["story_times"][slot - 1],
            "kind": "story",
            "purpose": story.purpose,
            "slides": [{"title": story.title, "body": story.body}],
            "sticker_idea": story.sticker_idea,
            "ai_generated": True,
        })
    for item in created:
        problems = content.validate(item)
        if problems:
            item["problems"] = problems
        content.save(item, "drafts" if problems else state)
    return created
