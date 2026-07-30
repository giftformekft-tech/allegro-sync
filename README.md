# allegro-sync

Modern, helyben futó Allegro-kezelő a [forme.hu](https://forme.hu) egyedi mintás
ajándéktárgy-webshophoz: termékimport, Allegro API-kapcsolat, később
rendelésszinkron és szamlazz.hu számlázás.

> **Státusz: működő első alkalmazásverzió.** A kattintásos Python-felület,
> a CSV-előnézet és -validálás, a helyi SQLite állapottár, a terméklista,
> az Allegro OAuth, az élő kategória/GTIN-felderítés és az egytermékes inaktív
> tesztajánlat létrehozása elkészült. A tömeges feltöltés, rendelés- és
> számlaszinkron következő ütem.

## Gyors indítás

Python 3.11 vagy újabb szükséges, külső csomagot nem kell telepíteni.

```powershell
python run.py
```

Windows alatt a `start-allegro-sync.bat` fájlra duplán kattintva is indul.
Az alkalmazás megnyitja a böngészőt a `http://127.0.0.1:8765` címen. Első
indítás után:

1. **Beállítások:** add meg a sandbox Client ID-t, Client Secretet és a
   szabályos User-Agentet.
2. **Kapcsolatok:** teszteld az alkalmazást, majd csatlakoztasd az eladói fiókot.
3. **Importálás:** húzd be az Allegro CSV-t, ellenőrizd a hibákat, majd mentsd
   a megfelelő sorokat.
4. **Tesztfeltöltés:** keress kategóriát, ellenőrizd a GTIN-verdiktet, töltsd
   ki a kötelező Allegro-paramétereket, majd készíts egy inaktív ajánlatot.
   A program a csatlakoztatott eladói fiókból olvassa ki az alappiacot és
   annak pénznemét; nem HUF-os fióknál külön tesztárat kér.

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
nem kötelező. **Ezt kell először kideríteni** – ez a terv 0. fázisa.

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
