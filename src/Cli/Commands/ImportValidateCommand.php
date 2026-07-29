<?php

declare(strict_types=1);

namespace AllegroSync\Cli\Commands;

use AllegroSync\Cli\Arguments;
use AllegroSync\Cli\Command;
use AllegroSync\Cli\Context;
use AllegroSync\Import\CsvReader;
use AllegroSync\Import\RowValidator;
use AllegroSync\Map\TitleBuilder;

/**
 * A forme.hu export ellenőrzése – hálózat nélkül.
 *
 * Ez a parancs szándékosan nem hív API-t: a hibák nagy része (hiányzó ár,
 * rossz cím, kép nélküli sor) a fájlból eldönthető, és sokkal olcsóbb itt
 * kiszűrni, mint több ezer 422-es válaszból.
 */
final class ImportValidateCommand implements Command
{
    public static function name(): string
    {
        return 'import:validate';
    }

    public static function description(): string
    {
        return 'Ellenőrzi a forme.hu export CSV-t (API-hívás nélkül)';
    }

    public function run(Context $context, Arguments $args): int
    {
        $out = $context->output;
        $path = $args->positional(0);

        if ($path === null) {
            $out->error('Adj meg egy CSV fájlt.');
            $out->write('Példa: bin/allegro import:validate export.csv');

            return 1;
        }

        $reader = new CsvReader();
        $result = $reader->read($path);

        $out->heading('Beolvasás');
        $out->write(sprintf('Fájl: %s', $path));
        $out->write(sprintf('Beolvasott sorok: %d', count($result['rows'])));

        foreach ($result['errors'] as $error) {
            $out->warn('  ' . $error);
        }

        $validator = new RowValidator();
        $validated = $validator->validate($result['rows']);

        $out->heading('Ellenőrzés');

        if ($validated['problems'] === []) {
            $out->success(sprintf('Mind a %d sor rendben van.', count($validated['ok'])));
        } else {
            $badRows = count(array_unique(array_column($validated['problems'], 'line')));
            $out->write(sprintf(
                '%s sor rendben, %s sor hibás (%d hiba).',
                $out->paint((string) count($validated['ok']), '32'),
                $out->paint((string) $badRows, '31'),
                count($validated['problems']),
            ));
            $out->write();

            $rows = [];
            foreach (array_slice($validated['problems'], 0, 50) as $problem) {
                $rows[] = [(string) $problem['line'], $problem['sku'], $problem['problem']];
            }
            $out->table(['Sor', 'SKU', 'Hiba'], $rows);

            if (count($validated['problems']) > 50) {
                $out->dim(sprintf('… és további %d hiba.', count($validated['problems']) - 50));
            }
        }

        // A címek előnézete azért hasznos, mert a 75 karakteres korlát miatt
        // a cím gyakran nem az, amire az ember számít.
        if ($args->flag('titles') && $validated['ok'] !== []) {
            $out->heading('Címek előnézete');
            $builder = new TitleBuilder();
            $rows = [];
            $slugLooking = 0;
            foreach (array_slice($validated['ok'], 0, 20) as $row) {
                $title = $builder->build([$row->name, $row->typeLabel, $row->color, $row->size]);
                $rows[] = [
                    $row->sku,
                    $title->title,
                    (string) mb_strlen($title->title),
                ];
                if ($row->typeLabel === $row->type && $row->type !== '' && $row->type === mb_strtolower($row->type)) {
                    $slugLooking++;
                }
            }
            $out->table(['SKU', 'Cím', 'Hossz'], $rows);

            // A cím a vevőnek szól – egy "polo" slug ott csúnyán néz ki.
            if ($slugLooking > 0) {
                $out->write();
                $out->warn('A címekben a terméktípus slug alakban szerepel (pl. "polo").');
                $out->warn('Vegyél fel egy type_label oszlopot az exportba az olvasható');
                $out->warn('megnevezéssel ("Póló"), különben ez kerül ki a vevőnek.');
            }
        }

        $out->write();

        if (!$args->flag('titles')) {
            $out->dim('Tipp: a címek előnézetéhez add hozzá a --titles kapcsolót.');
        }

        return $validated['problems'] === [] ? 0 : 1;
    }
}
