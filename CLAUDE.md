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
- Design má být **ve stylu @organic__101_** (koláž vystřižených fotek-„samolepek“,
  velký serifový nadpis, papírové pozadí, malé popisky). Současná šablona
  (`igbot/moodboard.py`, fotky v rámečcích na šalvějovém pozadí) se mu nelíbí.
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

| Soubor | Co dělá |
|---|---|
| `instagram.py` | Graph API klient (v26.0, host `graph.facebook.com`): publikace obrázek/karusel/story/reel, quota, insights, Business Discovery s `children{media_url}`. Token posílá v hlavičce `Authorization: Bearer`. Pole `shortcode` přes Business Discovery nejde. |
| `analyze.py` | `python -m igbot analyze <účet>`: 100 postů přes API, statistiky, Claude vision rozbor, report. |
| `links.py` | `inspect <odkaz>`: rozbor odkazu IG/TikTok/YouTube jen přes oficiální endpointy. |
| `generate.py` | Claude (`claude-opus-5-5`, structured output) navrhne týden karuselů + stories. |
| `moodboard.py` | Šablona karuselu + stahování CC0/PD fotek z Openverse. **K předělání.** |
| `render.py` | Starší textové slidy (Pillow). |
| `publish.py`, `content.py`, `hosting.py` | Fronta `content/{drafts,approved,published,failed}`, validace, upload na S3/R2, publikace. |
| `discover.py`, `insights.py` | Sledování podobných účtů, statistiky do `data/`. |

Testy: `python -m pytest -q` (42 prochází). GitHub Actions v `.github/workflows/`
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
2. **Předělat design** na koláž ve stylu @organic__101_, ale s vlastní identitou:
   vystřižené předměty přes `rembg` (open-source, pip), 10–15 položek kolem
   velkého nadpisu, papírová textura, popisky u předmětů, vlastní barvy/písmo
   (DM Serif Display je v `assets/fonts/`). Fotky: Pexels API (komerčně OK, bez
   uvedení autora) + Openverse CC0/PD; ideálně předmět na čistém pozadí.
   Volitelně lokální AI (FLUX schnell / mflux na Macu), pokud má uživatel GPU.
   Ukázat 2 varianty stejného postu, než se to zautomatizuje.
3. **Publikace:** první testovací post „The art of autumn living“ (renderuje se
   z `build/post1_plan.json`, `build/` je gitignored, takže lokálně ho vyrob znovu).
   Buď ručně v aplikaci, nebo zařídit Cloudflare R2 (`MEDIA_BACKEND=s3`) a pak
   `python -m igbot publish`.
4. Generátor přizpůsobit novým formátům (moodboard, then vs now, this not that,
   seznam) podle `data/niche_profile.yaml`; popisky krátké.
5. Lead magnet / komunita později (model @organic__101_), affiliate na přírodní
   produkty do domácnosti a kuchyně.
