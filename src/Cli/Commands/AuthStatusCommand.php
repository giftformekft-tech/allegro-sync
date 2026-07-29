<?php

declare(strict_types=1);

namespace AllegroSync\Cli\Commands;

use AllegroSync\Auth\Authenticator;
use AllegroSync\Cli\Arguments;
use AllegroSync\Cli\Command;
use AllegroSync\Cli\Context;
use Throwable;

final class AuthStatusCommand implements Command
{
    public static function name(): string
    {
        return 'auth:status';
    }

    public static function description(): string
    {
        return 'Megmutatja a beállításokat és a tokenek állapotát';
    }

    public function run(Context $context, Arguments $args): int
    {
        $out = $context->output;
        $config = $context->config;

        $out->heading('Beállítások');
        $out->table(['Kulcs', 'Érték'], [
            ['Környezet', $config->environment()],
            ['API', $config->apiBase()],
            ['OAuth', $config->authBase()],
            ['Nyelv', $config->language()],
            ['User-Agent', $config->userAgent()],
            ['Kéréskorlát', $config->rateLimitPerMinute() . ' / perc'],
            ['Állapottár', $config->statePath()],
            ['Számlázás', $config->invoiceDriver() === 'none' ? 'kikapcsolva' : $config->invoiceDriver()],
        ]);

        $store = $context->tokenStore();

        $out->heading('Tokenek');
        $rows = [];
        foreach ([Authenticator::TOKEN_APP => 'Alkalmazás', Authenticator::TOKEN_USER => 'Felhasználó'] as $name => $label) {
            $row = $store->find($name);
            if ($row === null) {
                $rows[] = [$label, 'nincs', '-'];

                continue;
            }
            $expiresAt = (int) $row['expires_at'];
            $rows[] = [
                $label,
                $store->isExpired($name) ? 'lejárt' : 'érvényes',
                date('Y-m-d H:i', $expiresAt),
            ];
        }
        $out->table(['Token', 'Állapot', 'Lejár'], $rows);

        // Élő próba: az alkalmazás-token megszerzése egyben azt is igazolja,
        // hogy a client id/secret és a User-Agent rendben van.
        $out->heading('Kapcsolatpróba');
        try {
            $context->auth()->appToken();
            $out->success('Alkalmazás-token megszerezve – a kulcsok és a User-Agent rendben.');
        } catch (Throwable $e) {
            $out->error('Alkalmazás-token: ' . $e->getMessage());

            return 1;
        }

        if ($store->find(Authenticator::TOKEN_USER) === null) {
            $out->warn('Felhasználói token nincs. Az ajánlat- és rendeléskezeléshez jelentkezz be:');
            $out->write('  bin/allegro auth:login');
        }

        return 0;
    }
}
