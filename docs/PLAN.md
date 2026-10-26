# Plán: Instagram účet v nice „organic“

Stav k 26. 10. 2026. Vychází z průzkumu šesti oblastí (oficiální API, algoritmus,
monetizace v ČR, právo a pravidla, technické řešení, nika). Asi 180 tvrzení prošlo
druhou nezávislou kontrolou proti primárním nebo důvěryhodným sekundárním zdrojům.
Co ověřit nešlo nebo stojí jen na sekundárním zdroji, je označené. Nejde o právní
ani daňové poradenství.

---

## 1. Co víme o `organic__101_`

Instagram profil bez přihlášení neukáže. Podle úryvků z vyhledávačů (**neověřeno**,
datum stažení neznámé):

- anglicky psaný účet typu „health coach“, kolem 45 tisíc sledujících, kolem 670 postů,
- témata: přirozený a „ancestral“ životní styl bez chemie (syrové mléko, maso, med,
  cvičení, víra),
- zpeněžení přes placenou komunitu na Skool („The Organic Lab“, 15 $ měsíčně,
  13 členů), propojení s IG účtem je odvozené jen ze shodného jména,
- `linktr.ee/organic__101_` i `youtube.com/@organic__101_` vrací 404.

Ověříme to hned po připojení API: `python -m igbot analyze organic__101_ --limit 100`
(funguje jen ve variantě B z NASTAVENI.md a jen pro veřejné firemní nebo autorské
účty bez věkového omezení).

**Co si bereme:** témata a formáty, které u něj fungují, jako signál.
**Co nebereme:** jeho posty, texty, fotky, videa, jméno, tvář ani příběh.

## 2. Proč obsah nekopírovat

- **Dosah:** od 30. 4. 2026 Instagram přestává doporučovat účty, které převážně
  zveřejňují cizí fotky, karusely a reels. Vodoznak, rámeček, titulky ani uvedení
  autora nepomůžou. Nový účet bez sledujících by tak měl dosah skoro nulový.
- **Peníze:** převzatý obsah nesplňuje pravidla monetizace (Content Monetization
  Policies), takže nedostane dárky, bonusy ani předplatné.
- **Právo:** autorská práva (opakované porušení = smazání účtu) a napodobování
  cizí identity.

Myšlenky, témata a formáty chráněné nejsou, konkrétní zpracování ano. Proto
všechno tvoříme vlastní.

## 3. Pozicování (rozhodnuto 26. 10. 2026)

- **Jazyk: angličtina.** Publikum USA, Velká Británie, Kanada a Austrálie, tedy
  mnohem větší trh než česká čtyřmilionová základna. Časy publikace jsou v čase
  východního pobřeží USA a po dvou týdnech je upravíme podle Insights.
- **Formát: jen karusely, žádné reels**, stejně jako zdrojový účet.
- **Téma:** přirozená strava a život s méně zbytečnou chemií: praktické záměny
  potravin, čtení etiket, sezónní suroviny, jednoduché recepty. Přesné pilíře,
  tón a vizuál nastavíme podle rozboru `organic__101_` (kap. 1).
- **Čemu se vyhneme:** léčebná tvrzení, „detoxy“, strašení „toxiny“, hormonální
  zázraky a propagace syrového mléka. Přehnaná zdravotní tvrzení a „zázračné léky“
  Instagram nedoporučuje lidem, kteří nás nesledují. Zdravotní tvrzení v reklamě
  a affiliate postech omezuje zákon (kap. 8). Zbytek je naše volba kvůli riziku
  a důvěryhodnosti.

**Co znamená „jen karusely“ (je dobré to vědět předem):**

- Karusely mají v datech analytických firem nejvyšší míru zapojení na dosah
  a nejvíc uložení. Reels ale mají větší dosah mimo sledující, takže růst bude
  pomalejší než s reels.
- Instagram od dubna 2026 hodnotí originalitu i u fotek a karuselů. Musíme mít
  vlastní design a vlastní texty, ne podobu zdrojového účtu.
- Karusely s hudbou se mohou objevit i v záložce Reels, ale hudbu přes API přidat
  nejde. Občas tedy můžeš karusel s hudbou zveřejnit ručně v aplikaci.
- Nativní peníze od Instagramu se pro čistě karuselový účet zúží na předplatné
  (od 10 000 sledujících). Dárky jsou jen u reels a prezentace obrázků a textové
  koláže nemají nárok na monetizaci obsahu. Hlavní příjmy budou affiliate,
  vlastní digitální produkty, komunita (jako u zdrojového účtu) a spolupráce
  se značkami (kap. 7).

## 4. Obsahový systém: co dělá bot a co ty

Týdně 7 karuselů (1 denně), denně 3 stories.

