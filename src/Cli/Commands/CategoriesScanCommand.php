<?php

declare(strict_types=1);

namespace AllegroSync\Cli\Commands;

use AllegroSync\Cli\Arguments;
use AllegroSync\Cli\Command;
use AllegroSync\Cli\Context;
use AllegroSync\Discover\CategoryScanner;
use AllegroSync\Discover\CategoryVerdict;

/**
 * A 0. fázis parancsa: go/no-go tábla az EAN nélküli listázhatóságról.
 */
final class CategoriesScanCommand implements Command
{
    public static function name(): string
    {
        return 'categories:scan';
    }

    public static function description(): string
    {
        return 'Megvizsgálja, mely kategóriákban listázhatunk EAN/GTIN nélkül';
    }

    public function run(Context $context, Arguments $args): int
    {
        $root = $args->option('root');
        $idList = $args->option('ids');

        if ($root === null && $idList === null) {
            $context->output->error('Adj meg --root=<kategoriaId> vagy --ids=<id1,id2> kapcsolót.');
            $context->output->write();
            $context->output->write('Példák:');
            $context->output->write('  bin/allegro categories:scan --ids=12345,67890');
            $context->output->write('  bin/allegro categories:scan --root=3 --depth=3');
            $context->output->write();
            $context->output->dim('Kategória-azonosítót a categories:suggest paranccsal találsz.');

            return 1;
        }

        // A kategória- és paraméter-erőforrások alkalmazás-tokennel is mennek,
        // tehát ehhez NEM kell felhasználói bejelentkezés.
        $scanner = new CategoryScanner($context->appClient(), $context->logger);

        $context->output->dim(sprintf(
            'Környezet: %s · nyelv: %s',
            $context->config->environment(),
            $context->config->language(),
        ));

        if ($idList !== null) {
            $ids = array_values(array_filter(array_map('trim', explode(',', $idList))));
            $context->output->dim(sprintf('%d kategória ellenőrzése…', count($ids)));
            $verdicts = $scanner->scanIds($ids);
        } else {
            $depth = (int) ($args->option('depth', '4') ?? '4');
            $context->output->dim("Bejárás a(z) {$root} kategóriától, max. {$depth} szint mélyen…");
            $verdicts = $scanner->scanTree((string) $root, $depth);
        }

        if ($verdicts === []) {
            $context->output->warn('Nem található levélkategória a megadott gyökér alatt.');

            return 1;
        }

        $this->render($context, $verdicts);

        $jsonPath = $args->option('json');
        if ($jsonPath !== null && $jsonPath !== '') {
            $this->writeJson($jsonPath, $verdicts);
            $context->output->dim("A részletes eredmény elmentve: {$jsonPath}");
        }

        // Kilépési kód: 0, ha van legalább egy járható kategória.
        foreach ($verdicts as $verdict) {
            if ($verdict->verdict() === CategoryVerdict::OK || $verdict->verdict() === CategoryVerdict::RISKY) {
                return 0;
            }
        }

        return 2;
    }

    /** @param list<CategoryVerdict> $verdicts */
    private function render(Context $context, array $verdicts): void
    {
        $out = $context->output;

        $out->heading('Kategóriák EAN nélküli listázhatósága');

        $rows = [];
        foreach ($verdicts as $verdict) {
            $mark = match ($verdict->verdict()) {
                CategoryVerdict::OK => $out->paint('OK', '32'),
                CategoryVerdict::RISKY => $out->paint('FIGYELNI', '33'),
                default => $out->paint('ZÁRT', '31'),
            };

            $rows[] = [
                $verdict->id,
                $this->shorten($verdict->path !== '' ? $verdict->path : $verdict->name, 52),
                $verdict->gtinRequired ? 'IGEN' : ($verdict->gtinPresent ? 'nem (van)' : 'nincs'),
                $verdict->productCreationEnabled ? 'igen' : 'NEM',
                $mark,
            ];
        }

        $out->table(
            ['Kategória ID', 'Útvonal', 'GTIN kötelező?', 'Saját termék?', 'Verdikt'],
            $rows,
        );

        $counts = [CategoryVerdict::OK => 0, CategoryVerdict::RISKY => 0, CategoryVerdict::BLOCKED => 0];
        foreach ($verdicts as $verdict) {
            $counts[$verdict->verdict()]++;
        }

        $out->write();
        $out->write(sprintf(
            'Összesen %d kategória: %s járható, %s figyelendő, %s zárt.',
            count($verdicts),
            $out->paint((string) $counts[CategoryVerdict::OK], '32'),
            $out->paint((string) $counts[CategoryVerdict::RISKY], '33'),
            $out->paint((string) $counts[CategoryVerdict::BLOCKED], '31'),
        ));

        // A "figyelendő" eset megérdemel egy magyarázatot, mert ez a
        // leggyakoribb kimenet, és könnyű félreérteni.
        if ($counts[CategoryVerdict::RISKY] > 0) {
            $out->write();
            $out->warn('A "figyelendő" kategóriákban ma listázhatunk EAN nélkül,');
            $out->warn('de létezik GTIN-paraméter, ami később kötelezővé válhat.');
            $out->warn('Ezekre futtasd rendszeresen: bin/allegro gtin:watch');
        }

        if ($counts[CategoryVerdict::BLOCKED] > 0) {
            $out->write();
            $out->heading('Miért zárt?');
            foreach ($verdicts as $verdict) {
                if ($verdict->verdict() !== CategoryVerdict::BLOCKED) {
                    continue;
                }
                $out->write(sprintf('  %s  %s', $verdict->id, $verdict->reason()));
            }
        }
    }

    /** @param list<CategoryVerdict> $verdicts */
    private function writeJson(string $path, array $verdicts): void
    {
        $data = [];
        foreach ($verdicts as $verdict) {
            $data[] = [
                'id' => $verdict->id,
                'name' => $verdict->name,
                'path' => $verdict->path,
                'verdict' => $verdict->verdict(),
                'reason' => $verdict->reason(),
                'gtinPresent' => $verdict->gtinPresent,
                'gtinRequired' => $verdict->gtinRequired,
                'productCreationEnabled' => $verdict->productCreationEnabled,
                'offersWithProductPublicationEnabled' => $verdict->offersWithProductPublicationEnabled,
                'requiredParameters' => $verdict->requiredParameters,
                'error' => $verdict->error,
            ];
        }

        file_put_contents(
            $path,
            json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
        );
    }

    private function shorten(string $text, int $max): string
    {
        if (mb_strlen($text) <= $max) {
            return $text;
        }

        return '…' . mb_substr($text, -($max - 1));
    }
}
