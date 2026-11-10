"""Command line entry point: `python -m igbot <command>`."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from . import content
from .config import BUILD_DIR, load_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="igbot", description="Automatizace Instagram účtu přes oficiální API")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="vygeneruj koncepty postů a stories pomocí Claude")
    g.add_argument("--days", type=int, default=7)
    g.add_argument("--start", type=date.fromisoformat, default=date.today() + timedelta(days=1))

    a = sub.add_parser("approve", help="schval koncepty (přesun drafts → approved)")
    a.add_argument("ids", nargs="*", help="ID položek; bez ID schválí všechny bez chyb")

    at = sub.add_parser("attach", help="připoj natočené video/fotku ke konceptu (nahraje ho do úložiště)")
    at.add_argument("id", help="ID položky, např. 2026-11-02-feed-1")
    at.add_argument("files", nargs="+", type=Path, help="video (a volitelně obrázek obálky)")
    at.add_argument("--ai", action="store_true", help="médium je generované AI (přidá štítek AI info)")

    sub.add_parser("preview", help="vyrenderuj grafiku všech konceptů a schválených položek do build/preview")
    co = sub.add_parser("collage", help="vyrenderuj moodboard koláž z plánu (JSON) do build/collage")
    co.add_argument("plan", type=Path, help="plán postu, např. assets/examples/autumn-living.json")
    co.add_argument("--seed", type=int, default=0, help="jiné číslo = jiné rozložení předmětů")
    sub.add_parser("check", help="zkontroluj frontu (validace, kolize termínů)")
    sub.add_parser("plan", help="ukaž dnešní plán publikace (zásoba, okna, co půjde další)")
    pr = sub.add_parser("prepare", help="vyrenderuj slidy konceptů a schválených položek do media/ "
                                        "(publikace z GitHubu je pak jen stáhne)")
    pr.add_argument("ids", nargs="*", help="ID položek; bez ID všechny, které ještě nemají média")
    pr.add_argument("--force", action="store_true", help="vyrenderuj znovu i hotové položky")
    pr.add_argument("--seed", type=int, default=0, help="jiné číslo = jiné rozložení předmětů")
    pr.add_argument("--music", action="store_true", help="vyber hudbu k Reelu znovu (podle dnešních trendů)")

    p = sub.add_parser("publish", help="publikuj schválené položky, kterým nastal čas")
    p.add_argument("--dry-run", action="store_true", help="nic neposílej, jen ukaž, co by se stalo")

    sub.add_parser("insights", help="stáhni statistiky postů a účtu do data/")
    sub.add_parser("discover", help="analyzuj podobné účty a rozšiř jejich seznam")

    an = sub.add_parser("analyze", help="hloubková analýza IG účtu (API nebo screenshoty) → report")
    an.add_argument("username", help="uživatelské jméno bez @")
    an.add_argument("--limit", type=int, default=60, help="kolik posledních postů projít (API)")
    an.add_argument("--images", type=Path, help="složka se screenshoty místo API")
    an.add_argument("--set-niche", action="store_true",
                    help="ulož výsledek jako profil naší niky (u prvního účtu v competitors.seeds automaticky)")
    ins = sub.add_parser("inspect", help="rozbor odkazu z Instagramu, TikToku nebo YouTube")
    ins.add_argument("urls", nargs="*", help="jeden nebo více odkazů")
    ins.add_argument("--file", type=Path, help="soubor s odkazy, jeden na řádek")
    ins.add_argument("--account", help="autor instagramového příspěvku, pokud není v odkazu")
    ins.add_argument("--image", type=Path, action="append", default=[],
                     help="screenshot k odkazu (lze opakovat); doplní čísla a obsah, které API nedá")
    ins.add_argument("--note", help="vlastní poznámka k odkazu (co se ve videu děje, čísla…)")
    ins.add_argument("--raw", action="store_true", help="jen vypiš stažená data, bez rozboru Claudem")

    ks = sub.add_parser("klapka-sync", help="pošli frontu do KLAPKY (Airtable) a proveď rozhodnutí z ní")
    ks.add_argument("--dry-run", action="store_true", help="jen ukaž, co by se poslalo (bez volání API)")

    sub.add_parser("quota", help="ukaž využití denního limitu publikací")
    sub.add_parser("refresh-token", help="prodluž long-lived token (Instagram Login)")

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "generate":
        from .generate import generate
        items = generate(cfg, args.start, args.days)
        print(f"Vytvořeno {len(items)} položek.")
        from . import klapka
        klapka.after("generate")
    elif args.cmd == "approve":
        for item in content.items("drafts"):
            if args.ids and item["id"] not in args.ids:
                continue
            problems = content.validate(item)
            if problems:
                item["problems"] = problems
                content.save(item, "drafts")
                print(f"přeskočeno {item['id']}: {'; '.join(problems)}")
                continue
            item.pop("problems", None)
            content.save(item, "approved")
            print(f"schváleno {item['id']}")
        from . import klapka
        klapka.after("approve")
    elif args.cmd == "attach":
        attach_media(args)
    elif args.cmd == "preview":
        from .render import Theme, render_item
        theme = Theme.from_config(cfg)
        out = BUILD_DIR / "preview"
        for state in ("drafts", "approved"):
            for item in content.items(state):
                for path in render_item(item, out, theme):
                    print(path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path)
    elif args.cmd == "collage":
        render_collage(cfg, args)
    elif args.cmd == "prepare":
        prepare_media(cfg, args)
    elif args.cmd == "check":
        seen, bad = {}, 0
        for state in ("drafts", "approved"):
            for item in content.items(state):
                problems = content.validate(item)
                if state == "drafts" and content.MISSING_VIDEO in problems:
                    # A reel script waiting to be filmed is normal, not a broken queue.
                    problems.remove(content.MISSING_VIDEO)
                    print(f"čeká na natočení: {item['id']}")
                if item["kind"] in content.TIMED and item.get("date") and item.get("time"):
                    slot = (item["date"], item["time"], item["kind"] == "story")
                    if slot in seen:
                        problems.append(f"stejný termín jako {seen[slot]}")
                    seen[slot] = item["id"]
                if problems:
                    bad += 1
                    print(f"{state}/{item['id']}: {'; '.join(problems)}")
        print("Fronta je v pořádku." if not bad else f"{bad} položek s problémy.")
        raise SystemExit(1 if bad else 0)
    elif args.cmd == "plan":
        show_plan(cfg)
    elif args.cmd == "publish":
        from .publish import publish_due
        n = publish_due(cfg, dry_run=args.dry_run)
        print(f"Publikováno: {n}")
        if not args.dry_run:
            from . import klapka
            klapka.after("publish", published=n)
    elif args.cmd == "klapka-sync":
        from . import klapka
        print(f"KLAPKA: {klapka.describe(klapka.sync('cli', dry_run=args.dry_run))}")
    elif args.cmd == "insights":
        from .insights import collect
        from .instagram import Instagram
        print(f"Uloženo {collect(Instagram.from_env())} záznamů.")
    elif args.cmd == "discover":
        from .discover import run
        from .instagram import Instagram
        result = run(Instagram.from_env(), cfg["competitors"]["seeds"], cfg["account"].get("handle", ""))
        print(result)
    elif args.cmd == "analyze":
        from .analyze import run
        ig = None
        if not args.images:
            from .instagram import Instagram
            ig = Instagram.from_env()
        username = args.username.lstrip("@")
        seeds = (cfg.get("competitors") or {}).get("seeds") or []
        set_niche = args.set_niche or (bool(seeds) and username.lower() == seeds[0].lower())
        print(f"Report: {run(cfg, username, args.limit, args.images, ig, update_niche_profile=set_niche)}")
    elif args.cmd == "inspect":
        inspect_links(cfg, args)
    elif args.cmd == "quota":
        from .instagram import Instagram
        print(Instagram.from_env().publishing_quota())
    elif args.cmd == "refresh-token":
        from .instagram import Instagram
        data = Instagram.from_env().refresh_instagram_login_token()
        # Never print the token itself; the workflow stores it as a secret.
        Path(BUILD_DIR).mkdir(exist_ok=True)
        (BUILD_DIR / "new_token.txt").write_text(data["access_token"], encoding="utf-8")
        print(f"Token prodloužen, platí {int(data.get('expires_in', 0)) // 86400} dní.")


def show_plan(cfg: dict) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from . import scheduler
    tz = cfg["account"]["timezone"]
    now = datetime.now(ZoneInfo(tz))
    p = scheduler.plan(now, tz)
    print(f"Teď {now:%a %H:%M} ({tz}). Dnes {p['today']}/{p['per_day']} postů, v zásobě {len(p['pool'])}.")
    print("Okna dnes:", ", ".join(f"{s:%H:%M}" for s in p["slots"]) or "žádná")
    print("Teď publikovat:", "ano → " + p["pick"]["id"] if p["due"] else f"ne ({p['reason']})")
    prague = ZoneInfo("Europe/Prague")
    days = scheduler.day_plan(now, tz)
    for day in days["days"]:
        label = "Dnes" if day["date"] == f"{now:%Y-%m-%d}" else "Zítra"
        print(f"{label} ({day['date']}), {day['per_day']} za den:")
        for s in day["slots"] or [{"at": None}]:
            if s["at"] is None:
                print("  nic (zásoba schválených je prázdná)")
                continue
            at = datetime.fromisoformat(s["at"])
            mark = "✓" if s["status"] == "published" else "·"
            why = f"  ({s['why']})" if s.get("why") else ""
            print(f"  {mark} {at:%H:%M} NY / {at.astimezone(prague):%H:%M} Praha  {s['post_id']} "
                  f"[{s.get('format')}] {s['title']}{why}")
    print(f"V zásobě po těchto dnech zbude: {days['left_after']}")


def render_collage(cfg: dict, args) -> None:
    """Render a moodboard plan file, with a contact sheet and the photos' licence trail."""
    import json

    from . import collage, photos

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    out = BUILD_DIR / "collage" / (plan.get("id") or args.plan.stem)
    paths, credits = collage.render_post(plan, out, cfg.get("account", {}).get("handle", ""),
                                         collage.Style.from_brand(cfg.get("brand")), seed=args.seed)
    photos.save_credits(credits, out / "credits.json")
    sheet = collage.contact_sheet(paths, out / "overview.jpg")
    print(f"hotovo: {sheet.relative_to(Path.cwd()) if sheet.is_relative_to(Path.cwd()) else sheet}")


