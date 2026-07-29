<?php

declare(strict_types=1);

namespace AllegroSync\Cli\Commands;

use AllegroSync\Cli\Arguments;
use AllegroSync\Cli\Command;
use AllegroSync\Cli\Context;

/**
 * Bejelentkezés device flow-val: a CLI kiír egy kódot, a böngészőben
 * hagyod jóvá. Így nem kell átirányítási URL-t és webszervert üzemeltetni.
 */
final class AuthLoginCommand implements Command
{
    public static function name(): string
    {
        return 'auth:login';
    }

    public static function description(): string
    {
        return 'Bejelentkezés az Allegro-fiókba (device flow)';
    }

    public function run(Context $context, Arguments $args): int
    {
        $out = $context->output;
        $auth = $context->auth();

        $out->dim(sprintf('Környezet: %s', $context->config->environment()));

        $device = $auth->startDeviceFlow();

        $out->heading('Bejelentkezés');
        $out->write('Nyisd meg ezt a címet, és hagyd jóvá a hozzáférést:');
        $out->write();
        $out->write('  ' . $out->paint(
            $device['verification_uri_complete'] ?? $device['verification_uri'],
            '1;4;36',
        ));
        $out->write();
        $out->write('Ha a rendszer kódot kér, ez az:');
        $out->write('  ' . $out->paint($device['user_code'], '1;33'));
        $out->write();
        $out->dim(sprintf('Várakozás a jóváhagyásra (legfeljebb %d másodperc)…', $device['expires_in']));

        $auth->pollDeviceToken(
            $device['device_code'],
            $device['interval'],
            $device['expires_in'],
        );

        $out->write();
        $out->success('Bejelentkezve. A token elmentve.');
        $out->dim('Az access token ~12 óráig él, a refresh token ~3 hónapig – a frissítés automatikus.');

        return 0;
    }
}
