<?php

declare(strict_types=1);

namespace AllegroSync\Invoice;

/**
 * A számlázó illesztési pontja.
 *
 * A számlázás EGYELŐRE NINCS BEKÖTVE – ez a felület azért van itt, hogy a
 * bekötés ne igényeljen átépítést. A rendelésszinkron majd ezen keresztül
 * kér számlát, és nem tud róla, hogy szamlazz.hu van mögötte.
 *
 * A bekötés sorrendje, ha majd sorra kerül:
 *   1. SzamlazzInvoiceIssuer kitöltése a Számla Agent XML szerint
 *   2. INVOICE_DRIVER=szamlazz a .env-ben
 *   3. Az Allegro-oldali feltöltést az InvoiceUploader végzi – az már kész
 */
interface InvoiceIssuer
{
    public function isEnabled(): bool;

    /**
     * Számla kiállítása egy rendelésre.
     *
     * @param array<string,mixed> $order az Allegro checkout-form adatai
     */
    public function issue(array $order): IssuedInvoice;
}
