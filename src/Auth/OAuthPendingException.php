<?php

declare(strict_types=1);

namespace AllegroSync\Auth;

use RuntimeException;

/**
 * A device flow alatti "még nem hagyta jóvá" állapot.
 *
 * Nem hiba: a pollozó ciklus ezt várja, amíg a felhasználó a böngészőben
 * jóvá nem hagyja a hozzáférést.
 */
final class OAuthPendingException extends RuntimeException
{
    public function __construct(public readonly bool $slowDown = false)
    {
        parent::__construct($slowDown ? 'slow_down' : 'authorization_pending');
    }
}
