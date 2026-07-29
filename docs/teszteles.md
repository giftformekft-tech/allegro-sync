# Hogyan teszteld

Négy szint, növekvő sorrendben. Az első kettőhöz **nem kell semmilyen
Allegro-hozzáférés** – érdemes azzal kezdeni.

## Mire van szükség

PHP 8.1 vagy újabb, `curl`, `pdo_sqlite`, `mbstring` kiterjesztéssel.
Ellenőrzés:

```bash
php -v
php -m | grep -E '^(curl|pdo_sqlite|mbstring)$'
```

Futtatható a webszerveren SSH-n keresztül, vagy a saját gépeden.
`composer install` **nem** kell – a program külső függőség nélkül fut.

```bash
git clone https://github.com/giftformekft-tech/allegro-sync.git
cd allegro-sync
```

---

## 0. szint – működik-e egyáltalán (hozzáférés nélkül)

```bash
php tests/run.php
```

Elvárt: `Mind a 47 teszt átment.`

Ez a címképzőt és a CSV-beolvasót ellenőrzi, beleértve azt is, hogy a
plugin oldali export oszlopnevei egyeznek-e azzal, amit a program vár.

---

## 1. szint – a CSV-ellenőrző (hozzáférés nélkül)

Ez a parancs **nem hív API-t**, tehát bátran futtatható:

```bash
php bin/allegro import:validate examples/export-minta.csv --titles
```

Elvárt: `4 sor rendben, 1 sor hibás (4 hiba).` – a mintafájl utolsó sora
szándékosan hibás (nulla ár, nulla készlet, rossz kép-URL, hiányzó leírás),
hogy lásd, hogyan jelez.

A `--titles` megmutatja a generált ajánlatcímeket és a hosszukat. Érdemes
ránézni: az Allegro 12–75 karaktert és legalább három szót vár, és a
csonkolás gyakran nem az, amire az ember számít.

**Kilépési kód:** 0 ha minden sor rendben, 1 ha van hibás – cronból használható.

---

## 2. szint – kapcsolat az Allegróval (sandbox)

### 2.1 Sandbox fiók

A tesztkörnyezet teljesen elkülönül az élestől: **külön fiók, külön
alkalmazás, külön kulcsok.**

1. Regisztrálj: <https://allegro.pl.allegrosandbox.pl>
2. Az aktiválásnál **valós formátumú lengyel címet** adj meg, különben
   elhasal. Pl. `Grunwaldzka 182`, `60-166`, `Poznań`.
3. Kétfaktoros hitelesítés nem kell. Ha mégis kér kódot: `123456`
   (a sandbox nem küld SMS-t).
4. Valós személyes adatot ne adj meg – a sandbox szabályzata is ezt kéri.

### 2.2 Alkalmazás regisztrálása

<https://apps.developer.allegro.pl.allegrosandbox.pl/>

Két dologra figyelj:

- **Az alkalmazás neve** kerül a User-Agentbe, és egyeznie kell vele.
- A bejelentkezés **device flow**-val megy (a CLI kiír egy kódot, böngészőben
  hagyod jóvá). Ehhez olyan alkalmazástípust válassz, amelyik **nem**
  böngészős átirányítással dolgozik. Ha csak böngészős típus választható,
  az sem baj – szólj, és hozzáteszem az authorization code flow-t is.

### 2.3 Beállítás

```bash
cp .env.example .env
```

Töltsd ki:

```ini
ALLEGRO_ENV=sandbox
ALLEGRO_CLIENT_ID=<a regisztrációból>
ALLEGRO_CLIENT_SECRET=<a regisztrációból>
ALLEGRO_USER_AGENT="<AlkalmazasNev>/1.0.0 (+https://forme.hu/allegro-sync)"
```

A User-Agent formátuma kötött, és a program elutasítja, ha hibás.
Ez nem szőrszálhasogatás: a fejlesztői portál szerint fehérlistázási
tényezőként használják, és hiányában szokatlan aktivitásnál blokkolhatják
az alkalmazás IP-címét. Validátor:
<https://apps.developer.allegro.pl/user-agent>

