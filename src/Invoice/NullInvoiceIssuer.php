<?php

declare(strict_types=1);

namespace AllegroSync\Invoice;

use RuntimeException;

/**
 * Alapértelmezett számlázó: nincs bekötve.
 *
 * Szándékosan dob, ha mégis meghívnák – a néma nem-számlázás sokkal
 * veszélyesebb lenne, mint egy egyértelmű hiba.
 */
final class NullInvoiceIssuer implements InvoiceIssuer
{
    public function isEnabled(): bool
    {
        return false;
    }

    public function issue(array $order): IssuedInvoice
    {
        throw new RuntimeException(
            'A számlázás nincs bekötve (INVOICE_DRIVER=none). '
            . 'A rendelésszinkron ilyenkor nem állít ki számlát.'
        );
    }
}
