# allegro-sync

Modern, helyben futó marketplace-kezelő a [forme.hu](https://forme.hu) egyedi
mintás ajándéktárgy-webshophoz. Az Allegro működő modulja mellé megkezdődött a
Temu Open Platform integráció is, ugyanabban a kapcsolható felületben.

> **Státusz: működő első alkalmazásverzió.** A kattintásos Python-felület,
> a CSV-előnézet és -validálás, a helyi SQLite állapottár, a terméklista,
> az Allegro OAuth, az élő kategória/GTIN-felderítés és az egytermékes inaktív
> tesztajánlat létrehozása, a szállítási és GPSR-adatok kezelése, valamint a
> menthető feltöltési sablonok elkészültek.
> A rendeléslista, a maszkolt vevői e-mail átvétele, a Számlázz.hu
> számlakiállítás és a PDF Allegro-rendeléshez feltöltése is elkészült.
> A Számlázz.hu közvetlen e-mailje választható biztonsági másodpéldány;
> az elsődleges kézbesítési út mindig az Allegro.

## Gyors indítás

Python 3.11 vagy újabb szükséges, külső csomagot nem kell telepíteni.

```powershell
python run.py
```

Windows alatt a `start-allegro-sync.bat` fájlra duplán kattintva is indul.
Az alkalmazás megnyitja a böngészőt a `http://127.0.0.1:8765` címen. Első
indítás után:

Az oldal tetején az **Allegro / Temu** választóval lehet platformot váltani. A
Temu első fázisában a Beállítások oldalon menthető az EU API-végpont, az App
Key, az App Secret és az Access Token, a Kapcsolatok oldalon pedig valódi
Open Platform kéréssel tesztelhető a hozzáférés. A titkos értékeket a felület
nem olvassa vissza.

A **Temu feltöltés** oldal a Product Publishing API V3-at használja. Egy
kiválasztott típus–szín sor minden importált mérete külön SKU-ként kerül a
termékbe. A V3 a WooCommerce saját variánsértékeit normalizálja, a kategóriát
pedig a megadott külső kategórianévből ajánlja. A felület ellenőrzi a kötelező
ár-, készlet-, csomag- és képmezőket, megmutatja a pontos JSON-kérést, majd a
`FELTÖLTÉS` megerősítéssel valóban létrehozza a terméket. A képek közvetlen,
nyilvános HTTPS URL-ként kerülnek át; külön képfeltöltési lépés nincs.
Részletek: [`docs/temu-v3-product-upload.md`](docs/temu-v3-product-upload.md).

A WooCommerce-bővítményben ehhez külön **Temu API Export** menüpont tartozik.
Ez nem az Allegro export és nem a régi, kézi Temu CSV/XLSX export. A Temu API
fájl `marketplace=temu_api_v3` jelölést és `TEMU-` előtagú SKU-kat használ;
az alkalmazás platformonként szűri az importált termékeket, így a két
marketplace adatai nem írják felül és nem ajánlják fel egymást.

1. **Beállítások:** add meg a sandbox Client ID-t, Client Secretet és a
   szabályos User-Agentet.
2. **Kapcsolatok:** teszteld az alkalmazást, majd csatlakoztasd az eladói fiókot.
3. **Importálás:** húzd be az Allegro CSV-t, ellenőrizd a hibákat, majd mentsd
   a megfelelő sorokat.
4. **Tesztfeltöltés:** keress kategóriát, ellenőrizd a GTIN-verdiktet, töltsd
   ki a kötelező Allegro-paramétereket, majd készíts egy inaktív ajánlatot.
   A program a csatlakoztatott eladói fiókból olvassa ki az alappiacot és
   annak pénznemét; nem HUF-os fióknál külön tesztárat kér.
5. **Sablonok:** mentsd el a kategóriát, a fix paramétereket és igény
   szerint a fix készletet. A termékhez kötött mezők minden kiválasztott
   pólónál automatikusan frissülnek.

Az importált, kiterítve mért pólóhossz és hónalj alatti szélesség a leírás
mellett automatikusan bekerül az Allegro megfelelő „További paraméterek”
mezőibe is. A program a férfi/női és gyerek pólók eltérő paraméter-ID-jét
kezeli.

A pólók „Fő minta” paramétere alapból férfi/női terméknél „mintás
(nyomatos)”, gyerekterméknél „nyomott mintás”. A „Nyomtatási terület”
alapértéke „elülső”; mindegyik érték átírható és sablonba menthető.

Ha a kategória tartalmaz `Modell` termékparamétert, a program a Woo közös
terméknevéből, az olvasható típusnévből és a színből képezi az értékét. A
méretet kihagyja, így egy szín teljes méretsora azonos modellt kap; a gyártói
kód ettől függetlenül továbbra is a méretenkénti SKU.

### Temu rendelés és számlázás

A Temu platformra váltva a **Rendelések** képernyő az EU Open Platform
`bg.order.list.v2.get` adatait mutatja. A „Számlaadatok ellenőrzése” előbb
lekéri a Temu hivatalos számlarészleteit és a virtuális vevői e-mailt, majd
külön mutatja a vevőnek és – ha a Temu ilyet ad vissza – a platformnak szóló
bizonylatot. A terméktétel neve a Temu `goodsInfoList[].description` mezője;
a kupon platform által térített része külön, egyértelmű megnevezést kap.

A kiállítás előtt kötelező beállítani egy nyilvános HTTPS alapcímet. A Temu
erről a futó alkalmazásról tölti le a tokennel védett PDF-et, majd a program
a `temu.pay.tax.merchant.upload.invoice` végponttal a rendeléshez kapcsolja.
A platform nevét és nyers címét a Temu API adja. Az alkalmazás az egyértelmű
címrészeket felbontja, az eredeti címet megmutatja az előnézetben, és az adott
API-címet egyszer jóvá kell hagyni; címváltozáskor újból ellenőrzést kér.
A folyamat külön `temu_order_invoices` táblát és külön Temu számlaelőtagot
használ, ezért nem ütközik sem az Allegro számlázásával, sem a régi Temu
CSV/XLSX exporttal. Jóváíró bizonylat és nem HUF-os rendelés csak külön
ellenőrzés után lesz engedélyezhető.

### Temu rendelés feladása Express One-nal

A **Rendelések** képernyőn az „Express One feladás” megmutatja a Temutól
lekért címzettet és a csomag tömegét. A `FELADÁS` megerősítés után a program
az Express One `parcel/create_labels` végpontján létrehozza az A4 PDF-címkét,
elmenti a csomagszámot, majd a Temu `bg.logistics.shipment.confirm`
végpontján az egész rendelést egy csomagként feladottnak jelöli.

A Temuhoz tartozó Express One fuvarozóazonosítót alapból a
`bg.logistics.companies.get` régiós listából keresi ki. Ha a fiók más néven
adja vissza a szolgáltatót, a carrier ID kézzel is rögzíthető. A címke a
rendeléssorból megnyitható, a pillanatnyi nyomkövetés pedig közvetlenül az
Express One API-ból kérhető le. Ha a címke létrejött, de a Temu visszaírása
hibázik, az újrapróbálás a mentett csomagszámot használja, így nem keletkezik
második Express One csomag.

Tömeges munkához a rendeléstábla sorai kijelölhetők. A **Kijelöltek
feladása** rendelésenként biztonságosan létrehozza és visszaírja a csomagot,
majd siker/hiba bontást mutat; egy hibás rendelés nem állítja le a többit.
A már címkével rendelkező kijelölt sorokhoz a **Kijelölt címkék nyomtatása**
az Express One `parcel_label/get_selected_parcel_labels` végpontjáról egyetlen
közös A4 PDF-et nyit meg.

Automata tesztek:

```powershell
python -m unittest discover -s tests_python -v
```

Részletes használat: [`docs/kezelo-felulet.md`](docs/kezelo-felulet.md).

## A teljes célfolyamat

A forme.hu WooCommerce-boltja (a `mockup-generator` plugin) exportál egy CSV-t
a termékvariánsokról. Ez a program beolvassa, feltölti az Allegróra, majd
kétirányban szinkronban tartja:

```
forme.hu CSV ─► képfeltöltés ─► katalógustermék ─► ajánlat (inaktív)
                                                        │
                                                   ellenőrzés
                                                        │
                                                    aktiválás
                                                        │
              szamlazz.hu ◄─── rendelés ◄───────────────┘
                    │
                    └─► számla PDF vissza az Allegróra
```

## Dokumentáció

| Fájl | Tartalom |
|---|---|
| [`docs/allegro-integracio-terv.md`](docs/allegro-integracio-terv.md) | **A teljes fejlesztési terv** – architektúra, API-végpontok, fázisok, kockázatok |
| [`docs/kezelo-felulet.md`](docs/kezelo-felulet.md) | A kattintásos alkalmazás telepítése, használata és jelenlegi határai |
| [`docs/temu-v3-product-upload.md`](docs/temu-v3-product-upload.md) | A Temu V3 termékfeltöltés mezői, képei, biztonsága és hivatalos forrásai |
| `Allegro Developer Portal - baza wiedzy o Allegro REST API.pdf` | A hivatalos OpenAPI-referencia (473 oldal, 279 végpont) |

## Rögzített keretek

- **Csak a magyar piac** (allegro.hu), HUF, 27% ÁFA, nincs OSS.
- **Nincs EAN/GTIN, és nem is lesz.** Ez a projekt központi megkötése.
- Allegro eladói fiók és API-alkalmazás megvan (`fmshirt`).

## A két kritikus kockázat

**1. Listázás EAN nélkül.** Az Allegro egyre több kategóriában kötelezi az
ajánlat katalógushoz kötését, és a GTIN-t alapparaméterként kezeli. EAN nélkül
saját katalógusterméket kell javasolni (`POST /sale/product-proposals`), ami
csak olyan kategóriában megy, ahol a `productCreationEnabled` igaz és a GTIN
nem kötelező. A GTIN kötelezettsége feltételes is lehet: a pólókategóriákban
például az állapot és a márka együtt dönthet róla. A program az Allegro
`requiredIf` szabályait is kiértékeli.

**2. Darabszám-robbanás.** A többvariánsos ajánlat-erőforrásokat az Allegro
2026 áprilisában kivezette, a variánsokat a katalógusból képzi. Minden
szín×méret önálló ajánlat: 1 minta × 3 típus × 5 szín × 6 méret = **90 ajánlat**.
A termékjavaslat havi 20 000 új katalógustermékre van maximálva, tehát a
szín- és méretskála szűkítése kapacitáskérdés, nem ízlés.

## Következő fejlesztési lépés

A kategória-felderítő és az egytermékes, inaktív tesztfeltöltés elkészült.
A következő modul a tömeges feltöltés, majd az ár- és készletszinkron.
A felület nem tiltja le az éles környezetet, de az első kategória- és
GTIN-próbát érdemes sandbox fiókkal elvégezni.

Tesztelés lépésről lépésre: [`docs/teszteles.md`](docs/teszteles.md)

Részletek: [`docs/allegro-integracio-terv.md`](docs/allegro-integracio-terv.md)
7.2 és 9. fejezet.
