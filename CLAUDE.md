# Kontext projektu pro Clauda

Shrnutí dosavadní práce (cloudová relace, 25. 10. – 7. 11. 2026), aby lokální
Claude Code mohl navázat. Uživatel komunikuje **česky**; obsah účtu je **anglicky**.

## Cíl

Automatizovaný Instagram účet **@naturizz** inspirovaný účtem **@organic__101_**:
denní karusely + stories generované Claudem, publikované přes oficiální API,
s cílem růstu a monetizace. Uživatel chce postupovat společně a schvalovat kroky.

## Rozhodnutí uživatele

- Jazyk obsahu: **angličtina** (publikum USA/UK/CA/AU, časy `America/New_York`).
- Formát: **fotokarusely přes celý formát, 5–6 slidů** (slidy se swipují). 9. 11. 2026
  jsme zkusili karusel jako video Reel s populární hudbou (`reel.py`, `music.py`), Simon:
  „karusel na reelsku neznamená video ale fotky zvlášť“. Hudbu ale Instagram API připojí
  jen k Reelu (videu), k obrázku ani karuselu ne (ověřeno živě, „Invalid parameter“),
  takže karusely jdou bez hudby. Přepínač `feed.publish_as` (`carousel` / `reel`).
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
- **@organic__101_ je předloha** (Simon 9. 11. 2026: „okopíruj klidně celý karusel od
  organic … rozeber to na detaily“): přebíráme strukturu, témata, hustotu a typ
  popisků jeho nejlepších karuselů. Nikdy ale jeho fotky (autorská práva) a ne
  doslovně jeho texty a „maxxing“ (Instagram od 30. 4. 2026 nedoporučuje
  neoriginální obsah). Fotky vlastní (Pexels/CC0), barvy a písmo naše.
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
| `generate.py` | Claude (`claude-opus-5-5`, structured output, streamování) navrhne týden koláží (formáty moodboard, list, then_vs_now, this_not_that; každý post je karusel: titul, slidy s předměty s popiskem a hledáním fotek, závěrečný slide s výzvou; i seznam má titul + seznam + výzvu, od 8. 11. 2026 žádné samostatné obrázky) + stories. |
| `photos.py` | Hledání fotek: Pexels (s `PEXELS_API_KEY`) a Openverse CC0/PD, kontrola, že název/štítky fotky odpovídají předmětu, vyřazení AI obrázků, cache v `build/cache`, licence do `credits.json`. |
| `cutout.py` | Vystřižení předmětu (`rembg`, model isnet-general-use, CPU), skóre kvality výřezu (celý předmět, jeden objekt, barevnost, ne obdélník), finální výřez z plného rozlišení. |
| `collage.py` | Koláž podle rozboru nejlepších karuselů @organic__101_ (9. 11. 2026): **titul** = stěna fotek přes celý formát nahoře a dole, uprostřed natržený papír s nadpisem, výřezy na okrajích pruhu, bez popisků; **vnitřní slidy** = světlý papír, nahoře velká hero fotka (`hero: true`), nadpis, kolem 14–16 věcí natěsno (packer „snug“, když se něco nevejde, celé se zmenší): výřezy (jídlo, věci, bílý obrys) a obdélníkové fotky scén/aktivit (`photo: true`, `cutout.find_photo`, CLIP podobnost + jas), popisky jako životní styl („Riding a Vespa“), až na 2 řádky; **závěr** = stěna fotek z postu + výzva + @naturizz na pilulce. 5–6 slidů. Popisky musí odpovídat fotce, špatné fotky do `data/photo_rejects.txt`. Samostatně `python -m igbot collage <plan.json>`. |
| `reel.py` | Karusel jako Reel: slidy jako karty na tmavém pozadí se posouvají jako karusel (tečky, okraj další karty), 1080×1920, H.264 + tichá AAC stopa, ~17 s, ~3 MB, ffmpeg z `imageio-ffmpeg`. `prepare` ho uloží do `media/<id>.mp4` + `-cover.jpg`, položka dostane `reel: {video, cover}`. |
| `music.py` | Hudba k Reelu: hity jdou přes API najít jen v trendech (`GET /ig_audio` bez dotazu), hledání vrací jen knihovnu. Výběr z `data/music.yaml` (kurátorované trendy pro niku s náladami; rozšiřuj při přípravě postů) + aktuální trendy, které názvem sedí k nice; nálada postu podle formátu a nadpisu (`music_moods` ručně), bez opakování v posledních postech; záloha knihovna. Publikace zkusí písničku, alternativy, pak karusel. |
| `render.py` | Starší textové slidy (Pillow). |
| `publish.py`, `content.py`, `hosting.py` | Fronta `content/{drafts,approved,published,failed}`, validace, upload na S3/R2, publikace. |
| `klapka.py` | Sync fronty do KLAPKY (Airtable base `appGpk4fkNBGoMyBN`, tabulka SM Obsah) a rozhodnutí schválit/zamítnout zpět. Paměť syncu v YAML položky (`klapka:`), jen změny, rozpočet ~150 volání/měsíc. Tep automatu = technický řádek `__automat__` (`recKqXpfurb4jkWmD`, KLAPKA ho čte pro pruh „Automat běží“, sync ho nikdy nemaže). Volá se po generate/approve/publish, ručně `python -m igbot klapka-sync`. Token `AIRTABLE_TOKEN` v `.env`. |
| `discover.py`, `insights.py` | Sledování podobných účtů, statistiky do `data/`. |

