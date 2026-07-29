<?php

declare(strict_types=1);

namespace AllegroSync\Cli\Commands;

use AllegroSync\Cli\Arguments;
use AllegroSync\Cli\Command;
use AllegroSync\Cli\Context;
use AllegroSync\Discover\CategoryScanner;

/**
 * Kategória-javaslat terméknévre – ez a belépőpont a felderítéshez, hogy ne
 * kelljen a teljes kategóriafát bejárni.
 */
final class CategoriesSuggestCommand implements Command
{
    public static function name(): string
    {
        return 'categories:suggest';
    }

    public static function description(): string
    {
        return 'Kategóriát javasol egy terméknévre (pl. "pamut póló")';
    }

    public function run(Context $context, Arguments $args): int
    {
        $phrase = $args->positional(0);
        if ($phrase === null || trim($phrase) === '') {
            $context->output->error('Adj meg egy terméknevet.');
            $context->output->write('Példa: bin/allegro categories:suggest "pamut póló"');

            return 1;
        }

        // Ez az erőforrás felhasználói tokent kér – nem elég az alkalmazás-token.
        $scanner = new CategoryScanner($context->userClient(), $context->logger);
        $matches = $scanner->suggest($phrase);

        if ($matches === []) {
            $context->output->warn("Nincs javaslat erre: {$phrase}");

            return 1;
        }

        $context->output->heading("Javasolt kategóriák: {$phrase}");

        $rows = [];
        foreach ($matches as $match) {
            $rows[] = [$match['id'], $match['name']];
        }
        $context->output->table(['Kategória ID', 'Név'], $rows);

        $ids = implode(',', array_column($matches, 'id'));
        $context->output->write();
        $context->output->dim('Ellenőrizd őket EAN-szempontból:');
        $context->output->write("  bin/allegro categories:scan --ids={$ids}");

        return 0;
    }
}