### 2.4 Próba

```bash
php bin/allegro auth:status
```

Ez kiírja a beállításokat, majd megpróbál alkalmazás-tokent szerezni.
Ha sikerül, a kulcsok **és** a User-Agent rendben van.

Kulcsok nélkül ezt kapod, és ez a helyes viselkedés:

```
Alkalmazás-token: Hiányzó beállítás: ALLEGRO_CLIENT_ID.
```

---

## 3. szint – a valódi kérdés: listázható-e EAN nélkül

Ez a projekt go/no-go pontja.

```bash
php bin/allegro auth:login
```

Kiír egy linket és egy kódot; a böngészőben hagyod jóvá. Utána:

```bash
php bin/allegro categories:suggest "pamut póló"
php bin/allegro categories:suggest "kerámia bögre"
```

A kapott azonosítókkal:

```bash
php bin/allegro categories:scan --ids=12345,67890 --json=felderites.json
```

Kimenet kategóriánként:

| Verdikt | Jelentés |
|---|---|
| **OK** | EAN nélkül listázható, nincs is GTIN-paraméter |
| **FIGYELNI** | Ma működik, de van GTIN-paraméter – kötelezővé válhat |
| **ZÁRT** | Nem járható EAN nélkül; a program megírja, miért |

Ha van legalább egy OK vagy FIGYELNI kategória a póló/bögre típusokra,
a projekt mehet tovább. Ha minden ZÁRT, más kategóriát kell keresni –
és ezt **most** jobb megtudni, mint a feltöltő megírása után.

### Kockázatfigyelés

```bash
php bin/allegro gtin:watch --categories=12345,67890
```

Megmondja, tervez-e az Allegro GTIN-kötelezettséget a következő három
hónapban. Kilépési kódja 3, ha talál ilyet – így cronból riasztható.
Heti futtatás javasolt, mert EAN nélkül ez az egyetlen előrejelzésünk.

---

## 4. szint – a plugin oldali export

A `formemockup` pluginban: **Mockup Generator → Export → Allegro Export**.

1. Állítsd be az árszorzót, a készletet, a márkát, és típusonként a súlyt
   és az anyagot. Mentsd.
2. Termékek betöltése → jelölj ki néhányat → **Allegro CSV generálása**.
3. Töltsd le a fájlt, és futtasd át az ellenőrzőn:

```bash
php bin/allegro import:validate allegro-export-....csv --titles
```

Ez a kör azért fontos, mert a hibák nagy része a fájlból eldönthető, és
sokkal olcsóbb itt kiszűrni, mint több ezer elutasított API-hívásból.

**Amit érdemes megnézni a címeken:** ha a terméktípus slug alakban jelenik
meg (`polo` a `Póló` helyett), a program figyelmeztet. A cím a vevőnek
szól, ott ez csúnyán néz ki.

---

## Hibakeresés

Minden parancshoz adható `--verbose`, ami kiírja az összes HTTP-hívást és a
`Trace-Id`-t:

```bash
php bin/allegro categories:scan --ids=12345 --verbose
```

A teljes napló a `var/allegro-sync.log` fájlban van. **Ha hibát jelentesz
az Allegrónak, a Trace-Id-t kérik** – az naplóban minden hívásnál ott van.

Az állapottár környezetenként külön fájl (`var/state-sandbox.sqlite`,
`var/state-production.sqlite`). Ez szándékos: a sandbox azonosítók élesben
semmit nem jelentenek, összekeverni őket adatvesztés.

---

## Amit még NEM lehet tesztelni

A tényleges feltöltés (kép, katalógustermék, ajánlat) még nincs megírva –
szándékosan, mert a 3. szint eredménye dönti el, hogyan kell megírni.
A számlázás sincs bekötve, csak a varrat kész hozzá.
