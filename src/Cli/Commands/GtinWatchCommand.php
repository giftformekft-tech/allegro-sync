<?php

declare(strict_types=1);

namespace AllegroSync\Cli\Commands;

use AllegroSync\Api\ApiException;
use AllegroSync\Cli\Arguments;
use AllegroSync\Cli\Command;
use AllegroSync\Cli\Context;
use AllegroSync\Discover\GtinWatchdog;

/**
 * Heti cronnak szánt parancs: figyeli, hogy a GTIN kötelezővé válik-e.
 *
 * Kilépési kód 3, ha GTIN-t érintő változást talál – így a cron ki tudja
 * szűrni, mikor kell értesíteni.
 */
final class GtinWatchCommand implements Command
{
    public static function name(): string
    {
        return 'gtin:watch';
    }

    public static function description(): string
    {
        return 'Figyeli, hogy a GTIN kötelezővé válik-e a használt kategóriákban';
    }

    public function run(Context $context, Arguments $args): int
    {
        $out = $context->output;
        $watchdog = new GtinWatchdog($context->userClient());

        $categoryIds = [];
        $idList = $args->option('categories');
        if ($idList !== null && $idList !== '') {
            $categoryIds = array_values(array_filter(array_map('trim', explode(',', $idList))));
        }

        $alert = false;

        // ---------------------------------------------- kategóriaszintű előrejelzés
        $out->heading('Tervezett paraméter-változások (max. 3 hónap)');

        try {
            $changes = $watchdog->scheduledRequirementChanges($categoryIds);

            if ($changes === []) {
                $out->success('Nincs bejelentett változás.');
            } else {
                $rows = [];
                foreach ($changes as $change) {
                    $rows[] = [
                        $change['categoryId'],
                        $this->shorten($change['categoryName'], 30),
                        $change['parameterName'],
                        substr($change['scheduledFor'], 0, 10),
                        $change['isGtin'] ? $out->paint('GTIN!', '1;31') : '',
                    ];
                    if ($change['isGtin']) {
                        $alert = true;
                    }
                }
                $out->table(['Kategória', 'Név', 'Paraméter', 'Mikortól', ''], $rows);
            }
        } catch (ApiException $e) {
            $out->error('A tervezett változások nem kérdezhetők le: ' . $e->getMessage());
        }

        // ------------------------------------------------- ajánlatszintű hiányok
        $out->heading('Meglévő ajánlatok hiányzó paraméterekkel');

        try {
            $planned = $watchdog->unfilledParameters('REQUIREMENT_PLANNED');
            $required = $watchdog->unfilledParameters('REQUIRED');

            $this->renderUnfilled($context, 'Hamarosan kötelező', $planned, $alert);
            $this->renderUnfilled($context, 'Már most kötelező', $required, $alert);
        } catch (ApiException $e) {
            $out->error('A hiányzó paraméterek nem kérdezhetők le: ' . $e->getMessage());
        }

        $out->write();

        if ($alert) {
            $out->error('FIGYELEM: GTIN-t érintő változás van érvényben vagy bejelentve.');
            $out->write('Mivel EAN nincs és nem is lesz, ez az érintett kategóriákban');
            $out->write('leállíthatja a feltöltést. Keress alternatív kategóriát,');
            $out->write('vagy vizsgáld felül a kínálatot.');

            return 3;
        }

        $out->success('Nincs GTIN-t érintő kockázat a látóhatáron.');

        return 0;
    }

    /**
     * @param list<array{offerId:string,offerName:string,parameters:list<string>,gtinAffected:bool}> $items
     */
    private function renderUnfilled(Context $context, string $label, array $items, bool &$alert): void
    {
        $out = $context->output;

        if ($items === []) {
            $out->dim($label . ': nincs ilyen ajánlat.');

            return;
        }

        $gtinOnes = array_values(array_filter($items, static fn (array $i): bool => $i['gtinAffected']));
        if ($gtinOnes !== []) {
            $alert = true;
        }

        $out->write(sprintf(
            '%s: %d ajánlat (ebből %s GTIN-t érint)',
            $label,
            count($items),
            $out->paint((string) count($gtinOnes), $gtinOnes === [] ? '32' : '1;31'),
        ));

        $rows = [];
        foreach (array_slice($gtinOnes !== [] ? $gtinOnes : $items, 0, 15) as $item) {
            $rows[] = [
                $item['offerId'],
                $this->shorten($item['offerName'], 40),
                $this->shorten(implode(', ', $item['parameters']), 40),
            ];
        }
        $out->table(['Ajánlat', 'Név', 'Hiányzó paraméterek'], $rows);
    }

    private function shorten(string $text, int $max): string
    {
        if (mb_strlen($text) <= $max) {
            return $text;
        }

        return mb_substr($text, 0, $max - 1) . '…';
    }
}
