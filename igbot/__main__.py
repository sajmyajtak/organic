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
    sub.add_parser("check", help="zkontroluj frontu (validace, kolize termínů)")

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

    sub.add_parser("quota", help="ukaž využití denního limitu publikací")
    sub.add_parser("refresh-token", help="prodluž long-lived token (Instagram Login)")

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "generate":
        from .generate import generate
        items = generate(cfg, args.start, args.days)
        print(f"Vytvořeno {len(items)} položek.")
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
    elif args.cmd == "check":
        seen, bad = {}, 0
        for state in ("drafts", "approved"):
            for item in content.items(state):
                problems = content.validate(item)
                slot = (item["date"], item["time"], item["kind"] == "story")
                if slot in seen:
                    problems.append(f"stejný termín jako {seen[slot]}")
                seen[slot] = item["id"]
                if problems:
                    bad += 1
                    print(f"{state}/{item['id']}: {'; '.join(problems)}")
        print("Fronta je v pořádku." if not bad else f"{bad} položek s problémy.")
        raise SystemExit(1 if bad else 0)
    elif args.cmd == "publish":
        from .publish import publish_due
        n = publish_due(cfg, dry_run=args.dry_run)
        print(f"Publikováno: {n}")
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


def attach_media(args) -> None:
    """Upload the filmed reel (or photo) to public storage and link it to the item.

    Videos are too big for git, so the item stores the public URL; publishing
    then works the same from GitHub Actions as from this computer."""
    from . import hosting

    found = [i for state in ("drafts", "approved", "failed") for i in content.items(state) if i["id"] == args.id]
    if not found:
        raise SystemExit(f"Položka {args.id} není v drafts/approved/failed.")
    item = found[0]
    missing = [str(f) for f in args.files if not f.is_file()]
    if missing:
        raise SystemExit(f"Soubor neexistuje: {', '.join(missing)}")
    item["media"] = hosting.upload(list(args.files), prefix=item["id"])
    if args.ai:
        item["ai_media"] = True
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
