<?php

declare(strict_types=1);

use AllegroSync\Import\CsvReader;
use AllegroSync\Import\RowValidator;

/** @var TestRunner $t */

$t->group('CsvReader – a forme.hu export beolvasása');

$tmp = sys_get_temp_dir() . '/allegro-csv-test-' . getmypid() . '.csv';

// UTF-8 BOM + pontosvessző + magyar fejlécek: ez a WooCommerce/Excel valósága.
$csv = "\xEF\xBB\xBF" . implode(';', [
    'sku', 'parent_sku', 'name', 'description', 'type', 'color', 'size',
    'price_huf', 'stock', 'image_url', 'image_url_2', 'weight_g', 'brand', 'material', 'ai_content',
]) . "\n";
$csv .= "CICA-POLO-FEKETE-L;CICA;Vicces macskás minta;Szép leírás;polo;Fekete;L;5 990;100;https://forme.hu/a.webp;https://forme.hu/b.webp;180;forme;100% pamut;igen\n";
$csv .= "CICA-POLO-FEKETE-M;CICA;Vicces macskás minta;Szép leírás;polo;Fekete;M;5990,50;100;https://forme.hu/a.webp;;180;forme;100% pamut;\n";
$csv .= "\n"; // üres sor
$csv .= "CICA-POLO-FEKETE-L;CICA;Duplikátum;Leírás;polo;Fekete;L;5990;100;https://forme.hu/a.webp;;180;forme;pamut;\n";
$csv .= ";CICA;SKU nélkül;Leírás;polo;Fehér;S;5990;100;https://forme.hu/c.webp;;180;forme;pamut;\n";

file_put_contents($tmp, $csv);

$reader = new CsvReader();
$result = $reader->read($tmp);

$t->same(2, count($result['rows']), 'Két érvényes sor olvasódott be');
$t->same(2, count($result['errors']), 'Két hiba: duplikált SKU és hiányzó SKU');

$first = $result['rows'][0];
$t->same('CICA-POLO-FEKETE-L', $first->sku, 'Az SKU beolvasva');
$t->same('CICA', $first->parentSku, 'A parent SKU beolvasva');
$t->same(2, count($first->imageUrls), 'Mindkét képoszlop beolvasva');
$t->same(100, $first->stock, 'A készlet beolvasva');
$t->same(180, $first->weightGrams, 'A súly beolvasva');
$t->assert($first->aiContent, 'Az "igen" AI-jelölés igazra fordul');

// Az árnál a szóköz mint ezreselválasztó és a vessző mint tizedesjel is
// előfordul – a normalizálásnak mindkettőt kezelnie kell, string maradva.
$t->same('5990', $first->priceHuf, 'Az ezreselválasztó szóköz eltűnik');
$t->same('5990.50', $result['rows'][1]->priceHuf, 'A tizedesvessző ponttá alakul');
$t->assert(!$result['rows'][1]->aiContent, 'Az üres AI-jelölés hamis');

$duplicateError = false;
foreach ($result['errors'] as $error) {
    if (str_contains($error, 'ismétlődő SKU')) {
        $duplicateError = true;
    }
}
$t->assert($duplicateError, 'A duplikált SKU külön hibaként jelenik meg');

// --- validátor --------------------------------------------------------------
$t->group('RowValidator – sorszintű ellenőrzés');

$validator = new RowValidator();
$validated = $validator->validate($result['rows']);

$t->same(2, count($validated['ok']), 'Mindkét sor átmegy a validáláson');
$t->same(0, count($validated['problems']), 'Nincs hiba a helyes sorokban');

// Nulla ár/készlet, rossz kép-URL és túl rövid cím egyszerre.
// A név szándékosan olyan rövid, hogy a típussal, színnel és mérettel
// együtt se érje el a 12 karaktert – különben a cím érvényes lenne.
$bad = "sku;name;description;type;color;size;price_huf;stock;image_url\n"
    . "X-1;A;Leírás;b;c;d;0;0;nem-url\n";
file_put_contents($tmp, $bad);

$badResult = $reader->read($tmp);
$badValidated = $validator->validate($badResult['rows']);

$problems = array_column($badValidated['problems'], 'problem');
$joined = implode(' | ', $problems);

$t->same(0, count($badValidated['ok']), 'A hibás sor nem megy át');
$t->assert(str_contains($joined, 'ár'), 'A nulla árat észreveszi');
$t->assert(str_contains($joined, 'készlet') || str_contains($joined, 'Nulla'), 'A nulla készletet észreveszi');
$t->assert(str_contains($joined, 'kép-URL') || str_contains($joined, 'kép'), 'Az érvénytelen kép-URL-t észreveszi');
$t->assert(str_contains($joined, 'Cím'), 'A túl rövid címet észreveszi');

// --- hiányzó kötelező oszlop ------------------------------------------------
file_put_contents($tmp, "sku;name\nX-1;Valami\n");
$threw = false;
try {
    $reader->read($tmp);
} catch (RuntimeException $e) {
    $threw = str_contains($e->getMessage(), 'Hiányzó kötelező oszlop');
}
$t->assert($threw, 'Hiányzó kötelező oszlopnál beszédes hibát dob');

@unlink($tmp);

// --- szerződés a plugin oldali exporttal ------------------------------------
// A formemockup plugin MG_Allegro_Export_Page::CSV_COLUMNS listája szerint ír.
// Ha a két oldal elcsúszik, az itt bukik el, nem éles feltöltés közben.
$t->group('CSV-szerződés a formemockup plugin exportjával');

$example = dirname(__DIR__) . '/examples/export-minta.csv';
$t->assert(is_file($example), 'A mintafájl megvan (examples/export-minta.csv)');

if (is_file($example)) {
    $expectedHeader = [
        'sku', 'parent_sku', 'name', 'description', 'type', 'type_label',
        'color', 'size', 'price_huf', 'stock', 'image_url',
        'weight_g', 'brand', 'material', 'ai_content',
    ];

    $firstLine = fgets(fopen($example, 'r')) ?: '';
    $firstLine = ltrim($firstLine, "\xEF\xBB\xBF");
    $actualHeader = array_map('trim', explode(';', trim($firstLine)));

    $t->same($expectedHeader, $actualHeader, 'A mintafájl fejléce megegyezik a plugin CSV_COLUMNS listájával');

    $exampleResult = $reader->read($example);
    $exampleValidated = $validator->validate($exampleResult['rows']);

    $t->same(5, count($exampleResult['rows']), 'A mintafájl öt sora beolvasható');
    $t->same(4, count($exampleValidated['ok']), 'Négy sor érvényes, a szándékosan hibás nem');

    $first = $exampleResult['rows'][0];
    $t->same('Póló', $first->typeLabel, 'A type_label olvasható megnevezésként érkezik');
    $t->same('polo', $first->type, 'A type slug külön mezőben marad');
}
