# Allegro Sync kezelőfelület

Az alkalmazás egy helyi, böngészőből használható adminfelület. A szerver csak
a saját gépen, a `127.0.0.1` címen figyel; nem teszi ki az API-kulcsokat a
hálózatra. Külső Python-csomagot nem igényel.

## Indítás

Python 3.11 vagy újabb verzióval:

```powershell
python run.py
```

Másik porton vagy automatikus böngészőnyitás nélkül:

```powershell
python run.py --port 9000 --no-browser
```

Windows alatt a gyökérben lévő `start-allegro-sync.bat` is használható.

## Oldalak

- **Áttekintés:** termék-, készlet- és kapcsolati állapot, indulási ellenőrzőlista,
  legutóbbi aktivitások.
- **Termékek:** az importált termékváltozatok kereshető listája.
- **Importálás:** CSV behúzása, helyi ellenőrzés, hibalista és a megfelelő sorok
  mentése. A hibás sorok nem kerülnek a termékek közé.
- **Tesztfeltöltés:** élő Allegro kategóriakeresés, kategória- és GTIN-verdikt,
  kötelező paraméterek dinamikus űrlapja, JSON-előnézet, majd egyetlen INACTIVE
  ajánlat létrehozása. A gomb nincs környezet alapján letiltva; minden esetben
  `FELTÖLTÉS` szöveges megerősítést kér, éles módban pedig külön párbeszédet is.
- **Kapcsolatok:** Allegro alkalmazás-token tesztelése és device-flow eladói
  bejelentkezés.
- **Beállítások:** sandbox/éles környezet, Allegro-kulcsok, User-Agent és a
  szamlazz.hu előkészített mezői.
- **Rendelések:** jelenleg tájékoztató képernyő; a szinkron még nincs bekötve.

## Adattárolás és titkok

- A beállítások a `.env` fájlban vannak. Ez a Gitből ki van zárva.
- Az API soha nem küldi vissza a böngészőnek az elmentett titkos kulcsot, csak
  azt jelzi, hogy van-e beállítva.
- A termékek, import-előnézetek, tokenek és aktivitások a
  `var/app-state-sandbox.sqlite`, illetve `var/app-state-production.sqlite`
  fájlba kerülnek. A két környezet állapota szándékosan különálló.

## CSV-szerződés

Kötelező oszlopok:

```text
sku, name, type, color, size, price_huf, stock, image_url
```

Ajánlott további oszlopok:

```text
parent_sku, type_label, description, weight_g, brand, material, ai_content
```

A program UTF-8 BOM-os fájlt, pontosvesszős és vesszős elválasztást, valamint
magyar és angol fejlécneveket is kezel. Az előnézet ellenőrzi többek között az
SKU-ütközést, a pozitív árat és készletet, a kép URL-jét, a leírást, valamint
az Allegro 12-75 karakteres és legalább háromszavas címszabályát.

## A tesztfeltöltés menete

1. Csatlakoztasd az eladói fiókot a **Kapcsolatok** oldalon.
2. Importálj legalább egy megfelelő termékváltozatot.
3. A **Tesztfeltöltés** oldalon keress rá például arra, hogy `pamut póló`.
4. Válassz egy kategóriát, majd ellenőrizd a négy feltételt: levélkategória,
   saját termék létrehozása, termékajánlat engedélyezése és nem kötelező GTIN.
5. Válaszd ki a terméket és töltsd ki az Allegro által kötelezőnek jelölt
   paramétereket. A program megpróbálja előválasztani a márka, szín, méret,
   anyag és gyártói cikkszám értékét.
6. Ellenőrizd az Allegro fiókból automatikusan beolvasott alappiacot és
   pénznemet. HUF esetén az importált ár automatikusan megjelenik; más
   pénznemnél adj meg külön tesztárat.
7. Készíts JSON-előnézetet. A feltöltéshez írd be pontosan: `FELTÖLTÉS`.

A létrehozott ajánlat publikációs állapota minden esetben `INACTIVE`; ez a
folyamat nem aktivál és nem kezd automatikus értékesítésbe.

## Ami még nincs bekötve

- külön képfeltöltési gyorsítótár és önálló `product-proposals` folyamat;
- ajánlat aktiválása és tömeges feltöltés;
- ár- és készletszinkron;
- rendelési eseményfolyam;
- szamlazz.hu XML számlakiállítás és PDF-visszatöltés.

Ezekhez az API-alapok a régi PHP-magban referenciaként rendelkezésre állnak.
Az alkalmazás nem tiltja le az éles tesztfeltöltést, de első alkalommal
javasolt sandboxban ellenőrizni a kiválasztott kategória GTIN-követelményét.
