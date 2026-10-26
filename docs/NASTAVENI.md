# Nastavení: jak se bot „přihlásí“ na Instagram

Bot se **nepřihlašuje heslem** a neovládá aplikaci jako člověk. Používá oficiální
Instagram API od Mety s přístupovým tokenem. Je to jediná cesta automatizace, kterou
Meta povoluje; i tak je nutné dodržovat pravidla obsahu a proti spamu (žádné hromadné
akce). Heslo k účtu nikdy nedávej do kódu, do chatu ani do GitHubu.

Stav podle dokumentace Meta k 25. 10. 2026 (Graph API v26.0).

---

## Krok 1: Instagram účet (uděláš ty)

1. Založ nový účet. Jméno, fotka a bio musí být vlastní, **ne napodobenina
   `organic__101_`** (to by bylo vydávání se za jiný účet a důvod ke smazání).
2. *Nastavení → Typ účtu a nástroje → Přepnout na profesionální účet → **Autor (Creator)***.
   API i monetizace (předplatné, dárky, Marketplace) fungují s jakýmkoli
   profesionálním účtem; Creator volíme hlavně kvůli širší hudební knihovně.
   Účet musí být **veřejný** a vlastník plnoletý.
3. Zapni dvoufázové ověření.

## Krok 2: Business portfolio a aplikace v Meta for Developers

Jsou dvě varianty:

| | **A: Instagram Login** | **B: Facebook Login (doporučeno)** nebo Unified Login |
|---|---|---|
| Co potřebuješ | jen IG účet | Facebook Login: IG účet propojený s Facebook stránkou (+ Business portfolio pro systémového uživatele). Unified Login: Business portfolio, HTTPS redirect URL a HTTPS webhook, stránka není potřeba |
| Publikace postů, karuselů, stories, reels | ano | ano |
| Statistiky vlastního účtu | ano | ano |
| **Analýza podobných účtů (Business Discovery)** | **ne** | **ano** |
| Štítek placeného partnerství, ankety ve feedu, mazání přes API | ne | zdokumentováno pro Facebook Login; u Unified Login neověřeno |
| Platnost tokenu | 60 dní, prodlužuješ příkazem `refresh-token` (ručně, před 60. dnem) | token systémového uživatele lze vydat bez expirace (Meta doporučuje expirující; i tak může být zneplatněn) |

Pro náš plán (hledání a sledování podobných účtů) je potřeba **varianta B**.

### Varianta B, krok za krokem

1. Na <https://business.facebook.com> založ Business portfolio a přidej do něj
   Instagram účet (*Nastavení → Účty → Instagramové účty → Přidat*).
   Pokud chceš jít přes Facebook Login, vytvoř i Facebook stránku a propoj ji s IG účtem.
2. Na <https://developers.facebook.com/apps> vytvoř aplikaci typu **Business**
   a přidej k ní produkt/use case pro Instagram (správa obsahu a zpráv na Instagramu).
   Aplikaci připoj ke svému Business portfoliu.
3. *Business nastavení → Uživatelé → Systémoví uživatelé → Přidat* (role Admin).
   Systémovému uživateli přiřaď aktiva: aplikaci a Instagram účet (případně stránku).
4. *Vygenerovat nový token* → vyber aplikaci → expirace **Nikdy** → oprávnění:
   `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`,
   `instagram_manage_comments`, `instagram_manage_contents` (mazání),
   `pages_show_list`, `pages_read_engagement` a `ads_read` (role na stránce přes
   Business portfolio to vyžaduje). `business_management` jen pokud ho Meta
   při generování výslovně chce.
5. Zjisti ID Instagram účtu, ideálně v *Graph API Explorer*:
   `GET /me/accounts?fields=instagram_business_account{id,username}`
   (Facebook Login přes stránku), u tokenu z Unified Login
   `GET /me/assigned_instagram_accounts`.

Protože aplikace slouží jen **tvému vlastnímu účtu**, stačí jí *Standard Access*:
App Review podle přehledu dokumentace potřeba není. Dokumentace si ale místy
odporuje: návod k vytvoření aplikace uvádí, že přepnutí aplikace do režimu Live
vyžaduje ověřenou firmu (Business Verification). Business Discovery je
zdokumentované pro uživatelský token; s tokenem systémového uživatele to ověříme
při prvním spuštění. Pokud Meta něco z toho bude chtít, projdeme to společně.

Poznámky z dokumentace (stav 10/2026):
- Meta teď pro nové aplikace doporučuje **Unified Login** (bez Facebook stránky,
  ale s business portfoliem, HTTPS webhookem a tokenem systémového uživatele;
  `instagram_manage_messages` je v něm povinné a `instagram_manage_insights`
  se musí přidat ručně). Funguje se stejným `IG_API_HOST=graph.facebook.com`.
  Varianta přes stránku výše je jednodušší na první spuštění; obě umí Business
  Discovery. U čistého Unified Login je potřeba otestovat zkušební reels,
  štítek partnerství, ankety a mazání.