| Formát | Kolik | Kdo |
|---|---|---|
| Karusely | 1× denně | bot celý: anglický text, grafika, popisek, hashtagy; ty schválíš |
| Stories | 3× denně | bot celý (text na grafice) |
| Stories s nálepkou (anketa, otázka, odkaz) | 2–3× týdně | ty v aplikaci; API nálepky neumí, bot ke každé story navrhne nápad |
| Odpovědi na komentáře a DM | denně 10–15 minut | ty; automatické hromadné lajky, sledování ani DM nepoužíváme (porušení pravidel) |

**Koloběh:**

1. *Neděle:* analýza podobných účtů (`discover`) → Claude navrhne obsah na týden →
   pull request ke schválení.
2. *Ty:* projdeš návrhy a náhledy grafiky, upravíš a sloučíš PR.
3. *Každých 30 minut:* publikace naplánovaných příspěvků.
4. *Každou noc:* statistiky. Generátor z nich bere, co fungovalo.
5. *Kdykoli:* `inspect <odkaz>` na zajímavé posty z IG, TikToku nebo YouTube jako
   inspirace pro další plán.

## 5. Pravidla algoritmu, podle kterých bot píše

Z oficiálních popisů doporučování od Mety (2025–2026), vyjádření Adama Mosseriho
a dat analytických firem. Kde jde o naše výchozí hodnoty k testování, je to napsáno.

- **Hlavní signály:** čas sledování (dokoukání), lajky a sdílení do zpráv
  (Mosseri, leden 2025). Sdílení má o něco větší váhu u lidí, kteří nás nesledují,
  lajky u sledujících. Model Mety, který předpovídá sdílení do zpráv, bere v úvahu,
  jestli je obsah informativní (návody, recenze, how-to).
- **Reels:** háček do 3 sekund (odchod do 3 s je negativní signál), formát 9:16,
  vlastní zvuk, žádné vodoznaky jiných aplikací, text nesmí zakrývat většinu obrazu.
  Reels hlavně s textem Instagram ukazuje méně. Oficiálně musí mít reel nejvýš
  3 minuty, aby šel doporučovat; naše výchozí délka k testování je 7–45 s.
- **Karusely:** naše výchozí délka 5–10 slidů. Druhý slide musí fungovat i jako
  začátek, protože ho Instagram někomu ukáže první. Hudbu ke karuselu přes API
  přidat nejde.
- **Hashtagy:** nejvýš 5 (limit od prosince 2025), fungují jako štítky pro hledání,
  ne jako zdroj dosahu. Klíčová slova patří do prvního řádku popisku.
- **Čerstvost:** skoro polovina doporučených reels je mladší než den, takže
  pravidelnost je důležitá.
- **Stories** vidí jen sledující. Víc než asi 4–5 denně prý dosah snižuje
  (neověřená parafráze z roku 2025).
- **Zkušební reels (Trial Reels)** se ukazují jen lidem, kteří nás nesledují.
  Uvádí se, že jsou dostupné od 1 000 sledujících (neověřeno). Bot je umí publikovat.
- **Publikace přes API** dosah nesnižuje (podle Mosseriho z druhé ruky).
- **Konzistentní téma:** uživatelé teď vidí a upravují témata, se kterými je
  Instagram spojuje (funkce „Your Algorithm“; běží globálně v angličtině,
  dostupnost pro česky nastavenou aplikaci nebyla potvrzena).
- **Každý týden** zkontrolovat v aplikaci *Nastavení → Účet → Stav účtu*, jestli je
  účet způsobilý pro doporučování.

## 6. 90 dní ve třech sprintech

| Fáze | Co děláme | Na co se díváme |
|---|---|---|
| Dny 0–7: nastavení | rozbor `organic__101_` (screenshoty, pak API); vlastní vizuální šablona karuselů; autorský účet, veřejný; jméno a bio s anglickými klíčovými slovy; připojení API; analýza 5–10 podobných účtů; první týden obsahu | vše funguje nanečisto |
| Sprint 1 (dny 1–30) | testujeme 4–5 obsahových pilířů a typů karuselů (návod, mýtus vs. fakt, recept, seznam záměn) | sdílení/dosah, uložení/dosah, podíl dosahu mimo sledující; spodní polovinu škrtáme |
| Sprint 2 (dny 31–60) | zdvojnásobíme dva nejlepší pilíře; spolupráce (Collabs) s podobně velkými anglickými účty; lead magnet a e-mailový seznam | růst sledujících, podíl dosahu mimo sledující, přihlášení do e-mailu |
| Sprint 3 (dny 61–90) | škálujeme vítězné typy karuselů; první monetizace (affiliate, digitální produkt) | příjmy, konverze z bia, nabídky spoluprací |

