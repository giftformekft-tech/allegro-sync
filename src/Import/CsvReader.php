<?php

declare(strict_types=1);

namespace AllegroSync\Import;

use RuntimeException;

/**
 * A forme.hu termékexportjának beolvasása.
 *
 * A Temu-exporthoz hasonlóan `;` vagy `,` elválasztót és UTF-8 BOM-ot is
 * elvisel, mert a WooCommerce oldali export és az Excel is ezeket keveri.
 *
 * Az oszlopnevek magyarul és angolul is elfogadottak, hogy a plugin oldali
 * exportőr elnevezései ne törjék el a beolvasást.
 */
final class CsvReader
{
    /** @var array<string,list<string>> mező => elfogadott fejlécnevek */
    private const COLUMNS = [
        'sku' => ['sku', 'cikkszám', 'cikkszam'],
        'parent_sku' => ['parent_sku', 'alap_sku', 'fő sku', 'fo_sku'],
        'name' => ['name', 'termék neve', 'termek neve', 'név', 'nev'],
        'description' => ['description', 'leírás', 'leiras'],
        'type' => ['type', 'típus', 'tipus'],
        'type_label' => ['type_label', 'típus neve', 'tipus neve', 'típus megnevezés'],
        'color' => ['color', 'szín', 'szin'],
        'size' => ['size', 'méret', 'meret'],
        'price_huf' => ['price_huf', 'ár', 'ar', 'price'],
        'stock' => ['stock', 'készlet', 'keszlet'],
        'image_url' => ['image_url', 'kép url', 'kep url', 'kép', 'kep'],
        'weight_g' => ['weight_g', 'súly', 'suly', 'tömeg', 'tomeg'],
        'brand' => ['brand', 'márka', 'marka'],
        'material' => ['material', 'anyag'],
        'ai_content' => ['ai_content', 'ai'],
    ];

    /** Ezek nélkül nem indul a feldolgozás. */
    private const REQUIRED = ['sku', 'name', 'type', 'color', 'size', 'price_huf', 'stock', 'image_url'];

    /**
     * @return array{rows:list<Row>,errors:list<string>}
     */
    public function read(string $path): array
    {
        if (!is_file($path)) {
            throw new RuntimeException("A fájl nem található: {$path}");
        }

        $raw = file_get_contents($path);
        if ($raw === false) {
            throw new RuntimeException("A fájl nem olvasható: {$path}");
        }

        // UTF-8 BOM eltávolítása – az Excel szereti odatenni.
        if (str_starts_with($raw, "\xEF\xBB\xBF")) {
            $raw = substr($raw, 3);
        }

        $delimiter = $this->detectDelimiter($raw);

        $handle = fopen('php://temp', 'r+');
        if ($handle === false) {
            throw new RuntimeException('Nem hozható létre ideiglenes puffer.');
        }
        fwrite($handle, $raw);
        rewind($handle);

        $header = fgetcsv($handle, 0, $delimiter, '"', '\\');
        if ($header === false || $header === [null]) {
            fclose($handle);

            throw new RuntimeException('A CSV üres.');
        }

        $index = $this->mapHeader($header);

        $missing = [];
        foreach (self::REQUIRED as $field) {
            if (!isset($index[$field])) {
                $missing[] = $field;
            }
        }
        if ($missing !== []) {
            fclose($handle);

            throw new RuntimeException(
                "Hiányzó kötelező oszlop(ok): " . implode(', ', $missing) . "\n"
                . 'Talált fejléc: ' . implode(' | ', array_map('strval', $header))
            );
        }

        // Az extra képoszlopok (image_url_2, image_url_3, …) felderítése.
        $extraImages = [];
        foreach ($header as $position => $label) {
            $normalised = $this->normalise((string) $label);
            if (preg_match('/^(image_url|kép url|kep url)[ _]?(\d+)$/u', $normalised) === 1) {
                $extraImages[] = $position;
            }
        }

        $rows = [];
        $errors = [];
        $seenSkus = [];
        $line = 1;

        while (($record = fgetcsv($handle, 0, $delimiter, '"', '\\')) !== false) {
            $line++;

            if ($record === [null] || $this->isBlank($record)) {
                continue;
            }

            $get = static function (string $field) use ($record, $index): string {
                $position = $index[$field] ?? null;
                if ($position === null || !isset($record[$position])) {
                    return '';
                }

                return trim((string) $record[$position]);
            };

            $sku = $get('sku');
            if ($sku === '') {
                $errors[] = "{$line}. sor: hiányzó SKU – kihagyva.";

                continue;
            }

            if (isset($seenSkus[$sku])) {
                $errors[] = sprintf(
                    '%d. sor: ismétlődő SKU (%s), először a %d. sorban. Kihagyva.',
                    $line,
                    $sku,
                    $seenSkus[$sku],
                );

                continue;
            }
            $seenSkus[$sku] = $line;

            $images = [];
            $primary = $get('image_url');
            if ($primary !== '') {
                $images[] = $primary;
            }
            foreach ($extraImages as $position) {
                $extra = isset($record[$position]) ? trim((string) $record[$position]) : '';
                if ($extra !== '') {
                    $images[] = $extra;
                }
            }

            $weight = $get('weight_g');

            $rows[] = new Row(
                lineNumber: $line,
                sku: $sku,
                parentSku: $get('parent_sku') !== '' ? $get('parent_sku') : $sku,
                name: $get('name'),
                description: $get('description'),
                type: $get('type'),
                // A címbe a slug helyett az olvasható megnevezés kell
                // ("Póló", nem "polo"). Ha nincs külön oszlop, a slugra
                // esünk vissza – de az látszani fog a cím-előnézetben.
                typeLabel: $get('type_label') !== '' ? $get('type_label') : $get('type'),
                color: $get('color'),
                size: $get('size'),
                priceHuf: $this->normalisePrice($get('price_huf')),
                stock: (int) $get('stock'),
                imageUrls: array_values(array_unique($images)),
                weightGrams: $weight === '' ? null : (int) $weight,
                brand: $get('brand'),
                material: $get('material'),
                aiContent: $this->truthy($get('ai_content')),
            );
        }

        fclose($handle);

        return ['rows' => $rows, 'errors' => $errors];
    }

