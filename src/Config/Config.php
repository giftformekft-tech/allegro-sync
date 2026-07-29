<?php

declare(strict_types=1);

namespace AllegroSync\Config;

use RuntimeException;

/**
 * A .env beolvasása és a környezetfüggő végpontok feloldása.
 *
 * Az éles és a sandbox környezet teljesen elkülönül: külön fiók, külön
 * alkalmazásregisztráció, külön kulcsok. Ezért a hosztokat egy helyen,
 * a környezet nevéből oldjuk fel, hogy ne lehessen félrekonfigurálni.
 */
final class Config
{
    private const HOSTS = [
        'production' => [
            'api'  => 'https://api.allegro.pl',
            'auth' => 'https://allegro.pl/auth/oauth',
            'web'  => 'https://allegro.hu',
        ],
        'sandbox' => [
            'api'  => 'https://api.allegro.pl.allegrosandbox.pl',
            'auth' => 'https://allegro.pl.allegrosandbox.pl/auth/oauth',
            'web'  => 'https://allegro.hu.allegrosandbox.pl',
        ],
    ];

    /** Az Allegro által elfogadott Accept-Language értékek. */
    public const LANGUAGES = ['en-US', 'pl-PL', 'uk-UA', 'sk-SK', 'cs-CZ', 'hu-HU'];

    /** @param array<string,string> $values */
    private function __construct(
        private readonly array $values,
        public readonly string $rootDir,
    ) {
    }

    public static function load(string $rootDir): self
    {
        $values = [];

        $envFile = $rootDir . '/.env';
        if (is_file($envFile)) {
            $values = self::parseEnvFile($envFile);
        }

        // A valódi környezeti változó erősebb, mint a .env – így a CI és a
        // cron felül tudja írni anélkül, hogy fájlt kellene szerkeszteni.
        foreach (array_keys($values) as $key) {
            $fromEnv = getenv($key);
            if ($fromEnv !== false && $fromEnv !== '') {
                $values[$key] = $fromEnv;
            }
        }

        return new self($values, $rootDir);
    }

    /** @return array<string,string> */
    private static function parseEnvFile(string $path): array
    {
        $out = [];
        $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        if ($lines === false) {
            throw new RuntimeException("A .env nem olvasható: {$path}");
        }

        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '' || str_starts_with($line, '#')) {
                continue;
            }
            $eq = strpos($line, '=');
            if ($eq === false) {
                continue;
            }
            $key = trim(substr($line, 0, $eq));
            $val = trim(substr($line, $eq + 1));

            // Idézőjelek leszedése, ha a teljes értéket körbeveszik.
            $len = strlen($val);
            if ($len >= 2) {
                $first = $val[0];
                $last = $val[$len - 1];
                if (($first === '"' && $last === '"') || ($first === "'" && $last === "'")) {
                    $val = substr($val, 1, -1);
                }
            }

            $out[$key] = $val;
        }

        return $out;
    }

    public function get(string $key, ?string $default = null): ?string
    {
        $value = $this->values[$key] ?? null;
        if ($value === null || $value === '') {
            return $default;
        }

        return $value;
    }

    public function require(string $key): string
    {
        $value = $this->get($key);
        if ($value === null) {
            throw new RuntimeException(
                "Hiányzó beállítás: {$key}. Másold a .env.example fájlt .env néven és töltsd ki."
            );
        }

        return $value;
    }

    public function environment(): string
    {
        $env = $this->get('ALLEGRO_ENV', 'sandbox');
        if (!isset(self::HOSTS[$env])) {
            throw new RuntimeException(
                "Ismeretlen ALLEGRO_ENV: {$env}. Érvényes: sandbox, production."
            );
        }

        return $env;
    }

    public function isProduction(): bool
    {
        return $this->environment() === 'production';
    }

    public function apiBase(): string
    {
        return self::HOSTS[$this->environment()]['api'];
    }

    public function authBase(): string
    {
        return self::HOSTS[$this->environment()]['auth'];
    }

    public function webBase(): string
    {
        return self::HOSTS[$this->environment()]['web'];
    }

    public function clientId(): string
    {
        return $this->require('ALLEGRO_CLIENT_ID');
    }

    public function clientSecret(): string
    {
        return $this->require('ALLEGRO_CLIENT_SECRET');
    }

    public function language(): string
    {
        $lang = $this->get('ALLEGRO_LANGUAGE', 'hu-HU');
        if (!in_array($lang, self::LANGUAGES, true)) {
            throw new RuntimeException(
                "Nem támogatott ALLEGRO_LANGUAGE: {$lang}. Érvényes: " . implode(', ', self::LANGUAGES)
            );
        }

        return $lang;
    }

    /**
     * A User-Agent kötelező, és a formátuma kötött. Itt validáljuk, mert egy
     * rosszul beállított User-Agent nem hibaüzenetet hoz, hanem – a portál
     * figyelmeztetése szerint – akár IP-blokkot.
     */
    public function userAgent(): string
    {
        $ua = $this->require('ALLEGRO_USER_AGENT');

        if (!preg_match('#^\S+/\S+\s+\(\+https?://\S+\)$#', $ua)) {
            throw new RuntimeException(
                "Az ALLEGRO_USER_AGENT formátuma hibás.\n"
                . "Elvárt:  Nev/Verzio (+https://url)\n"
                . "Kapott:  {$ua}\n"
                . 'Validátor: https://apps.developer.allegro.pl/user-agent'
            );
        }

        return $ua;
    }

    public function rateLimitPerMinute(): int
    {
        return max(1, (int) ($this->get('ALLEGRO_RATE_LIMIT_PER_MINUTE', '4000') ?? '4000'));
    }

    public function invoiceDriver(): string
    {
        return $this->get('INVOICE_DRIVER', 'none') ?? 'none';
    }

    public function varDir(): string
    {
        $dir = $this->rootDir . '/var';
        if (!is_dir($dir) && !mkdir($dir, 0775, true) && !is_dir($dir)) {
            throw new RuntimeException("Nem hozható létre a munkakönyvtár: {$dir}");
        }

        return $dir;
    }

    /**
     * Az állapottár környezetenként külön fájl. Ez szándékos: a sandbox
     * offerId-k semmit nem jelentenek élesben, összekeverni őket adatvesztés.
     */
    public function statePath(): string
    {
        return $this->varDir() . '/state-' . $this->environment() . '.sqlite';
    }
}