def prepare_media(cfg: dict, args) -> None:
    """Render drafts and approved items into media/ and point `media` at their public URLs.

    With `feed.publish_as: reel` every carousel also gets its Reel: a video of
    the slides swiping by (media/<id>.mp4 + cover) and a popular song picked
    for it (igbot/music.py), which Instagram adds when it publishes.

    The files only become reachable after they are pushed, so commit and push
    media/ and content/ before `klapka-sync` (KLAPKA shows every slide) and
    before the publishing slot. Each URL carries a hash of the file (?v=...):
    a re-render keeps the file name, and without it KLAPKA, Airtable and the
    raw.githubusercontent cache would keep showing the old slide."""
    import hashlib

    from . import collage, music, reel
    from .config import ROOT
    from .render import Theme, render_item

    base = (cfg.get("media") or {}).get("base_url", "").rstrip("/")
    if not base:
        raise SystemExit("Chybí media.base_url v config/account.yaml.")
    theme = Theme.from_config(cfg)
    as_reel = (cfg.get("feed") or {}).get("publish_as") == "reel"
    out = ROOT / "media"
    ig = None
    done = 0

    def url(path: Path) -> str:
        return f"{base}/media/{path.name}?v={hashlib.sha1(path.read_bytes()).hexdigest()[:8]}"

    for state in ("drafts", "approved"):
        for item in content.items(state):
            if args.ids and item["id"] not in args.ids:
                continue
            if item["kind"] == "reel" or not item.get("slides"):
                continue
            changed = False
            if not item.get("media") or (args.force and item.get("media_from_slides")):
                for old in out.glob(f"{item['id']}-*.jpg"):
                    old.unlink()  # a re-render may have fewer slides
                if collage.is_collage(item) and item["kind"] != "story":
                    paths = collage.render_item(item, out, cfg.get("brand"), theme.handle, seed=args.seed)
                else:
                    paths = render_item(item, out, theme)
                item["media"] = [url(p) for p in paths]
                item["media_from_slides"] = True
                item.pop("reel", None)  # new slides, new video
                sheet = collage.contact_sheet(paths, BUILD_DIR / "prepare" / f"{item['id']}.jpg")
                print(f"{item['id']}: {len(paths)} slidů, náhled {sheet}")
                changed = True
            if as_reel and item["kind"] == "carousel" and item.get("media_from_slides"):
                slides = [out / str(m).split("?")[0].rsplit("/", 1)[-1] for m in item["media"]]
                if not item.get("reel") and all(p.exists() for p in slides):
                    video = reel.render(slides, out / f"{item['id']}.mp4", cfg.get("brand") or {})
                    cover = reel.cover(slides, out / f"{item['id']}-cover.jpg", cfg.get("brand") or {})
                    item["reel"] = {"video": url(video), "cover": url(cover)}
                    print(f"{item['id']}: Reel {reel.duration(len(slides)):.0f} s, {video.stat().st_size / 1e6:.1f} MB")
                    changed = True
            if item["kind"] == "carousel" and item.get("media_from_slides") and (not item.get("music") or getattr(args, "music", False)):
                # The song to add in the app after publishing (the API can't put music on a
                # carousel); picked again from that day's trends when the post goes out.
                try:
                    if ig is None:
                        from .instagram import Instagram
                        ig = Instagram.from_env()
                    item["music"] = music.pick(ig, item)
                    print(f"{item['id']}: hudba {music.label(item['music'])}"
                          f"{' (v trendech)' if item['music'] and item['music']['trending'] else ''}")
                    changed = True
                except Exception as exc:  # publishing picks one later if this fails
                    print(f"{item['id']}: hudba nevybrána ({exc})")
            if not changed:
                continue
            problems = content.validate(item)
            if problems:
                item["problems"] = problems
            else:
                item.pop("problems", None)
            content.save(item, state)
            done += 1
    print(f"Připraveno: {done}. Teď commit + push složek media/ a content/, pak `klapka-sync`.")


