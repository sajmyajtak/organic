# organic

Automatizace Instagram účtu přes **oficiální Instagram API** (žádné přihlašování
heslem, žádné boty v aplikaci). Postup: analýza účtů v nice → vlastní obsah
generovaný Claudem → schválení → automatická publikace → statistiky → další kolo.

- **Strategie, monetizace a 90denní plán:** [docs/PLAN.md](docs/PLAN.md)
- **Připojení účtu a klíčů:** [docs/NASTAVENI.md](docs/NASTAVENI.md)

## Jak bot „prochází“ Instagram

| Způsob | Kdy | Co umí |
|---|---|---|
| `python -m igbot analyze <účet>` | po připojení účtu (viz [docs/NASTAVENI.md](docs/NASTAVENI.md)) | stáhne posledních N postů libovolného Business/Creator účtu: popisky, lajky, komentáře, zhlédnutí, obrázky. Claude každý post vyhodnotí (téma, formát, háček, vizuál, proč funguje) a napíše report do `reports/<účet>/` |
| `python -m igbot analyze <účet> --images složka/` | hned, bez API | stejná analýza ze screenshotů (mřížka profilu, posty, reels) |
| `python -m igbot inspect <odkaz>` | hned | rozbor jednoho odkazu z Instagramu, TikToku nebo YouTube: háček, formát, stavba, proč to funguje, nápady pro nás. Viz tabulka níže |
| `python -m igbot discover` | každý týden automaticky | sleduje podobné účty a z jejich zmínek @ přidává další, takže okruh zdrojů postupně roste |

Výstup analýzy (`data/niche_profile.yaml`) i rozbory odkazů (`data/inspected_links.jsonl`)
automaticky přebírá generátor obsahu.

### Co `inspect` z jednotlivých sítí dostane

Jen oficiální cesty, bez přihlašování a bez obcházení ochran proti botům:

| Síť | Zdroj | Data |
|---|---|---|
| YouTube | YouTube Data API (s `YOUTUBE_API_KEY`), jinak oEmbed | název, popis, tagy, délka, počty zhlédnutí, lajků a komentářů, náhled. Odběratele a texty komentářů nestahuje a čísla neukládá déle než 30 dní (pravidla YouTube API) |
| Instagram | Business Discovery (připojený účet) | popisek, lajky, komentáře, zhlédnutí, obrázek nebo náhled reelu, sledující autora. Autor musí být v odkazu (`instagram.com/<autor>/reel/…`) nebo v `--account`. Odkazy `instagram.com/share/…` nejdou |
| TikTok | oEmbed | jen ID videa a autor z odkazu. Čísla, popisek a obsah přilož screenshotem |

Ke každému odkazu jde přiložit screenshot a poznámku, třeba u TikToku nebo u videa,
kde je důležité, co se v něm děje:

```bash
python -m igbot inspect "https://www.tiktok.com/@autor/video/123" --image tiktok.png --note "1,2 mil. zhlédnutí, recept za 30 s"
python -m igbot inspect --file odkazy.txt        # víc odkazů najednou
```

## Příkazy

```bash
python -m igbot analyze organic__101_ --limit 100   # analýza účtu → report
python -m igbot inspect <odkaz> [--image shot.png]  # rozbor odkazu IG / TikTok / YouTube
python -m igbot discover                            # podobné účty
python -m igbot generate --days 7                   # koncepty na týden (karusely + stories, anglicky)
python -m igbot attach <id> foto.jpg                # připojit vlastní fotky/video k položce
python -m igbot preview                             # grafika do build/preview
python -m igbot approve                             # schválit koncepty
python -m igbot publish --dry-run                   # publikace (nanečisto)
python -m igbot insights                            # statistiky
```

Na GitHubu totéž běží samo (`.github/workflows/`): publikace každých 30 minut,
statistiky každou noc, týdenní plán v neděli jako pull request ke schválení,
analýza účtu ručně přes *Actions → Analýza účtu*.

## Struktura

- `igbot/`: kód (API klient, analýza, generátor, renderer grafiky, publikace)
- `config/account.yaml`: nastavení účtu, niky, rozvrhu a značky
- `content/{drafts,approved,published,failed}/`: fronta obsahu jako YAML soubory
- `reports/`: analýzy účtů
- `data/`: statistiky, sledované účty, profil niky
