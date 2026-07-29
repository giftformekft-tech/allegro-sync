<?php

declare(strict_types=1);

namespace AllegroSync\Support;

final class Uuid
{
    /** Véletlen v4 UUID – új parancsokhoz. */
    public static function v4(): string
    {
        $bytes = random_bytes(16);
        $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
        $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);

        return self::format($bytes);
    }

    /**
     * Névből képzett, determinisztikus UUID (v5-szerű, SHA-1 alapon).
     *
     * Ez a tömeges műveleteknél kulcsfontosságú: a commandId egyben
     * idempotencia-kulcs, tehát egy újrafuttatásnak UGYANAZT a commandId-t
     * kell előállítania, különben a parancs kétszer hajtódik végre.
     */
    public static function v5(string $namespace, string $name): string
    {
        $hash = sha1($namespace . '|' . $name, true);
        $bytes = substr($hash, 0, 16);
        $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x50);
        $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);

        return self::format($bytes);
    }

    private static function format(string $bytes): string
    {
        $hex = bin2hex($bytes);

        return sprintf(
            '%s-%s-%s-%s-%s',
            substr($hex, 0, 8),
            substr($hex, 8, 4),
            substr($hex, 12, 4),
            substr($hex, 16, 4),
            substr($hex, 20, 12),
        );
    }
}