Týdenní „severka“: engagement rate místo hrubých zhlédnutí (doporučuje Mosseri).
Počítáme ho jako zapojení / dosah; tahle definice je naše pracovní.

## 7. Monetizace podle velikosti účtu

Na co má účet nárok, rozhoduje země tvůrce (ČR), ne jazyk publika. Dostupnost
v ČR je ověřená tam, kde to není napsáno jinak. Prezentace obrázků a textové
koláže **nemají nárok na nativní monetizaci** Instagramu a dárky jsou jen
u reels. U čistě karuselového účtu proto stojí příjmy hlavně mimo Instagram.

| Sledující | Co zapnout | Poznámka |
|---|---|---|
| 0–1 000 | e-mailový seznam přes lead magnet (zdarma PDF v angličtině); affiliate programy pro anglické publikum (např. Amazon Associates US nebo programy jednotlivých e-shopů a značek); první digitální produkt (průvodce, nákupní seznam, recepty) za 9–29 $ přes Gumroad nebo Lemon Squeezy | podmínky affiliate pro tvůrce z ČR ověříme při registraci; e-maily jen se souhlasem (GDPR); Gumroad a Lemon Squeezy řeší DPH u digitálních produktů; zatím nepropagovat placeně (nákup reklamy u Mety = registrace k DPH jako identifikovaná osoba) |
| 1 000–10 000 | Meta Creator Marketplace (ČR podporována, značky z celého světa), přímé nabídky značkám s media kitem; placená komunita nebo měsíční členství (model zdrojového účtu: komunita na Skoolu) | před první placenou spoluprací volná živnost „Reklamní činnost, marketing, mediální zastoupení“ (poplatek asi 1 000 Kč, neověřeno na úředním webu); zvážit paušální daň (1. pásmo 9 162 Kč měsíčně od 7/2026) |
| 10 000–50 000 | předplatné (Subscriptions), sponzorované karusely, partnerské reklamy | předplatné je v ČR dostupné a Instagram si nebere nic, Apple a Google 30 %; ceny spoluprací na anglickém trhu jsme neověřovali, nastavíme je podle media kitu a nabídek |
| 50 000+ | dlouhodobé ambasadorství, vlastní produkt nebo e-shop, kurz nebo komunita | Instagram Shops tvůrcům z ČR nejsou dostupné, prodej přes vlastní web; u obratu nad 2 000 000 Kč plátce DPH od 1. 1. dalšího roku, nad 2 536 500 Kč hned |

**Nepočítat s:** dárky (jen reels), bonusy (jen na pozvánku), nativními affiliate
odkazy a nakupovatelnými reels (pro ČR zatím nejsou), Instagram Shops
(ČR nepodporována).

## 8. Právo a pravidla: checklist

- **Reklama:** spolupráci i affiliate je nutné označit hned na začátku postu,
  v jazyce postu. Podle advokátní kanceláře citující ČOI (epravo.cz, 12/2025,
  primární stránka ČOI nenalezena) stačí „Reklama“, „Sponzorovaný obsah“ nebo
  „Placené partnerství“; samotné „Spolupráce s…“ nestačí. U anglických postů
  používáme „Ad“ / „#ad“ / „Paid partnership“ na začátku, což odpovídá i obecnému
  požadavku americké FTC na jasné označení (FTC jsme v průzkumu podrobně
  neověřovali). Bot hlídá, aby popisek takto začínal.
  Štítek „Placené partnerství“ od Mety je přes API zdokumentovaný jen pro
  Facebook Login (u Unified Login neověřeno), vyžaduje způsobilost k brandovanému
  obsahu a nejvýš 2 sponzory; jinak se přidá ručně v aplikaci.
- **AI:** u obrázků a videí generovaných AI štítek `is_ai_generated` plus řádek
  „Created with the help of AI.“, obojí přidává bot. U textů se lze opřít o výjimku
  v AI Actu (čl. 50 odst. 4) jen za podmínek: člověk text věcně zkontroluje, nese
  za něj redakční odpovědnost a bot ho po schválení (sloučení PR) už nemění.
  Výjimka se netýká obrázků a videí. Archiv schválení je historie pull requestů.
- **Zdraví a jídlo** (platí pro reklamu, affiliate a sponzorované posty):
  zdravotní tvrzení o potravinách jen ve znění schváleném EU (nařízení 1924/2006);
  u doplňků text „doplněk stravy“ (zákon 40/1995, § 5d), v angličtině „food
  supplement“. U výrobků „pro zdraví“,
  které nejsou léčivem, nesmí reklama tvrdit, že zlepšují nebo udržují zdraví, ani
  že jejich nepoužívání škodí, a nesmí se opírat o vědce, zdravotníky nebo známé
  osobnosti (§ 5n). Syrové mléko: prodejce musí v místě prodeje uvádět
  „Syrové mléko, před použitím tepelně opracovat nebo pasterovat“ (vyhláška
  289/2007, § 13); náš obsah s tím nesmí být v rozporu.
