# Nastavení: jak se bot „přihlásí“ na Instagram

Bot se **nepřihlašuje heslem** a neovládá aplikaci jako člověk. Používá oficiální
Instagram API od Mety s přístupovým tokenem. Je to jediná cesta, za kterou Instagram
účty neblokuje. Heslo k účtu nikdy nedávej do kódu, do chatu ani do GitHubu.

Stav podle dokumentace Meta k 25. 10. 2026 (Graph API v26.0).

---

## Krok 1: Instagram účet (uděláš ty)

1. Založ nový účet. Jméno, fotka a bio musí být vlastní, **ne napodobenina
   `organic__101_`** (to by bylo vydávání se za jiný účet a důvod ke smazání).
2. *Nastavení → Typ účtu a nástroje → Přepnout na profesionální účet → **Autor (Creator)***.
   Creator otevírá monetizační nástroje (předplatné, dárky, Marketplace).
   Účet musí být **veřejný**.
3. Zapni dvoufázové ověření.

## Krok 2: Business portfolio a aplikace v Meta for Developers

Jsou dvě varianty:

| | **A: Instagram Login** | **B: Unified / Facebook Login (doporučeno)** |
|---|---|---|
| Co potřebuješ | jen IG účet | IG účet + Meta Business portfolio (zdarma) |
| Publikace postů, karuselů, stories, reels | ano | ano |
| Statistiky vlastního účtu | ano | ano |
| **Analýza podobných účtů (Business Discovery)** | **ne** | **ano** |
| Platnost tokenu | 60 dní, bot ho sám prodlužuje | lze vydat token bez expirace |

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
   `instagram_manage_comments`, `pages_show_list`, `pages_read_engagement`,
   `business_management`.
5. Zjisti ID Instagram účtu, ideálně v *Graph API Explorer*:
   `GET /me/accounts?fields=instagram_business_account{id,username}`
   (u Facebook Login přes stránku), nebo ho najdeš v nastavení API v dashboardu aplikace.

Protože aplikace slouží jen **tvému vlastnímu účtu**, stačí jí *Standard Access*:
žádné App Review ani ověření firmy. Pokud by Meta App Review přesto chtěla
(dokumentace si tu místy odporuje), projdeme to společně.

Poznámky z dokumentace (stav 10/2026):
- Meta teď pro nové aplikace doporučuje **Unified Login** (bez Facebook stránky,
  ale s business portfoliem, systémovým tokenem a webhookem). Funguje se stejným
  `IG_API_HOST=graph.facebook.com`. Varianta přes stránku a systémového uživatele
  výše je jednodušší na první spuštění; obě umí Business Discovery.
- Pokud stránka vyžaduje *Page Publishing Authorization* nebo dvoufázové ověření,
  musí být dokončené, jinak publikace selže.
- Po první testovací publikaci ověř z jiného účtu, že je příspěvek veřejně
  vidět (aplikace v režimu Development může mít omezení).
- Štítek „Placené partnerství“, ankety ve feedu a mazání příspěvků jdou přes API
  jen s Facebook/Unified Login.

### Varianta A (záložní, nejjednodušší)

Aplikace typu Business → Instagram → *API setup with Instagram login* → přidat účet →
**Generate token**. Token platí 60 dní; nastav `IG_API_HOST=graph.instagram.com`.
Prodlužuje se příkazem `python -m igbot refresh-token` (nejpozději do 60 dní, jinak
je nutné nové přihlášení).

## Krok 3: Úložiště obrázků

Instagram si obrázky stahuje z veřejné URL. Doporučení: **Cloudflare R2** (bezplatný
tarif stačí):

1. Cloudflare → R2 → vytvořit bucket (např. `ig-media`) → zapnout *Public access*
   (r2.dev subdoména) → poznamenat veřejnou URL.
2. *Manage R2 API Tokens* → token s právem *Object Read & Write* jen pro tento bucket.

Alternativa: `MEDIA_BACKEND=github`, ale jen pokud je tento repozitář **veřejný**,
a pro zpeněžovaný účet ji nedoporučuju (GitHub není CDN pro média).

## Krok 4: Claude API klíč

Na <https://console.anthropic.com> vytvoř API klíč. Vygenerování obsahu na týden
vyjde zhruba na 5–15 Kč.

## Krok 4b (volitelné): YouTube API klíč

Pro popis, tagy a počty zhlédnutí, lajků a komentářů u YouTube odkazů v `inspect`: <https://console.cloud.google.com> →
nový projekt → *APIs & Services → Library → YouTube Data API v3 → Enable* →
*Credentials → Create credentials → API key* (omezit na YouTube Data API v3).
Denní bezplatná kvóta stačí na stovky rozborů.

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
| Variable | `S3_PUBLIC_BASE_URL` | veřejná URL bucketu (`https://pub-….r2.dev`) |

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
