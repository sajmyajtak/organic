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
            if item.get("problems") and not args.ids:
                print(f"přeskočeno {item['id']}: {item['problems']}")
                continue
            item.pop("problems", None)
            content.save(item, "approved")
            print(f"schváleno {item['id']}")
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
        print(f"Report: {run(cfg, args.username.lstrip('@'), args.limit, args.images, ig)}")
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


def inspect_links(cfg: dict, args) -> None:
    import json

    from . import links

    urls = list(args.urls)
    if args.file:
        urls += [u.strip() for u in args.file.read_text(encoding="utf-8").splitlines()
                 if u.strip() and not u.startswith("#")]
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
            if not args.image:
                raise
            print("Instagram API není připojené, rozbor jen ze screenshotu.")

    failed = 0
    for url in urls or [""]:
        platform, details = links.classify(url)
        try:
            if platform == "instagram_profile" and not args.image:
                from .analyze import run
                print(f"Profil @{details['username']} → plná analýza účtu")
                print(f"Report: {run(cfg, details['username'], 30, None, ig)}")
                continue
            try:
                info = links.fetch(url, ig=ig, account=args.account) if url else links.screenshot_only("", "")
            except (LookupError, SystemExit) as exc:
                if not args.image:
                    raise
                info = links.screenshot_only(url, str(exc))
            if args.raw:
                print(json.dumps(info, ensure_ascii=False, indent=1))
                continue
            analysis = links.analyze(info, cfg, images=args.image, note=args.note)
            text = links.render(info, analysis)
            print(text)
            print(f"Uloženo: {links.save(info, analysis, text)}\n")
        except Exception as exc:  # one bad link shouldn't stop the batch
            failed += 1
            print(f"CHYBA {url}: {exc}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
