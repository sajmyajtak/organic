# Kontext projektu pro Clauda

Shrnutí dosavadní práce (cloudová relace, 25. 10. – 7. 11. 2026), aby lokální
Claude Code mohl navázat. Uživatel komunikuje **česky**; obsah účtu je **anglicky**.

## Cíl

Automatizovaný Instagram účet **@naturizz** inspirovaný účtem **@organic__101_**:
denní karusely + stories generované Claudem, publikované přes oficiální API,
s cílem růstu a monetizace. Uživatel chce postupovat společně a schvalovat kroky.

## Rozhodnutí uživatele

- Jazyk obsahu: **angličtina** (publikum USA/UK/CA/AU, časy `America/New_York`).
- Formát: **jen karusely (a obrázky), žádné reels**, 1 post denně + 3 stories.
- Účet: dedikovaný účet tvůrce **@naturizz** (IG user id `17841466729247229`,
  propojený s FB stránkou `1464286703432419`). **Nikdy nepublikovat na
  @your_chloe_hart** (`17841448715162723`), je to jiný účet uživatele ve stejném tokenu.
- Design: koláž vystřižených fotek-„samolepek“ kolem velkého serifového nadpisu
  (technika @organic__101_, vlastní vzhled). **Vybraný styl „sticker“** (7. 11. 2026):
  kraftový papír, bílý obrys nálepek, tmavě hnědý nadpis uprostřed, rezavý akcent;
  barvy v `brand` v `config/account.yaml`. Varianta „journal“ zamítnuta.
- Uživatel nechce řešit štítky AI. Proto preferujeme **skutečné fotky**
  (Pexels/Openverse CC0/PD), kde štítek není potřeba. Fotorealistické AI obrázky
  by podle EU AI Act čl. 50 označení vyžadovaly; upozornit, nevnucovat.

## Pravidla, která držíme (důležité)

- **Jen oficiální Meta API.** Žádné přihlašování heslem, žádné scrapování
  Instagramu, žádné neoficiální knihovny (instagrapi, Selenium), žádné hromadné
  lajky/follow/DM. Business Discovery API je legitimní cesta k cizím účtům.
- **Nekopírovat obsah @organic__101_** (texty, fotky, layouty 1:1, název série
  „maxxing“). Od 30. 4. 2026 Instagram nedoporučuje účty s převážně
  neoriginálním obsahem (i fotky/karusely). Bereme techniku a témata, ne podobu.
- **Žádná zdravotní tvrzení** (vakcíny, opalovací krém, léky, léčení nemocí,
  syrové mléko). @organic__101_ je dělá, my ne.
- Placený/affiliate obsah: popisek začíná „Ad“ / „#ad“ (validátor to hlídá).
- Max **5 hashtagů** (limit Instagramu od 12/2025).
- Tajné klíče nikdy do chatu ani do gitu: lokálně `.env` (je v `.gitignore`).

## Rozbor @organic__101_ (hotovo)

`reports/organic__101_/2026-11-06.md` + `data/niche_profile.yaml`. Klíčová zjištění:
- 46 221 sledujících, ~6 postů/týden, publikuje 9–14 h newyorského času.
- Karusely/obrázky: medián ~2 250 lajků (4,9 %), reels jen ~240 (0,5 %).
- Nejlepší série: „The art of ___ maxxing“ (moodboard koláž na zemi/téma),
  „Then vs Now“, „This isn't X / This is“, seznamový obrázek („Toxin free kitchen“).
- Ultrakrátké popisky (1 věta + emoji), skoro bez hashtagů.
- Monetizace: placená Skool komunita „The Organic Lab“ (poslední slide karuselu),
  vlastní mýdla. Fotky skládá z cizích obrázků z internetu (to my nesmíme).

## Stav kódu (`igbot/`, Python 3.12+)

Lokálně: Intel Mac (bez GPU), virtuální prostředí `.venv` na **Pythonu 3.13**
(`uv venv --python 3.13 .venv`; pro 3.14 není `onnxruntime`, na kterém stojí `rembg`).
Spouštěj `.venv/bin/python -m igbot …`. Klíče se načítají z `.env` (`config.load_dotenv`).
Závislosti: `requirements.txt` (jádro, publikační workflow), `requirements-render.txt`
(+ `rembg` pro koláže, jen lokálně), `requirements-dev.txt` (vše + pytest).

