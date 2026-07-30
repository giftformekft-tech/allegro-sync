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
- **Feltöltési sablonok:** a kategória és a fix Allegro-paraméterek névvel
  menthetők, frissíthetők és törölhetők. Paraméterenként beállítható,
  hogy fix sablonérték legyen vagy az aktuális termékből frissüljön.
  A készlet ugyanezzel a két móddal használható.
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
7. Válaszd ki a fiókban elmentett szállítási árlistát és a feladási időt.
   Előrendelésnél a várható feladási dátum is kötelező.
8. Válaszd ki a gyártó GPSR-rekordját, szükség esetén az EU-s felelős személyt,
   és add meg a biztonsági információt. Ezek különálló adatok, nem a márka
   kategóriaparaméterének másolatai.
9. Készíts JSON-előnézetet. A feltöltéshez írd be pontosan: `FELTÖLTÉS`.

## Sablonok használata

1. Válassz kategóriát és terméket, majd töltsd ki a kötelező mezőket.
2. Hagyd bejelölve a **Termékből frissül** opciót a szín, méret, márka,
   anyag vagy gyártói cikkszám mellett, ha az importált termék adata legyen az alap.
3. Vedd ki a jelölést azoknál a mezőknél, amelyek minden ilyen pólónál
   azonosak, és válaszd ki vagy írd be a mentendő fix értéket.
4. A készletnél is választhatsz termékből frissülő vagy fix darabszámot.
   A szállítási árlista, feladási idő, gyártó, felelős személy és biztonsági
   szöveg fix sablonadatként menthető.
5. Adj nevet a sablonnak, majd kattints a **Sablon mentése** gombra. Azonos
   névvel mentve a meglévő sablon frissül.

A termék neve, leírása, SKU-ja, képe és ára nincs a sablonba befagyasztva:
ezeket az alkalmazás mindig az aktuálisan kiválasztott termékből veszi.

A létrehozott ajánlat publikációs állapota minden esetben `INACTIVE`; ez a
folyamat nem aktivál és nem kezd automatikus értékesítésbe.

Az EAN/GTIN mező feltételes lehet. A program az API `requiredIf` szabályát
folyamatosan újraszámolja a kiválasztott állapot és márka alapján. Az `új`
állapot önmagában nem teszi kötelezővé az EAN-t: ha például a márka
`márkanév nélkül`, a mező opcionális marad és kimarad a feltöltésből.

## Ami még nincs bekötve

- külön képfeltöltési gyorsítótár és önálló `product-proposals` folyamat;
- ajánlat aktiválása és tömeges feltöltés;
- ár- és készletszinkron;
- rendelési eseményfolyam;
- szamlazz.hu XML számlakiállítás és PDF-visszatöltés.

Ezekhez az API-alapok a régi PHP-magban referenciaként rendelkezésre állnak.
Az alkalmazás nem tiltja le az éles tesztfeltöltést, de első alkalommal
javasolt sandboxban ellenőrizni a kiválasztott kategória GTIN-követelményét.
