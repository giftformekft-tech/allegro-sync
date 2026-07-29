# Allegro-integráció – terv

Fejlesztési terv. Önállóan végrehajtható, előzetes kontextus nélkül.

**Státusz:** terv, még nincs kód. Döntést igénylő pontok a 10. fejezetben.

**Rögzített keretek** (2026-07-29):

- Allegro eladói fiók és API-alkalmazás **megvan** (`fmshirt`).
- **Nincs EAN/GTIN, és nem is lesz.** Ez a terv központi megkötése – lásd 7. fejezet.
- **Csak a magyar piac** (allegro.hu). Nincs PL/CZ/SK értékesítés.

**Források.** A terv a hivatalos fejlesztői portál dokumentációján alapul:
az „Alapvető információk" oldal (magyar) és a **teljes, 473 oldalas
OpenAPI-referencia** (279 végpont), amely a
`giftformekft-tech/allegro-sync` repóban van
(`Allegro Developer Portal - baza wiedzy o Allegro REST API.pdf`).
Ezzel a 6., 7. és 8. fejezet végpontjai és mezői **ellenőrzöttek**, nem
becslésen alapulnak.

---

## 0. Kontextus

A forme.hu egy magyar, saját gyártású ajándéktárgy-webshop (WooCommerce +
`mockup-generator` plugin): egyedi mintás pólók, pulcsik, bögrék, saját nyomdával.
A termékkínálat **virtuális**: egy minta (design) × terméktípus × szín × méret
kombinációkból áll össze, a mockup képek generáltak.

Ma egy marketplace-re megy kivitel: **Temu**. Az `admin/class-temu-export-page.php`
+ `includes/class-temu-xlsx-writer.php` páros egy XLSX-mestersablont tölt fel
adatsorokkal, amit a felhasználó **kézzel tölt fel** a Temu felületére.
Nincs API-hívás, nincs visszacsatolás, nincs rendeléskezelés.

Az Allegro ettől **alapjaiban különbözik**: valódi REST API van, tokennel,
aszinkron műveletekkel, rendelés-eseményfolyammal és számlafeltöltéssel.
Tehát nem „még egy exportfájl" kell, hanem egy **kétirányú szinkron program**.