| Soubor | Co dělá |
|---|---|
| `instagram.py` | Graph API klient (v26.0, host `graph.facebook.com`): publikace obrázek/karusel/story/reel, quota, insights, Business Discovery s `children{media_url}`. Token posílá v hlavičce `Authorization: Bearer`. Pole `shortcode` přes Business Discovery nejde. |
| `analyze.py` | `python -m igbot analyze <účet>`: 100 postů přes API, statistiky, Claude vision rozbor, report. |
| `links.py` | `inspect <odkaz>`: rozbor odkazu IG/TikTok/YouTube jen přes oficiální endpointy. |
| `generate.py` | Claude (`claude-opus-5-5`, structured output, streamování) navrhne týden koláží (formáty moodboard, list, then_vs_now, this_not_that; každý slide = nadpis + předměty s popiskem a hledáním fotek, závěrečný slide s výzvou) + stories. |
| `photos.py` | Hledání fotek: Pexels (s `PEXELS_API_KEY`) a Openverse CC0/PD, kontrola, že název/štítky fotky odpovídají předmětu, vyřazení AI obrázků, cache v `build/cache`, licence do `credits.json`. |
| `cutout.py` | Vystřižení předmětu (`rembg`, model isnet-general-use, CPU), skóre kvality výřezu (celý předmět, jeden objekt, barevnost, ne obdélník), finální výřez z plného rozlišení. |
| `collage.py` | Koláž (styl sticker): procedurální papír, nálepky s bílým obrysem, packer bez překryvů, závěrečný slide s předměty v řadě. `render.render_item` ji použije pro každou položku fronty, jejíž slidy mají `items` (preview i publish); licence fotek se uloží do `photo_credits` položky. Samostatně `python -m igbot collage <plan.json>` → `build/collage/<id>/`, ukázka `assets/examples/autumn-living.json`. |
| `render.py` | Starší textové slidy (Pillow). |
| `publish.py`, `content.py`, `hosting.py` | Fronta `content/{drafts,approved,published,failed}`, validace, upload na S3/R2, publikace. |
| `klapka.py` | Sync fronty do KLAPKY (Airtable base `appGpk4fkNBGoMyBN`, tabulka SM Obsah) a rozhodnutí schválit/zamítnout zpět. Paměť syncu v YAML položky (`klapka:`), jen změny, rozpočet ~150 volání/měsíc. Tep automatu = technický řádek `__automat__` (`recKqXpfurb4jkWmD`, KLAPKA ho čte pro pruh „Automat běží“, sync ho nikdy nemaže). Volá se po generate/approve/publish, ručně `python -m igbot klapka-sync`. Token `AIRTABLE_TOKEN` v `.env`. |
| `discover.py`, `insights.py` | Sledování podobných účtů, statistiky do `data/`. |

Testy: `.venv/bin/python -m pytest -q` (70 prochází). GitHub Actions v `.github/workflows/`
(publikace každých 30 min, týdenní plán jako PR, statistiky) zatím nemají secrets.
Dokumenty: `docs/PLAN.md` (strategie, monetizace, právo), `docs/NASTAVENI.md` (setup API).

## Proč přechod na lokální běh

V cloudu: žádná GPU (AI obrázky nejdou), a bezpečnostní kontrola zablokovala
nahrání obrázků na anonymní veřejné úložiště. Instagram API bere obrázky jen
z veřejné URL, takže bez úložiště (Cloudflare R2) nešlo publikovat.

## Další kroky

1. `.env` lokálně (viz `.env.example`): `IG_ACCESS_TOKEN` (uživatel má 60denní
   token z Graph API Exploreru, oprávnění instagram_basic, instagram_manage_insights,
   instagram_content_publish, pages_show_list, pages_read_engagement,
   business_management), `ANTHROPIC_API_KEY`, později `PEXELS_API_KEY`, R2 klíče.
   `IG_USER_ID` není potřeba, je v `config/account.yaml`.
2. ~~Design~~ hotovo (styl sticker, `collage.py`). **Kvalita fotek:** Openverse
   vybírá podle názvů a často se netrefí (kolo místo vlašských ořechů). Potřeba:
   `PEXELS_API_KEY` + kontrola vybraných výřezů Claudem (vision), jestli ukazují
   předmět z popisku. Lokální AI obrázky nejdou (Intel Mac bez GPU).
3. **Publikace:** první testovací post „The art of autumn living“ (renderuje se
   z `build/post1_plan.json`, `build/` je gitignored, takže lokálně ho vyrob znovu).
   Buď ručně v aplikaci, nebo zařídit Cloudflare R2 (`MEDIA_BACKEND=s3`) a pak
   `python -m igbot publish`.
4. ~~Generátor~~ navrhuje koláže (všechny formáty zatím jako koláže; vlastní
   rozvržení pro then vs now / this not that později). Neověřeno živě, chybí
   `ANTHROPIC_API_KEY`. Koláže se renderují lokálně (rembg); pro plnou automatizaci
   je renderovat při schválení a nahrát na R2, publikace pak bere hotové URL.
5. Lead magnet / komunita později (model @organic__101_), affiliate na přírodní
   produkty do domácnosti a kuchyně.
