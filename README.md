# organic

Automatizace Instagram účtu přes **oficiální Instagram API** (žádné přihlašování
heslem, žádné boty v aplikaci). Postup: analýza účtů v nice → vlastní obsah
generovaný Claudem → schválení → automatická publikace → statistiky → další kolo.

## Jak bot „prochází“ Instagram

| Způsob | Kdy | Co umí |
|---|---|---|
| `python -m igbot analyze <účet>` | po připojení účtu (viz [docs/NASTAVENI.md](docs/NASTAVENI.md)) | stáhne posledních N postů libovolného Business/Creator účtu: popisky, lajky, komentáře, zhlédnutí, obrázky. Claude každý post vyhodnotí (téma, formát, háček, vizuál, proč funguje) a napíše report do `reports/<účet>/` |
| `python -m igbot analyze <účet> --images složka/` | hned, bez API | stejná analýza ze screenshotů (mřížka profilu, posty, reels) |
| `python -m igbot discover` | každý týden automaticky | sleduje podobné účty a z jejich zmínek @ přidává další, takže okruh zdrojů postupně roste |

Výstup analýzy (`data/niche_profile.yaml`) automaticky přebírá generátor obsahu.

## Příkazy

```bash
python -m igbot analyze organic__101_ --limit 100   # analýza účtu → report
python -m igbot discover                            # podobné účty
python -m igbot generate --days 7                   # koncepty na týden
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
