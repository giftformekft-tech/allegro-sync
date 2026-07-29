<?php

declare(strict_types=1);

namespace AllegroSync\Invoice;

final class IssuedInvoice
{
    public function __construct(
        public readonly string $invoiceNumber,
        public readonly string $pdfContents,
        public readonly string $fileName = 'invoice.pdf',
    ) {
    }

    /** Az Allegro 3 MB-nál nagyobb PDF-et nem fogad (413). */
    public function exceedsAllegroLimit(): bool
    {
        return strlen($this->pdfContents) > 3 * 1024 * 1024;
    }
}
