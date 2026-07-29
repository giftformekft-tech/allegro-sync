<?php

declare(strict_types=1);

namespace AllegroSync\Cli\Commands;

use AllegroSync\Cli\Arguments;
use AllegroSync\Cli\Command;
use AllegroSync\Cli\Context;

final class StatusCommand implements Command
{
    public static function name(): string
    {
        return 'status';
    }

    public static function description(): string
    {
        return 'Az állapottár összesítése (ajánlatok, termékek, rendelések)';
    }

    public function run(Context $context, Arguments $args): int
    {
        $db = $context->db();
        $out = $context->output;

        $out->heading('Ajánlatok állapota');
        $counts = $db->offerStatusCounts();

        if ($counts === []) {
            $out->dim('Még nincs feltöltött ajánlat.');
        } else {
            $rows = [];
            foreach ($counts as $status => $count) {
                $rows[] = [$status, (string) $count];
            }
            $out->table(['Állapot', 'Darab'], $rows);
        }

        $pdo = $db->pdo();
        $products = (int) ($pdo->query('SELECT COUNT(*) FROM products')?->fetchColumn() ?: 0);
        $images = (int) ($pdo->query('SELECT COUNT(*) FROM images')?->fetchColumn() ?: 0);
        $orders = (int) ($pdo->query('SELECT COUNT(*) FROM orders')?->fetchColumn() ?: 0);

        $out->heading('Összesítés');
        $out->table(['Erőforrás', 'Darab'], [
            ['Katalógustermékek', (string) $products],
            ['Feltöltött képek', (string) $images],
            ['Rendelések', (string) $orders],
        ]);

        $out->write();
        $out->dim('Állapottár: ' . $context->config->statePath());

        return 0;
    }
}