    /**
     * Az ár stringként utazik az API felé, ezért itt is stringgé
     * normalizáljuk – lebegőpontos átmenet nélkül, hogy ne keletkezzen
     * kerekítési hiba.
     */
    private function normalisePrice(string $value): string
    {
        $value = str_replace([' ', "\u{00A0}"], '', $value);
        $value = str_replace(',', '.', $value);
        $value = preg_replace('/[^0-9.]/', '', $value) ?? '';

        if ($value === '' || $value === '.') {
            return '';
        }

        // Több tizedespont esetén az elsőt tartjuk meg értelmesnek.
        $parts = explode('.', $value);
        if (count($parts) > 2) {
            $value = array_shift($parts) . '.' . implode('', $parts);
        }

        return rtrim(rtrim($value, '0'), '.') !== '' ? $value : '0';
    }

    private function detectDelimiter(string $raw): string
    {
        $sample = substr($raw, 0, 4096);
        $firstLine = strtok($sample, "\r\n");
        $sample = $firstLine === false ? $sample : $firstLine;

        return substr_count($sample, ';') >= substr_count($sample, ',') ? ';' : ',';
    }

    /**
     * @param list<string|null> $header
     *
     * @return array<string,int>
     */
    private function mapHeader(array $header): array
    {
        $index = [];

        foreach ($header as $position => $label) {
            $normalised = $this->normalise((string) $label);
            foreach (self::COLUMNS as $field => $aliases) {
                if (isset($index[$field])) {
                    continue;
                }
                foreach ($aliases as $alias) {
                    if ($normalised === $this->normalise($alias)) {
                        $index[$field] = $position;

                        break 2;
                    }
                }
            }
        }

        return $index;
    }

    private function normalise(string $label): string
    {
        $label = trim(mb_strtolower($label));

        return preg_replace('/\s+/u', ' ', $label) ?? $label;
    }

    /** @param list<string|null> $record */
    private function isBlank(array $record): bool
    {
        foreach ($record as $value) {
            if ($value !== null && trim((string) $value) !== '') {
                return false;
            }
        }

        return true;
    }

    private function truthy(string $value): bool
    {
        return in_array(mb_strtolower($value), ['1', 'igen', 'yes', 'true', 'x'], true);
    }
}
