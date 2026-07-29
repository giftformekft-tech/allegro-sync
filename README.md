# allegro-sync

Allegro-integráció a [forme.hu](https://forme.hu) egyedi mintás ajándéktárgy-webshophoz:
termékfeltöltés CSV/XLSX-ből, rendelésszinkron és szamlazz.hu számlázás.

> **Státusz: tervezés.** Kód még nincs. A fejlesztés a terv 0. fázisával kezdődik,
> ami egy go/no-go döntés – lásd alább.

## Mit csinál majd

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

## Következő lépés

A terv **0. fázisa**: kategória-felderítő, ami a célkategóriákra kiírja, hogy
a GTIN kötelező-e és javasolható-e saját termék. Amíg ez a tábla nincs meg,
keretrendszert írni kockázat.

Részletek: [`docs/allegro-integracio-terv.md`](docs/allegro-integracio-terv.md)
7.2 és 9. fejezet.
