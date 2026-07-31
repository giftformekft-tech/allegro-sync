# Temu Product Publishing API V3

Az alkalmazás termékfeltöltési útvonala a hivatalos `temu.local.goods.v3.add`
metódust használja. A korábbi WooCommerce Temu CSV/XLSX export ettől független,
változatlan biztonsági megoldás marad.

A WooCommerce-bővítmény három külön exportútvonalat tart fenn:

- a meglévő Allegro exportot csak az Allegro-folyamat olvassa;
- a meglévő Temu CSV/XLSX továbbra is kézi tartalék;
- az új Temu API Export kizárólag ehhez a V3 modulhoz készít CSV-t.

Az API-fájl `marketplace=temu_api_v3` jelölést, külön Temu-kategórianevet és
`TEMU-` előtagú termék/SKU azonosítókat tartalmaz. Emiatt egy Allegro-import
nem tud Temu-termékként megjelenni, és a Temu-import sem írja felül az Allegro
SKU-kat.

Hivatalos források:

- [Product Publishing API V3 Integration Guide](https://partner.temu.com/documentation?menu_code=fb16b05f7a904765aac4af3a24b87d4a&sub_menu_code=d2be183c4ebe4f06b232792f0ee53310)
- [`temu.local.goods.v3.add` végpont](https://partner.temu.com/documentation?menu_code=fb16b05f7a904765aac4af3a24b87d4a&sub_menu_code=419748d505a3483f8d210d978cb813f8)
- [`bg.local.goods.publish.status.get` végpont](https://partner.temu.com/documentation?menu_code=fb16b05f7a904765aac4af3a24b87d4a&sub_menu_code=db14c29a74744247828e8ebc69443dfe)

## Mit küld a program?

- Egy WooCommerce termékcsaládot egy Temu termékként.
- A kijelölt típus–szín sorok minden méretét külön SKU-ként, legfeljebb 500 SKU-t.
- Külső termék- és SKU-azonosítót, terméknevet, kategória-elnevezést és leírást.
- SKU-nként árat, pénznemet, készletet, csomagsúlyt és csomagméreteket.
- Típus, szín és méret variációt. A V3 a külső elnevezéseket normalizálja.
- Márka, anyag, származási ország és gyártó attribútumot, ha rendelkezésre áll.
- Közös galériaképet és SKU-nként variánsképet.

## Képek

A Temu V3 közvetlen, nyilvánosan elérhető HTTPS-kép URL-eket fogad. A Temu
letölti és saját rendszerében tárolja ezeket, ezért külön képfeltöltési API nem
szükséges. SKU-nként legalább egy érvényes variánskép kötelező. A Woo-ban
beállítható közös kép a termék galériájának elejére kerül.

## Biztonság és állapot

Az előnézet csak helyben validál és payloadot készít. A tényleges feltöltéshez a
`FELTÖLTÉS` megerősítés szükséges. Minden próbálkozás bekerül a helyi naplóba. A
visszakapott `goodsId` alapján a felület a publikálási állapotot is le tudja kérni.