- **Hudba:** jen Sound Collection od Mety, vlastní zvuk nebo licencovaná hudba.
  Žádné komerční hity v reklamních postech.
- **Automatizace:** jen oficiální API. Žádné hromadné sledování, lajky, komentáře,
  studené DM ani kupování sledujících. DM bot by směl jen odpovídat, s upozorněním,
  že jde o automat.
- **Data o konkurenci:** jen veřejné firemní metriky přes Business Discovery,
  krátká doba uchování. Data z YouTube API se po 30 dnech mažou (bot to dělá sám;
  vychází z YouTube API Developer Policies, část III.E.4, mimo hlavní průzkum).
- **Daně:** živnost před první placenou spoluprací. Výplaty od Mety (dárky,
  předplatné) mohou znamenat povinnost registrace k DPH jako identifikovaná osoba:
  ověřit s daňovým poradcem.

## 9. Náklady

| Položka | Měsíčně |
|---|---|
| Claude API (týdenní plány, rozbory, analýzy) | zhruba 50–200 Kč podle počtu rozborů |
| GitHub Actions (automatické spouštění) | 0 Kč (vejde se do bezplatného limitu) |
| Cloudflare R2 (úložiště obrázků a videí) | 0 Kč v rámci bezplatného tarifu; pro ostrý provoz vlastní doména (asi 10 $ ročně), protože adresa r2.dev je omezená a určená pro vývoj |
| YouTube Data API | 0 Kč (výchozí denní kvóta) |
| volitelně AI pozadí obrázků nebo krátká AI videa | asi 50–150 Kč |

## 10. Stav a další kroky

**Hotovo v repozitáři:** publikace (karusely, obrázky, stories; reels a zkušební
reels umí taky, ale nepoužíváme je), generátor týdenního obsahu v angličtině,
renderer grafiky, schvalování přes PR, statistiky, sledování podobných účtů,
`analyze` (rozbor účtu), `inspect` (rozbor odkazu z IG, TikToku nebo YouTube),
automatické spouštění na GitHubu. Zatím **neběželo naostro**: chybí účet a klíče.

**Společně spustíme:**

1. **Nastudovat `organic__101_`:** hned ze screenshotů, po připojení API přes
   `analyze` (popisky, čísla, obrázky až 100 postů). Výstup: témata, typy karuselů,
   co funguje, tón, vizuální styl, jak zpeněžuje.
2. Podle rozboru navrhnu vlastní vizuální šablonu karuselů (odlišnou od zdroje)
   a upravím niku v `config/account.yaml`.
3. Založíš účet a propojíme API podle [NASTAVENI.md](NASTAVENI.md) (asi 30–60 minut).
4. Analýza 5–10 podobných anglických účtů → první týdenní plán → projdeme ho.
5. Zkušební publikace nanečisto → ostrý start.

## Hlavní zdroje

- Originalita (30. 4. 2026): <https://creators.instagram.com/blog/rewarding-original-creators-on-instagram>,
  <https://creators.instagram.com/recommendations-and-originality>
- Jak funguje doporučování: <https://transparency.meta.com/features/explaining-ranking/ig-feed/>,
  <https://transparency.meta.com/features/explaining-ranking/ig-reels-chaining/>,
  <https://transparency.meta.com/features/explaining-ranking/ig-stories/>
- Publikace přes API: <https://developers.facebook.com/docs/instagram-platform/content-publishing>
- Štítek AI profilu: <https://creators.instagram.com/blog/ai-generated-profile-label>
- Limit 5 hashtagů: <https://www.socialmediatoday.com/news/instagram-implements-new-limits-on-hashtag-use/808309/>
- Předplatné a dárky v ČR: <https://help.instagram.com/478012211024479>, <https://help.instagram.com/738469380549477>
- Creator Marketplace: <https://help.instagram.com/1389278101788752>
- Shops nejsou v ČR: <https://help.instagram.com/321000045119159>
- Pravidla monetizace obsahu: <https://help.instagram.com/2635536099905516>
- Označování reklamy (ČOI): <https://www.epravo.cz/top/clanky/spoluprace-s-influencery-na-co-si-dat-pozor-120427.html>
- Zákon o regulaci reklamy: <https://www.zakonyprolidi.cz/cs/1995-40>
- AI Act čl. 50: <https://artificialintelligenceact.eu/article/50/>
- Dognet (bez živnosti): <https://www.dognet.cz/faq/>