def attach_media(args) -> None:
    """Upload the filmed reel (or photo) to public storage and link it to the item.

    Videos are too big for git, so the item stores the public URL; publishing
    then works the same from GitHub Actions as from this computer."""
    from . import hosting
    from .config import env

    if env("MEDIA_BACKEND", "s3") == "github":
        raise SystemExit("attach potřebuje MEDIA_BACKEND=s3 (videa do gitu nepatří).")
    found = [i for state in ("drafts", "approved", "failed") for i in content.items(state) if i["id"] == args.id]
    if not found:
        raise SystemExit(f"Položka {args.id} není v drafts/approved/failed.")
    item = found[0]
    missing = [str(f) for f in args.files if not f.is_file()]
    if missing:
        raise SystemExit(f"Soubor neexistuje: {', '.join(missing)}")
    item["media"] = hosting.upload([f.resolve() for f in args.files], prefix=item["id"])
    item["ai_media"] = bool(args.ai)  # attach replaces all media, so the flag follows the new files
    item.pop("error", None)
    problems = content.validate(item)
    if problems:
        item["problems"] = problems
        print(f"Médium připojeno, ale zbývá: {'; '.join(problems)}")
    else:
        item.pop("problems", None)
    state = "approved" if Path(item["_path"]).parent.name == "approved" and not problems else "drafts"
    content.save(item, state)
    print(f"{item['id']}: {len(item['media'])} médií → content/{state}/ "
          f"({'čeká na schválení' if state == 'drafts' else 'naplánováno'})")


