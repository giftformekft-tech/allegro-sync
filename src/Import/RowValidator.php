<?php

declare(strict_types=1);

namespace AllegroSync\Import;

use AllegroSync\Map\TitleBuilder;

/**
 * Sorszintű ellenőrzés, MIELŐTT bármit is küldenénk az Allegróra.
 *
 * A cél, hogy a hibák a saját gépünkön derüljenek ki, ne 422-es API-válaszként
 * több ezer hívás után. A hibaüzenet mindig a CSV sorszámára hivatkozik.
 */
final class RowValidator
{
    public function __construct(private readonly TitleBuilder $titleBuilder = new TitleBuilder())
    {
    }

    /**
     * @param list<Row> $rows
     *
     * @return array{ok:list<Row>,problems:list<array{line:int,sku:string,problem:string}>}
     */
    public function validate(array $rows): array
    {
        $ok = [];
        $problems = [];

        foreach ($rows as $row) {
            $issues = $this->check($row);

            if ($issues === []) {
                $ok[] = $row;

                continue;
            }

            foreach ($issues as $issue) {
                $problems[] = ['line' => $row->lineNumber, 'sku' => $row->sku, 'problem' => $issue];
            }
        }

        return ['ok' => $ok, 'problems' => $problems];
    }

    /** @return list<string> */
    private function check(Row $row): array
    {
        $issues = [];

        if ($row->name === '') {
            $issues[] = 'Hiányzó terméknév.';
        }

        if ($row->type === '') {
            $issues[] = 'Hiányzó terméktípus – enélkül nincs kategória-leképezés.';
        }

        if ($row->imageUrls === []) {
            $issues[] = 'Nincs kép. Az Allegro legalább egy képet megkövetel.';
        } else {
            foreach ($row->imageUrls as $url) {
                if (!filter_var($url, FILTER_VALIDATE_URL)) {
                    $issues[] = "Érvénytelen kép-URL: {$url}";
                }
            }
        }

        if ($row->priceHuf === '' || !is_numeric($row->priceHuf) || (float) $row->priceHuf <= 0) {
            $issues[] = 'Hiányzó vagy érvénytelen ár.';
        }

        if ($row->stock < 0) {
            $issues[] = 'A készlet nem lehet negatív.';
        }

        if ($row->stock === 0) {
            $issues[] = 'Nulla készlet – az ajánlat nem lenne aktiválható.';
        }

        // A címszabály a leggyakoribb buktató, ezért itt is ellenőrizzük,
        // ugyanazzal a modullal, ami majd a valódi címet képzi.
        $title = $this->titleBuilder->build([$row->name, $row->typeLabel, $row->color, $row->size]);
        if (!$title->valid) {
            $issues[] = 'Cím: ' . ($title->problem ?? 'ismeretlen hiba') . " (\"{$title->title}\")";
        }

        if ($row->description === '') {
            $issues[] = 'Hiányzó leírás.';
        } elseif (strlen($row->description) > 40000) {
            $issues[] = 'A leírás meghaladja a 40 000 bájtot.';
        }

        return $issues;
    }
}