- Pokud stránka vyžaduje *Page Publishing Authorization* nebo dvoufázové ověření,
  musí být dokončené, jinak publikace selže.
- Po první testovací publikaci ověř z jiného účtu, že je příspěvek veřejně
  vidět (aplikace v režimu Development může mít omezení).
- Štítek „Placené partnerství“, ankety ve feedu a mazání příspěvků jsou přes API
  zdokumentované jen pro Facebook Login; štítek navíc vyžaduje způsobilost
  k brandovanému obsahu.

### Varianta A (záložní, nejjednodušší)

1. Aplikace typu Business (use case „Other“) → Instagram → *API setup with Instagram
   business login* → přidat účet jako testera.
2. Pozvánku přijmi na webu Instagramu: *Nastavení → Oprávnění webů → Aplikace
   a weby → Pozvánky pro testery*.
3. Vyplň *Business login settings* (redirect URL, deauthorize a data deletion URL;
   pro vlastní účet stačí jednoduchá stránka).
4. **Generate token** → token se ukáže jen jednou, hned ho zkopíruj. Platí 60 dní;
   nastav `IG_API_HOST=graph.instagram.com`.
5. Prodlužuje se příkazem `python -m igbot refresh-token`: nejdřív 24 hodin po
   vydání, nejpozději do 60 dní (pak už nejde a je nutné nové přihlášení). Nový
   token se uloží do `build/new_token.txt` a ty ho přepíšeš v GitHub secrets.

## Krok 3: Úložiště obrázků

Instagram si obrázky stahuje z veřejné URL. Doporučení: **Cloudflare R2** (bezplatný
tarif stačí):

1. Cloudflare → R2 → vytvořit bucket (např. `ig-media`).
2. Veřejný přístup: na zkoušku stačí subdoména r2.dev, ta je ale omezená a určená
   pro vývoj. Pro ostrý provoz připoj vlastní doménu spravovanou v Cloudflare
   (asi 10 $ ročně), např. `media.tvojedomena.cz`. Tu pak dej do `S3_PUBLIC_BASE_URL`.
3. *Manage R2 API Tokens* → token s právem *Object Read & Write* jen pro tento bucket.

Alternativa: `MEDIA_BACKEND=github`, ale jen pokud je tento repozitář **veřejný**,
a pro zpeněžovaný účet ji nedoporučuju (GitHub není CDN pro média).

## Krok 4: Claude API klíč

Na <https://console.anthropic.com> vytvoř API klíč. Vygenerování obsahu na týden
vyjde zhruba na 5–15 Kč.

## Krok 4b (volitelné): YouTube API klíč

Pro popis, tagy a počty zhlédnutí, lajků a komentářů u YouTube odkazů v `inspect`: <https://console.cloud.google.com> →
nový projekt → *APIs & Services → Library → YouTube Data API v3 → Enable* →
*Credentials → Create credentials → API key* (omezit na YouTube Data API v3).
Jeden rozbor stojí jednu jednotku z výchozí bezplatné denní kvóty (10 000 jednotek).

## Krok 5: Uložení do GitHubu

*Repozitář → Settings → Secrets and variables → Actions*:

| Typ | Název | Hodnota |
|---|---|---|
| Secret | `IG_USER_ID` | ID Instagram účtu z kroku 2 |
| Secret | `IG_ACCESS_TOKEN` | token z kroku 2 |
| Secret | `ANTHROPIC_API_KEY` | klíč z kroku 4 |
| Secret | `YOUTUBE_API_KEY` | klíč z kroku 4b (volitelné) |
| Secret | `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | R2 token z kroku 3 |
| Variable | `IG_API_HOST` | `graph.facebook.com` (B) nebo `graph.instagram.com` (A) |
| Variable | `IG_API_VERSION` | `v26.0` |
| Variable | `MEDIA_BACKEND` | `s3` |
| Variable | `S3_BUCKET` | název bucketu |
| Variable | `S3_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| Variable | `S3_PUBLIC_BASE_URL` | veřejná URL bucketu (vlastní doména, na zkoušku `https://pub-….r2.dev`) |

Dále *Settings → Actions → General → Workflow permissions*: zapnout
**Read and write permissions** a **Allow GitHub Actions to create and approve pull requests**.

## Krok 6: První spuštění (společně)

1. *Actions → Týdenní plán obsahu → Run workflow* → vznikne PR s koncepty.
2. Projdeme koncepty, upravíme je a PR sloučíme (= schváleno).
3. *Actions → Publikace → Run workflow* s volbou **dry run** → zkontrolujeme výpis.
4. Pak už jede automaticky: publikace každých 30 minut podle plánu, statistiky
   každou noc, nový plán každou neděli.

Lokálně to jde i bez GitHubu:

```bash
pip install -r requirements-dev.txt
cp .env.example .env   # doplnit hodnoty, soubor se necommituje
set -a; . ./.env; set +a
python -m igbot generate --days 7
python -m igbot preview          # obrázky v build/preview
python -m igbot approve
python -m igbot publish --dry-run
```