Az Allegro 2026 januárjában nyitotta meg a platformot magyar kereskedőknek;
nincs havidíj, csak sikeres eladás után jutalék, és **180 napos 0% jutalékos
welcome program** fut.
([hvg.hu](https://hvg.hu/kkv/20260121_allegro-magyar-kereskedok-beenged))

---

## 1. Amit meg kell építeni

| # | Funkció | Prioritás |
|---|---|---|
| 0 | **Kategória-felderítő** – megvalósíthatóság eldöntése EAN nélkül | **P0 – ez az első** |
| 1 | OAuth2 bejelentkezés + token-frissítés (sandbox és éles) | P0 |
| 2 | forme.hu CSV/XLSX beolvasás | P0 |
| 3 | Kategória- és paraméter-térkép | P0 |
| 4 | Képfeltöltés (mockup → Allegro CDN) | P0 |
| 5 | Saját katalógustermék javaslása (`product-proposals`) | P0 |
| 6 | Ajánlat létrehozás + aszinkron művelet követés | P0 |
| 7 | Állapottár: SKU ↔ offerId ↔ productId | P0 |
| 8 | GPSR-adatok (`productSafety`, felelős gyártó) | P0 – jogszabályi |
| 9 | **GTIN-őrszem** – figyelmeztetés, ha kötelezővé válik | P0 – egzisztenciális |
| 10 | Ár- és készletszinkron (tömeges) | P1 |
| 11 | Rendelés-lehúzás eseményfolyamból | P1 |
| 12 | szamlazz.hu számlázás + számla visszatöltés Allegróra | P1 |
| 13 | Szállítási adat / csomagszám visszaírás | P2 |

Ami **kikerült** a magyar-piac-only döntés miatt: cross-border megosztás,
OSS-számlázás, devizakezelés.

---

## 2. Üzleti keretek

### 2.1 Csak magyar piac – amit ez egyszerűsít

- **ÁFA:** belföldi értékesítés, egységes 27% – **nincs OSS**, nincs célország
  szerinti kulcslogika. A számlázó modul ezzel jelentősen egyszerűbb.
- **Deviza:** HUF-ban árazunk és HUF-ban számolunk el.
- **Nyelv:** magyar cím és leírás.
- **Szállítás:** csak belföldi.

### 2.2 Az alappiac kérdése – most már konkrétan megfogható

Az OpenAPI-referencia két mezőt ad, ami ezt eldönti:

- `language` – „Declared base language of the offer" (az ajánlat deklarált alapnyelve)
- `additionalMarketplaces` – *„This field does not contain information about the
  base marketplace of the offer"*; a lehetséges `marketplaceId` értékek a
  `GET /marketplaces` erőforrásból jönnek.

Tehát az ajánlatnak van **alappiaca** és vannak **további piacai**, és a
`GET /marketplaces` megmondja, mi közülük elérhető a fióknak.

**Konkrét induló ellenőrzés:** `GET /marketplaces` lefuttatása a meglévő
`fmshirt` fiókkal. Ha az `allegro-hu` alappiacként választható, magyarul
listázunk és kész. Ha nem, akkor az alappiac PL marad, és a magyar szöveget
a **fordítás-erőforrásokon** keresztül adjuk meg:

```
GET   /sale/offers/{offerId}/translations
PATCH /sale/offers/{offerId}/translations/{language}
```

Ez fontos mentőöv: **nem vagyunk az Allegro gépi fordítására utalva** –
a magyar címet és leírást saját kezűleg feltölthetjük. Egyedi mintás,
szójátékos feliratoknál ez nem kozmetikai kérdés.

### 2.3 Egyedi/személyre szabott termék és az elállási jog

A POD-termékek „személyre szabottak", ezért a 14 napos elállási jog rájuk
jellemzően nem vonatkozik – de ezt az ajánlatban **deklarálni kell**.
Ha viszont a minta előre gyártott (nem a vevő küldi egyedileg), akkor
**vonatkozik**. Tisztázandó, melyik esetbe esik a kínálat.

### 2.4 GPSR és AI-tartalom

Két deklarációs kötelezettség, mindkettőre van API-mező:

- **`productSafety`** (a termékjavaslatban): `responsibleProducers` +
  `safetyInformation`. A 2024 decemberétől hatályos uniós termékbiztonsági
  rendelet miatt kötelező.
- **`aiCoCreatedContent`** (az ajánlaton és a termékjavaslaton is):
  *„Information about content declared as generated using AI."*

Ez utóbbi minket **közvetlenül érint**: a repóban van
`includes/class-ai-seo-generator.php`, tehát a leírások egy része AI-val
készül, és a mockup-képek is generáltak. Az `aiCoCreatedContent` mező
`images` és `paths` szerkezetet vár – tisztázni kell, mi minősül
deklarálandónak, és a mapperben ezt ki kell tölteni.

---

## 3. Architektúra – hol lakjon a kód

| Opció | Előny | Hátrány |
|---|---|---|
| **A.** Plugin admin oldal (Temu-minta) | Ismerős UI, közvetlen WooCommerce-adat, nem kell CSV | WP-cron megbízhatatlan a rendszeres szinkronhoz; a plugin már így is hatalmas; OAuth-token tárolás/refresh WP-ben kényelmetlen |
| **B.** Önálló PHP CLI program | Composer, tesztelhető, valódi cronon fut, hosszú futású szinkron OK | Külön telepítés, külön hely |
| **C.** Hibrid *(javaslat)* | A plugin csak **exportál** egy CSV-t (mint a Temunál); az önálló program végzi az API-munkát | Két komponens |

**Javaslat: C.** Indoklás:

- A rendelés- és számlaszinkron **folyamatosan** kell fusson (5–15 percenként).
  Ezt WP-cronra tenni hiba lenne – a WP-cron csak akkor fut, ha van látogató.
- Az OAuth refresh-token 3 hónapig él, a hozzáférési token 12 óráig. Ennek
  kezelése állandó állapottárral (SQLite) sokkal tisztább, mint `wp_options`.
- A CSV-határ pontosan az, amit kértél, és egyben **jó szeparáció**: az Allegro-oldal
  nem függ a WooCommerce belső szerkezetétől.
- A plugin exportőr gyakorlatilag a meglévő Temu CSV-export másolata, kibővítve.

### 3.1 Javasolt könyvtárszerkezet

```
allegro-sync/
  bin/allegro                 # CLI belépési pont
  src/
    Auth/TokenStore.php       # token mentés + refresh
    Auth/DeviceFlow.php       # bejelentkezés böngésző nélkül
    Api/Client.php            # HTTP, User-Agent, rate limit, 429 backoff, Trace-Id log
    Api/Operations.php        # aszinkron művelet-pollozás
    Discover/CategoryScanner.php   # <-- a 0. fázis eszköze
    Discover/GtinWatchdog.php      # <-- 7.6
    Import/CsvReader.php      # forme.hu CSV/XLSX
    Import/RowValidator.php
    Map/CategoryMap.php       # forme típus -> Allegro kategória + paraméterek
    Map/TitleBuilder.php      # 12–75 karakter, min. 3 szó (7.5)
    Map/OfferBuilder.php
    Map/ColorMap.php
    Map/SizeMap.php
    Sync/ImageSync.php
    Sync/ProductProposalSync.php
    Sync/OfferSync.php
    Sync/PriceStockSync.php
    Sync/OrderSync.php
    Invoice/SzamlazzClient.php
    Invoice/InvoiceUploader.php
    State/Db.php              # SQLite
  config/
    categories.php            # kézzel karbantartott kategória-térkép
    .env                      # client id/secret, szamlazz kulcs
  var/state.sqlite
```

---

## 4. Adatfolyam

```
forme.hu (WooCommerce plugin)
    │  „Allegro export" gomb
    ▼
allegro-export.csv  ── termékvariáns-soronként
    │
    ▼
allegro-sync import           (validálás, dry-run)
    │
    ├─ ImageSync            ─► POST /sale/images
    ├─ ProductProposalSync  ─► POST /sale/product-proposals   (409 → meglévő productId)
    ├─ OfferSync            ─► POST /sale/product-offers      (INACTIVE!)
    │                            └─► 202 → operation polling → offerId
    ▼
Ellenőrző kör  ─► tömeges aktiválás
    │
    ├─ PriceStockSync  ◄── napi CSV újraolvasás
    ├─ GtinWatchdog    ◄── heti ellenőrzés (7.6)
    │
    └─ OrderSync   ◄── GET /order/events
             │
             ├─► szamlazz.hu Számla Agent  ─► PDF (27% ÁFA, HUF)
             └─► POST /order/checkout-forms/{id}/invoices
                 PUT  /order/checkout-forms/{id}/invoices/{invId}/file
```

---

## 5. A forme.hu export CSV sémája

A mai Temu CSV (`admin/class-temu-export-page.php:1059`) oszlopai:

```
Termék neve; SKU; Sub SKU; Szín; Méret; Leírás; Kép URL
```

Ez az Allegróhoz **kevés**. Hiányzik belőle a legfontosabb kettő: **ár** és **készlet**.
Javasolt bővített séma:

| Oszlop | Forrás | Kötelező | Megjegyzés |
|---|---|---|---|
| `sku` | jelenlegi `SKU` + variáns | ✔ | **Ez lesz az `external.id`** – idempotencia-kulcs |
| `parent_sku` | alap SKU | ✔ | csoportosításhoz, riportokhoz |
| `name` | terméknév + típus | ✔ | **12–75 karakter, min. 3 szó** – lásd 7.5 |
| `description` | kategória-SEO szöveg | ✔ | HTML, szekciókra bontva, max. 40 000 bájt |
| `type` | terméktípus slug (polo, pulcsi, bogre) | ✔ | kategória-térkép kulcsa |
| `color` | szín címke | ✔ | Allegro paraméterértékre kell képezni |
| `size` | méret | ✔ | ua.; ruházatnál `sizeTable` is szóba jön |
| `price_huf` | **új** | ✔ | bruttó, HUF; **stringként** megy tovább (6.0) |
| `stock` | **új** | ✔ | POD-nál jellemzően fix nagy szám |
| `image_url` | mockup URL | ✔ | több kép is: `image_url_2..n` |
| `weight_g` | **új** | ✔ | szállítási díjszabáshoz |
| `brand` | **új** | ✔ | GPSR + Allegro paraméter |
| `material` | **új** | – | pl. „100% pamut", kategóriaparaméter |
| `ai_content` | **új** | – | AI-val készült leírás/kép jelölése (2.4) |

**EAN oszlop nincs** – tudatos döntés, lásd 7. fejezet.

### 5.1 Két csapda a meglévő exportban

**A `Sub SKU` random generálása** (`str_shuffle`, `class-temu-export-page.php:1181`)
az Allegrónál kifejezetten káros: minden export új azonosítót adna, és
**duplikált ajánlatokat** hoznánk létre. Az Allegro-exportban az SKU-nak
determinisztikusnak és stabilnak kell lennie:
`{alap_sku}-{tipus}-{szin}-{meret}`.

**A kamu 14Y-os sor** (`:1244`) Temu-specifikus hack – az Allegro-exportból
ki kell maradnia.

### 5.2 XLSX

XLSX-beolvasás is kell (kérted): a `MG_Temu_Xlsx_Writer` csak *ír*.
Olvasáshoz vagy egy minimál XLSX-olvasót írunk (a ZIP + `sharedStrings`
megközelítés a repóban már ismerős), vagy a CSV-t tesszük kötelezővé.
**Javaslat: CSV a kötelező formátum, XLSX opcionális kényelmi funkció.**

---

## 6. Allegro API

### 6.0 Kötelező kliens-viselkedés

Ezek nem stílusjavaslatok – az API elutasítja vagy megbünteti a kérést nélkülük.

**User-Agent – kötelező.** A REST API Szabályzat 3.4(c) pontja megköveteli az
alkalmazás egyértelmű azonosítását. Formátum:

```
AlkalmazasNev/Verzio (+https://info-oldal-url)
```

Az alkalmazásnévnek **egyeznie kell a regisztrált alkalmazás nevével**, és
mutatnia kell egy elérhető információs oldalra. Validátor:
`https://apps.developer.allegro.pl/user-agent`.

A portál külön kiemeli: a User-Agent tartalmát **ne változtassuk**
(a szoftververziót se), mert fehérlistázási tényezőként használják. Ha nincs
rendes User-Agent, szokatlan aktivitásnál **az alkalmazás IP-címét megelőzően
blokkolhatják**. Ezt az első kódsortól kezdve helyesen kell csinálni.

**Verziózás.** Kötelező az erőforrás-verzió az `Accept` és `Content-Type`
fejlécben: `application/vnd.allegro.public.v1+json`. Béta erőforrásoknál
`application/vnd.allegro.beta.v1+json`. Kivétel: `DELETE` és az OAuth-végpontok.
Rossz verzió → `406 Not Acceptable`.

**Nyelv.** `Accept-Language: hu-HU` **támogatott** (a támogatott értékek:
`en-US`, `pl-PL`, `uk-UA`, `sk-SK`, `cs-CZ`, `hu-HU`). Ezzel a kategória- és
paraméternevek, valamint a hibák `userMessage` mezője magyarul jön vissza.
Alapértelmezés nélkül lengyelül kapjuk.

> Kivétel: a `GET /sale/category-parameters-scheduled-changes` erőforrás
> **csak `pl-PL`-t fogad**. A GTIN-őrszemnél (7.6) ezzel számolni kell.

**Trace-Id.** Minden válasz tartalmaz egy `Trace-Id` fejlécet, ami egyedileg
azonosítja a kérést; hibabejelentésnél az Allegro ezt kéri.
→ **Minden API-hívásnál naplózni kell.**

**Ár mint karakterlánc.** Az ár `{"amount": "10.23", "currency": "HUF"}`
formában megy – az `amount` **string**, nem szám. A mapperben ezért nem
lebegőpontos aritmetikát kell használni, hanem egész értéket és
string-formázást, különben kerekítési hibák keletkeznek.

**Azonosítók mint karakterlánc.** Az API az azonosítókat mindig stringként adja
vissza (gyakran UUID). Az állapottárban is stringként tároljuk.

**`commandId` – mi generáljuk.** A tömeges műveleteknél a `commandId` a
**kérés azonosítója, amit nekünk kell UUID-ként előállítani**, és amivel
utána lekérdezhető az állapot
(`GET /sale/offer-modification-commands/{commandId}`, illetve `/tasks`).
Ez egyben **idempotencia-kulcs** – újrapróbálkozásnál ezt kell kihasználni.

**Lapozás.** `offset` + `limit` (a `limit` erőforrásfüggő, jellemzően max. 1000),
illetve kurzoros lapozás `page.id`-val. Szűrés és rendezés az URL-ben:
`?publication.status=ACTIVE`, `?sort=-stock.sold`.

**Dátum/idő.** ISO 8601, zulu idő. A My Allegro felület helyi időt mutat,
tehát 1–2 óra eltérés lesz a felület és az API között. Egyes mezők
(`handlingTime`, `publication.duration`) ISO 8601 **időtartamot** várnak:
`P3D`, `PT24H`.

**Hibakezelés.** A hibaválasz `errors[]` tömb, mezői: `code` (gépi döntéshez),
`message` (fejlesztőnek), `userMessage` (felhasználónak mutatható),
`path` (a hibás mező útvonala), `details`, `metadata`.
A `path` miatt a validációs hibákat **soronként és mezőnként** vissza tudjuk
vezetni a CSV-re – a riportban ezt ki kell használni.

### 6.1 Hitelesítés és környezetek

- OAuth2 **Authorization Code** – felhasználói kontextus. Az ajánlat-, termékjavaslat-
  és rendelés-erőforrások mind `bearer-token-for-user` jogosultságot kérnek.
- **Device Flow** – CLI-hez ez a kényelmes: kiír egy kódot, böngészőben jóváhagyod.
- **Client credentials** (`bearer-token-for-application`) – a **kategória- és
  paraméter-erőforrásokhoz elég**. Ez a 0. fázist jelentősen egyszerűsíti:
  a felderítő futtatásához nem kell felhasználói bejelentkezés.
- Access token ~12 óra, refresh token ~3 hónap → automatikus refresh kell.

| | Éles | Sandbox |
|---|---|---|
| API | `https://api.allegro.pl/` | `https://api.allegro.pl.allegrosandbox.pl/` |
| Alkalmazásregisztráció | `https://apps.developer.allegro.pl/` | `https://apps.developer.allegro.pl.allegrosandbox.pl/` |
| OAuth | `https://allegro.pl/auth/oauth/` | `https://allegro.pl.allegrosandbox.pl/auth/oauth/` |
| Webes felület | `https://allegro.hu` | `https://allegro.hu.allegrosandbox.pl` |

A sandbox **magyar domainen is elérhető** (`allegro.xy.allegrosandbox.pl`
mintára) – a magyar piacot tesztkörnyezetben is meg tudjuk nézni.

**Sandbox-buktatók, amikre tervezni kell:**

- A feltöltött **fotókat 7 nap után törlik**. A képfeltöltő szinkronnak ezért
  újrafuttathatónak kell lennie, és a kép-URL-ekhez lejárat tartozzon.
- **Negyedévente frissítik a kategória- és paraméterlistát, és törlik az összes
  tesztajánlatot.** A kategória-térképet nem elég egyszer felvenni.
- **Ugyanazok a kéréskorlátok érvényesek**, mint élesben.
- A regisztrációnál valós formátumú (lengyel) címet kell megadni, különben az
  aktiválás elhasal. Kétfaktoros hitelesítés nem kell; ha mégis kér: `123456`.
- A tesztkörnyezet **teljesen elkülönül** az élestől: külön fiók, külön
  alkalmazásregisztráció, külön kulcsok.

### 6.2 Kéréskorlátok

**9000 kérés/perc Client ID-nként** (élesben és sandboxban egyaránt).
Túllépésnél az Allegro **egy percre blokkolja a Client ID-t**, és `429`-et ad.
Egyes erőforrásokon ezen felül alacsonyabb, erőforrás-specifikus limitek vannak,
illetve felhasználónkénti (`user.id`) **leaky bucket**: előbb lassítják a
válaszidőt, majd `429`.

A kliensbe ezért kell központi ütemező + exponenciális backoff.

### 6.3 Felderítés és listázás

| Végpont | Auth | Szerep |
|---|---|---|
| `GET /marketplaces` | user | elérhető piacok, alappiac (2.2) |
| `GET /sale/categories`, `/sale/categories/{id}` | app | kategóriafa + `options` |
| `GET /sale/categories/{id}/parameters` | app | paraméterek, kötelezőség, GTIN |
| `GET /sale/categories/{id}/product-parameters` | app | termékdefiniáló paraméterek |
| `GET /sale/matching-categories` | app | **kategória-javaslat kifejezésre** |
| `GET /sale/category-parameters-scheduled-changes` | app | **tervezett kötelezővé válás (7.6)** |
| `GET /sale/products`, `/sale/products/{id}` | user | katalógus keresés (kurzoros lapozás) |
| `POST /sale/product-proposals` | user | **saját katalógustermék javaslása** |
| `POST /sale/images` | user | képfeltöltés |
| `POST /sale/product-offers` | user | ajánlat létrehozás – `201` vagy `202` |
| `GET /sale/product-offers/{offerId}/operations/{operationId}` | user | aszinkron művelet státusz |
| `PATCH /sale/product-offers/{offerId}` | user | részleges módosítás |
| `GET /sale/offers` | user | saját ajánlatok (`?product.id.empty=true` szűrhető) |
| `GET /sale/offers/unfilled-parameters` | user | **hiányzó kötelező paraméterek (7.6)** |
| `GET /sale/offer-events` | user | ajánlat-eseményfolyam, egyeztetéshez |
| `POST /sale/offer-bulk-modification-commands` | user | tömeges ár/készlet, max. 25/kérés |
| `PUT /sale/offer-publication-commands/{commandId}` | user | **tömeges aktiválás/leállítás** |
| `GET/PATCH /sale/offers/{offerId}/translations/{lang}` | user | saját fordítás (2.2) |

**Biztonsági minta tömeges feltöltéshez.** A hivatalos példa
`"publication": {"status": "INACTIVE"}` értékkel dolgozik. Vegyük át szabályként:
**minden ajánlat inaktívan jön létre**, utána jön egy ellenőrző kör (kép rendben?
cím nem csonkult értelmetlenre? ár stimmel?), és csak azután aktiválunk tömegesen
a `offer-publication-commands` erőforrással. 90 ajánlat/minta mellett ez az
egyetlen épeszű módja annak, hogy egy hibás leképezés ne kerüljön azonnal élesbe.

A hivatalos példa payload a leképezés vázát is megerősíti:

```json
{
  "productSet": [{ "product": { "id": "…", "idType": "GTIN" } }],
  "sellingMode": { "price": { "amount": "220.85", "currency": "PLN" } },
  "stock": { "available": 10 },
  "publication": { "status": "INACTIVE" }
}
```

Nálunk az `idType: "GTIN"` ág **nem járható** (nincs EAN) – helyette saját
javasolt termék `productId`-ja kerül a `product.id` mezőbe. Lásd 7.3.

Az ajánlat további releváns mezői: `external.id` (a mi SKU-nk),
`language` (alapnyelv), `category`, `parameters`, `images`, `description`,
`delivery.handlingTime`, `sizeTable` (ruházatnál!), `taxSettings`,
`aiCoCreatedContent`, `additionalMarketplaces`.

### 6.4 Rendelés és számla

| Végpont | Szerep |
|---|---|
| `GET /order/events` | **rendelés-eseményfolyam** – inkrementális lehúzás |
| `GET /order/event-stats` | eseményfolyam-statisztika |
| `GET /order/checkout-forms`, `/{id}` | rendeléslista és részletek |
| `PUT /order/checkout-forms/{id}/fulfillment` | eladói állapot |
| `POST /order/checkout-forms/{id}/shipments` | csomagszám visszaírás |
| `GET /order/carriers`, `/order/carriers/{id}/tracking` | futárszolgálatok, követés |
| `POST /order/checkout-forms/{id}/invoices` | számla-metaadat |
| `PUT /order/checkout-forms/{id}/invoices/{invoiceId}/file` | PDF feltöltés |
| `GET /order/customer-returns` | vevői visszaküldések |
| `GET/POST /order/refund-claims` | visszatérítési igények |
| `GET/POST /payments/refunds`, `GET /payments/payment-operations` | fizetések, visszatérítés |
| `GET /billing/billing-entries`, `/billing/billing-types` | **jutalék- és díjtételek** |

**Eseményfolyam.** A `GET /order/events` kurzoros: a `from` paraméterbe az
utolsó feldolgozott **esemény ID-ja** megy, `limit` 1–1000 (alap 100).
Az események típusai:

| Típus | Jelentés |
|---|---|
| `BOUGHT` | vásárlás, kitöltött űrlap nélkül |
| `FILLED_IN` | űrlap kitöltve, de a fizetés még nincs kész – **az adat még változhat** |
| `READY_FOR_PROCESSING` | **fizetés teljesítve, feldolgozásra kész** |
| `BUYER_CANCELLED` | a vevő lemondta |
| `FULFILLMENT_STATUS_CHANGED` | eladói állapot változott |
| `AUTO_CANCELLED` | az Allegro automatikusan lemondta |

**A számlázás kizárólag `READY_FOR_PROCESSING`-re indulhat.** A `FILLED_IN`
állapotban a dokumentáció szerint az adat még változhat – ha ott számlázunk,
rossz vevőadattal állítunk ki számlát, amit utána sztornózni kell.

**Eladói állapot.** A `PUT …/fulfillment` `status` értékei: `NEW`,
`PROCESSING`, `READY_FOR_SHIPMENT`, `READY_FOR_PICKUP`, `SENT`, `PICKED_UP`,
`CANCELLED`, `SUSPENDED`, `RETURNED`. Két fontos részlet:

- A `RETURNED` **nem állítható be eladóként** – automatikusan vált.
- A hívás **revíziót használ**: elavult revízióval `409 Conflict`. Tehát
  módosítás előtt friss állapotot kell olvasni, és ütközésnél újrapróbálni.
- A `SENT` automatikusan beáll csomagszám hozzáadásakor, ha a fiókban be van
  kapcsolva a megfelelő beállítás – érdemes ezt bekapcsolni, akkor a
  `shipments` hívás elég.

**Jutalék.** A `GET /billing/billing-entries` szűrhető `offer.id`-ra és
`order.id`-ra, `type.id`-val (pl. `LIS` listázás, `SUC` sikerdíj). Tehát
**rendelésenként és ajánlatonként visszaolvasható a tényleges díj** – ezzel a
valós árrés kiszámolható, nem kell becsülni. Lásd a 10. fejezet 4. kérdését.

---

## 7. A projekt sorsa: listázás EAN nélkül

Mivel **nincs és nem is lesz EAN**, ez a fejezet dönti el, hogy a projekt
egyáltalán megvalósítható-e, és milyen terméktípusokra.

### 7.1 A variáns-API megszűnt

**2026. április 14-én az Allegro kivezette a többvariánsos ajánlat-erőforrásokat.**
A `/sale/offer-variants` végpontok azóta `404`-et adnak; a variánsokat most
**automatikusan képzi a Termékkatalógusból**.
([allegro-api#12899](https://github.com/allegro/allegro-api/issues/12899))

A kapott OpenAPI-referencia ezt megerősíti: a kategória `options` struktúrájában
már **nincs** `variantsByColorPatternAllowed` mező – csak `advertisement`,
`offersWithProductPublicationEnabled`, `productCreationEnabled` és
`sellerCanRequirePurchaseComments`.

Fontos pontosítás: az Allegrón **eddig is** minden szín×méret önálló ajánlat volt –
a kivezetett erőforrás csak *összefűzte* őket variánsválasztóvá. A darabszám tehát
nem nőtt, de **elveszítettük a csoportosítás irányítását**.

Következmény: 1 minta × 3 típus × 5 szín × 6 méret = **90 ajánlat**.
Saját javasolt katalógustermékeknél az automatikus variánscsoportosítás nagy
valószínűséggel nem áll össze, tehát a vevő külön hirdetéseket lát, nem
méretválasztót. Ezt konverziós hátrányként be kell kalkulálni.

### 7.2 Hogyan listázunk EAN nélkül – a felderítő

A kategória-erőforrás visszaad egy `options` struktúrát:

```json
{
  "id": "12", "leaf": true, "name": "Other",
  "options": {
    "advertisement": true,
    "offersWithProductPublicationEnabled": true,
    "productCreationEnabled": true,
    "sellerCanRequirePurchaseComments": true
  },
  "parent": { "id": "709" }
}
```

Nekünk a `productCreationEnabled` (javasolhatunk-e saját terméket) és az
`offersWithProductPublicationEnabled` (publikálható-e termékhez kötött ajánlat)
a döntő. A `GET /sale/categories/{id}/parameters` pedig megadja a paraméterek
kötelezőségét és a GTIN-jelölést.

Egy további bíztató jel: a dokumentáció szűrési példája
`GET /sale/offers?product.id.empty=true` – tehát **létezik katalógustermékhez
nem kötött ajánlat**, és az API külön szűrőt ad rájuk. Ez nem garancia
(kategóriafüggő marad), de azt jelzi, hogy nem elvi lehetetlenség.

**A 0. fázis eszköze, a kategória-felderítő:**

```
allegro categories:scan --root <categoryId> --lang hu-HU
```

A `GET /sale/matching-categories` segít a kiindulásban: kifejezésre
(„póló", „bögre") kategóriát javasol, nem kell a teljes fát végigjárni.
Mivel ezek `bearer-token-for-application` jogosultsággal is mennek,
**a felderítéshez nem kell felhasználói bejelentkezés**.

Kimenet minden levélkategóriára:

| Kategória | GTIN kötelező? | `productCreationEnabled` | Verdikt |
|---|---|---|---|
| … | nem | igen | ✅ listázható EAN nélkül |
| … | igen | – | ❌ számunkra zárt |

Ez a tábla a **go/no-go döntés**.

Az ismert hibaüzenetek, amikbe rossz kategóriánál belefutunk:
`MatchingProductNotFoundException`, illetve „ebben a kategóriában az ajánlatot
a Katalógushoz kell kötni"
([#8450](https://github.com/allegro/allegro-api/issues/8450),
[#10101](https://github.com/allegro/allegro-api/issues/10101)).

### 7.3 A listázási út EAN nélkül

`POST /sale/product-proposals` kötelező mezői a referencia szerint:
`name` (**max. 75 karakter**), `category`, `images` (legalább egy),
`parameters`, `language`. Opcionális: `description` (max. 40 000 bájt),
`productSafety`, `aiCoCreatedContent`, `hasProtectedBrand`.
A publikációs állapot `PROPOSED`.

Folyamat:

1. `POST /sale/product-proposals` – saját katalógustermék javaslása
   (GTIN paraméter nélkül, ahol nem kötelező).
2. **`409 Conflict` = a termék már létezik**, és a válasz `Location` fejléce
   megadja a meglévő termék URL-jét. Ez ingyen idempotencia: újrafuttatásnál
   a `409`-ből kiolvassuk a `productId`-t, nem hozunk létre duplikátumot.
3. A `productId` az állapottárba.
4. `POST /sale/product-offers` – az ajánlat a saját termékre hivatkozik,
   `publication.status: INACTIVE`.
5. `202` esetén művelet-pollozás a végleges `offerId`-ért.

### 7.4 Kapacitáskorlát: havi 20 000 új termék

A referencia kimondja: **havonta legfeljebb 20 000 új terméket lehet a
Katalógusba felvinni** (`product-proposals`).

Ez a 7.1 szorzóval együtt kemény tervezési korlát:

| Minta/hó | Variáns/minta | Új katalógustermék/hó | Belefér? |
|---|---|---|---|
| 50 | 90 | 4 500 | ✅ |
| 100 | 90 | 9 000 | ✅ |
| 222 | 90 | 19 980 | ✅ (határon) |
| 300 | 90 | 27 000 | ❌ |

Tehát a **variánsskála szűkítése nem kozmetika, hanem kapacitáskérdés**.
Ha egy típusnál 6 helyett 4 méretet és 5 helyett 3 színt viszünk,
a variánsszám 90-ről 36-ra esik, és ugyanaz a keret 555 mintát bír el.

Ezt a számítást **a kínálattervezés elején** kell elvégezni, nem utólag.

### 7.5 Címszabály – szigorúbb, mint hittük

Az ajánlat `name` mezője: **12–75 karakter, szóközökkel együtt, és legalább
3 szóból kell állnia**. A termékjavaslat `name` mezője: max. 75 karakter.

A mai Temu-név (`terméknév + típus + toldalék`) a felső határt simán túllépi,
és csonkolásnál könnyen 3 szó alá eshet vagy értelmetlenné válhat.

Ezért kell egy dedikált `TitleBuilder`, ami:

- prioritási sorrendben épít: minta neve → típus → szín → méret,
- **szóhatáron** csonkol, nem karakter közepén,
- garantálja a 12 karakteres alsó és a 3 szavas minimumot,
- ütközésnél (két variáns azonos címet kapna) determinisztikusan feloldja.

Ez a modul kapjon egységteszteket – itt a csendes hiba drága.

### 7.6 GTIN-őrszem – egzisztenciális kockázat figyelése

Mivel a vállalkozás **soha nem fog EAN-t használni**, az a nap, amikor a
célkategóriánkban a GTIN kötelezővé válik, leállítja a feltöltést.
Az API viszont ad rá **előrejelzést**:

```
GET /sale/category-parameters-scheduled-changes?type=REQUIREMENT_CHANGE
    &scheduledFor.lte=<+3 hónap>          # Accept-Language: pl-PL !
GET /sale/offers/unfilled-parameters?parameterType=REQUIREMENT_PLANNED
```

Az első megmondja, mely paraméter válik kötelezővé egy kategóriában
(legfeljebb 3 hónapra előre), a második azt, hogy a **meglévő ajánlatainkból**
melyikből hiányzik kötelező vagy hamarosan kötelezővé váló paraméter.

**Javaslat: heti cron, ami mindkettőt lefuttatja a használt kategóriákra,
és e-mailt küld, ha GTIN-t érintő változást talál.** Ez néhány óra munka,
és három hónap reakcióidőt ad egy olyan eseményre, ami különben egyik napról
a másikra állítaná le az értékesítést.

---

## 8. Számlázás (szamlazz.hu Számla Agent)

A szamlazz.hu Számla Agent HTTP POST-tal, XML-lel működik: a rendszer egy
XML fájlt küld multipart POST-ban, ami tartalmazza a vezérlő paramétereket
és a számla adatait; számlánként egy XML.
([docs.szamlazz.hu/agent](https://docs.szamlazz.hu/agent))

Magyar-only értékesítésnél ez a modul **jelentősen egyszerűbb**: fix HUF,
fix 27% ÁFA, magyar vevő, nincs OSS-logika.

Folyamat:

1. `OrderSync` lehúzza a `READY_FOR_PROCESSING` eseményt (`GET /order/events`).
2. Leképezzük a szamlazz.hu számla-XML-re: vevő adatai, tételek, 27% ÁFA, HUF.
3. Számla Agent hívás → válaszban számlaszám + PDF.
4. `POST /order/checkout-forms/{id}/invoices` – **csak metaadat**:
   ```json
   { "file": { "name": "invoice.pdf" }, "invoiceNumber": "2026/00123" }
   ```
   Válasz `201`: `{ "id": "56ae349d-…" }` – ez az `invoiceId`.
5. `PUT /order/checkout-forms/{id}/invoices/{invoiceId}/file` –
   `Content-Type: application/pdf`, bináris törzs.
6. Számlaszám + Allegro `invoiceId` rögzítése az állapottárban.

### 8.1 Három megkötés, ami a ciklus alakját meghatározza

**A metaadat és a fájl párban megy, sorosan.** A `POST …/invoices` `429`-cel
válaszol ezzel az üzenettel: *„You're trying to add another metadata too fast.
Upload a file to previously added metadata or wait a few seconds before adding
next metadata."* Tehát **nem szabad** előbb legyártani az összes metaadatot,
majd utána feltölteni a fájlokat. A helyes ciklus rendelésenként:
metaadat → azonnal PDF → következő rendelés.

**Max. 3 MB a PDF.** Túllépésnél `413`. A szamlazz.hu PDF-je jellemzően jóval
kisebb, de a feltöltés előtt ellenőrizni kell, és ha valamiért nagyobb
(pl. sok tétel), akkor jelezni.

**A `409`-ek ingyen idempotenciát adnak.** A `POST …/invoices` `409`-et ad, ha
a rendelésnek **már van eladói számlája**; a `PUT …/file` `409`-et, ha a
számlához **már van feltöltött fájl**. Újrafuttatásnál tehát nem duplázunk,
és a `409` nem hiba, hanem „ez már kész" – így kell kezelni.

Ezen felül az állapottár `orders` táblája is őrzi, hogy kiállítottuk-e már a
számlát, hogy a szamlazz.hu oldalán se duplázzunk.

Kezelendő hibaágak: `422` – a rendelés nem enged számlát, a fizetés
elutasított, vagy **az előzőleg feltöltött fájl még vírusellenőrzés alatt van**.
Ez utóbbi átmeneti, tehát újrapróbálandó, nem végleges hiba.

> **Megjegyzés a pontosságról:** a `docs.szamlazz.hu` domaint a fejlesztői
> környezet proxyja blokkolja (403), így a szamlazz.hu XML mezőneveit
> (`szamlaagentkulcs`, `action-xmlagentxmlfile` stb.) **a hivatalos
> dokumentációval kell egyeztetni az implementáció előtt**.

---

## 9. Fázisok

| Fázis | Tartalom | Eredmény |
|---|---|---|
| **0. Felderítés** ⚠️ | Client-credentials token + `categories:scan` + `matching-categories`. `GET /marketplaces` az alappiac tisztázására (2.2). | **Go/No-go döntés** |
| **1. Egy ajánlat kézzel** ⚠️ | Sandboxban **egyetlen** POD-ajánlat végigvitele: `product-proposals` → kép → `product-offers` → aktiválás. | Bizonyíték, hogy EAN nélkül megy |
| **2. Alapkliens** | User-Agent, token store, rate limit, Trace-Id naplózás, aszinkron pollozás, SQLite. | `allegro auth`, `allegro whoami` |
| **3. Export + import** | Plugin Allegro-CSV export; CLI beolvasás, validálás, `TitleBuilder`, `--dry-run`. | Ellenőrizhető payloadok |
| **4. Feltöltés** | Kép- és termékjavaslat-szinkron (409-kezeléssel), ajánlat inaktívan, ellenőrző kör, tömeges aktiválás. | Élő ajánlatok sandboxban |
| **5. Ár/készlet + őrszem** | `offer-bulk-modification-commands` 25-ös kötegekben; GTIN-őrszem cron (7.6). | Napi szinkron, korai riasztás |
| **6. Rendelés + számla** | `GET /order/events`, szamlazz.hu, számla-visszatöltés. | Zárt kör |
| **7. Éles indulás** | Éles kulcsok, **szűk kínálattal** indulás, monitorozás. | Élesben |

A **0. és 1. fázis kritikus**, és együtt is csak néhány nap. Amíg nem tudjuk,
hogy EAN nélkül feltölthető-e egy póló a választott kategóriába, **semmilyen
keretrendszert nem érdemes írni**. Ez a terv legfontosabb üzenete.

---

## 10. Nyitott kérdések

Megválaszolva: Allegro-fiók ✔ megvan (`fmshirt`) · EAN ✘ nincs és nem lesz ·
piac ✔ csak HU.

Ami még nyitott:

1. **Hol legyen a kód?** Ebben a repóban egy `allegro-sync/` mappában,
   vagy külön repóban? (Javaslat: külön repó, mert nem WordPress-kód.)
2. **Melyik terméktípusokkal indulunk, és milyen szín/méret skálával?**
   A 7.4 kapacitásszámítás miatt ez nem ízlés kérdése.
3. **Szállítás:** ki szállít belföldön, milyen díjszabással?
   Allegro Shipping / DPD, vagy saját futár?
4. **Árazás:** a HUF-ár honnan jön – a WooCommerce ár + szorzó, vagy külön
   Allegro-árlista? A jutalékot **nem kell becsülni**: a
   `GET /billing/billing-entries` rendelésenként visszaadja a tényleges
   díjtételeket, tehát az induló árazás után a valós árrés kimérhető, és
   a szorzó ez alapján hangolható. Az induló szorzóhoz viszont kell egy
   döntés – a 180 napos 0% jutalékos időszak ezt torzítja, arra figyelni kell.
5. **szamlazz.hu:** a forme.hu ma is ezt használja? Van Agent kulcs?
6. **Elállási jog:** a kínálat előre gyártott mintás termék (elállás jár),
   vagy vevő által személyre szabott (nem jár)? Lásd 2.3.
7. **AI-tartalom:** a leírások mekkora része készül AI-val? Az
   `aiCoCreatedContent` mezőt ennek megfelelően kell kitölteni (2.4).

**Dokumentáció:** a teljes, 473 oldalas OpenAPI-referencia (279 végpont) a
`giftformekft-tech/allegro-sync` repóban van. Ezzel a 6., 7. és 8. fejezet
végpontjai és mezői ellenőrzöttek. Egyedül a **szamlazz.hu** oldal maradt
nyitva – a `docs.szamlazz.hu` domaint a fejlesztői környezet proxyja
blokkolja (403), így a Számla Agent XML mezőneveit
(`szamlaagentkulcs`, `action-xmlagentxmlfile` stb.) nem tudtam ellenőrizni.
Ha a szamlazz.hu Agent dokumentációját is felteszed a repóba, a 8. fejezet
is ugyanilyen pontos lesz.

---

## 11. Amit szándékosan kihagytam az első körből

- Allegro Ads / promóciós csomagok (`offer-promotion-packages`, `promo-options`)
- Vevői üzenetek (`/messaging`) kezelése
- Visszaküldés és reklamáció (`/order/refund-claims`) automatizálása
- One Fulfillment (Allegro raktár) – POD-nál nem értelmes
- Automatikus árverseny-követés
- Ajánlat-mellékletek (`offer-attachments`), méretjelző kompatibilitási listák

Ezek mind API-ból elérhetők, de csak akkor éri meg, ha az alapfolyamat
már stabilan megy.