Testy: `.venv/bin/python -m pytest -q` (71 prochází). GitHub Actions v `.github/workflows/`
(publikace každých 30 min, týdenní plán jako PR, statistiky) zatím nemají secrets.
Dokumenty: `docs/PLAN.md` (strategie, monetizace, právo), `docs/NASTAVENI.md` (setup API).

## Autopostování (zavedeno 7. 11. 2026, Simon: „Začni autopostovat content“)

Pracuje se na větvi **`main`** (výchozí; jen na ní běží plánované GitHub Actions,
které do ní zapisují stav fronty, takže před pushem vždy `git pull --rebase`).

1. **Koncepty** píše Claude Code (bez `ANTHROPIC_API_KEY`; generátor `generate`
   se použije, až klíč bude) do `content/drafts`, pravidla viz `SYSTEM` v `generate.py`.
2. **`python -m igbot prepare`** vyrenderuje slidy lokálně (rembg) do `media/`
   a do položky zapíše `media` = veřejné URL z `media.base_url` (raw.githubusercontent,
   repo je veřejné) + `media_from_slides: true` (alt texty zůstávají ze slidů).
   Náhled pro kontrolu: `build/prepare/<id>.jpg`. **Každou koláž zkontroluj
   očima** (vision) a špatné předměty vyměň/vyhoď, pak `prepare <id> --force`.
3. Commit + push `media/` a `content/`, pak `klapka-sync` → koncept je v KLAPCE
   (SM Automation → Obsah) i s náhledem, Simon schválí/zamítne.
4. **Schválené posty jsou zásoba bez data** (od 8. 11., Simon: „plánuj aktivně na základě
   statů, postuj z galerie schválených jak se ti zachce“). `igbot/scheduler.py` při každém
   běhu `publish.yml` rozhodne, jestli je chvíle a který post: 3 denně (≥6 v zásobě), jinak
   2/1, rozestup ≥3 h, 7–22 h NY, časy z výchozího odhadu niky + zásahu našich postů podle
   hodiny (`data/insights.csv`, workflow Statistiky), jedno okno denně zkouší méně ověřenou
   hodinu; formát podle výkonu, nikdy dvakrát za sebou stejný. `python -m igbot plan`
   ukáže denní plán (dnes a zítra: čas → post → proč, `scheduler.day_plan`); stejný plán
   jde jako JSON do pole „Denní plán“ technického řádku v KLAPCE (přehled ho ukazuje).
   Stories/reels mají dál pevný čas (`content.TIMED`).
   GitHub ve skutečnosti pouští workflow jen jednou za 3–6 h, plánovač to dohání.
   KLAPKA dostává všechny slidy v Náhledu a žádný Plán; sync se řídí uplynulým časem
   (stav `content/.automat.json`, zapisuje jen automat): změny a tep po novém postu
   nebo chybě, jinak ≤1× za 8 h, rozhodnutí ≤1× za 12 h. Rozbor a strategie:
   `reports/naturizz/2026-11-08.md`.

Pozor na cache: `build/cache/cutouts` je klíčovaná dotazem. Po přidání
`PEXELS_API_KEY` ji smaž, jinak zůstanou staré výřezy z Openverse.
Stories zatím negenerujeme (nový účet bez sledujících je nevidí).

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