def inspect_links(cfg: dict, args) -> None:
    import json

    from . import links

    urls = [links.clean_url(u) for u in args.urls if links.clean_url(u)]
    if args.file:
        for line in args.file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls and not args.image:
        raise SystemExit("Zadej aspoň jeden odkaz nebo screenshot (--image).")
    if len(urls) > 1 and (args.image or args.note):
        raise SystemExit("Screenshoty a poznámku lze přiložit jen k jednomu odkazu.")

    ig = None
    if any(links.classify(u)[0].startswith("instagram") for u in urls):
        from .instagram import Instagram
        try:
            ig = Instagram.from_env()
        except SystemExit:
            # Only the Instagram links fail (links.fetch raises per link without ig).
            print("Instagram API není připojené (chybí IG_USER_ID / IG_ACCESS_TOKEN).")

    failed = 0
    for url in urls or [""]:
        platform, details = links.classify(url) if url else ("screenshot", {})
        try:
            if platform == "instagram_profile" and not args.image:
                if args.raw:
                    print(json.dumps({"platform": platform, **details}, ensure_ascii=False))
                    continue
                if ig is None:
                    raise links.FetchError("Analýza profilu potřebuje připojený Instagram účet")
                from .analyze import run
                print(f"Profil @{details['username']} → plná analýza účtu")
                print(f"Report: {run(cfg, details['username'], 30, None, ig, update_niche_profile=False)}")
                continue
            try:
                info = links.fetch(url, ig=ig, account=args.account) if url else links.screenshot_only("", "")
            except Exception as exc:
                if not args.image and not args.note:
                    raise
                info = links.screenshot_only(url, str(exc))
            if args.raw:
                print(json.dumps(info, ensure_ascii=False, indent=1))
                continue
            analysis = links.analyze(info, cfg, images=args.image, note=args.note)
            print(links.render(info, analysis))
            print(f"Uloženo: {links.save(info, analysis)}\n")
        except (Exception, SystemExit) as exc:  # one bad link shouldn't stop the batch
            failed += 1
            print(f"CHYBA {url or '(screenshot)'}: {exc}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
