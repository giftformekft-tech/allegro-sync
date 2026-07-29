<?php

declare(strict_types=1);

namespace AllegroSync\Invoice;

use AllegroSync\Api\ApiException;
use AllegroSync\Api\Client;
use AllegroSync\Support\Logger;
use RuntimeException;

/**
 * A kiállított számla feltöltése az Allegróra.
 *
 * Ez a rész már kész, mert az Allegro-oldal független attól, hogy melyik
 * számlázó gyártotta a PDF-et.
 *
 * Három megkötést tart be, ami a dokumentációból jön:
 *
 *  1. A metaadat és a fájl PÁRBAN, sorosan megy. A metaadat-létrehozás 429-et
 *     ad, ha az előzőhöz még nem tartozik feltöltött fájl – tehát tilos előbb
 *     az összes metaadatot legyártani.
 *  2. A PDF legfeljebb 3 MB (fölötte 413).
 *  3. A 409-ek nem hibák: "a rendelésnek már van számlája", illetve "a
 *     számlához már van fájl". Újrafuttatásnál ez a normális válasz.
 */
final class InvoiceUploader
{
    public function __construct(
        private readonly Client $client,
        private readonly Logger $logger,
    ) {
    }

    /**
     * @return string|null az Allegro invoiceId, vagy null, ha már volt számla
     */
    public function upload(string $orderId, IssuedInvoice $invoice): ?string
    {
        if ($invoice->exceedsAllegroLimit()) {
            throw new RuntimeException(sprintf(
                'A számla PDF %d bájt, az Allegro korlátja 3 MB. Rendelés: %s',
                strlen($invoice->pdfContents),
                $orderId,
            ));
        }

        $invoiceId = $this->createMetadata($orderId, $invoice);

        if ($invoiceId === null) {
            $this->logger->info("A(z) {$orderId} rendelésnek már van eladói számlája – kihagyva.");

            return null;
        }

        $this->uploadFile($orderId, $invoiceId, $invoice);

        return $invoiceId;
    }

    private function createMetadata(string $orderId, IssuedInvoice $invoice): ?string
    {
        try {
            $response = $this->client->post(
                '/order/checkout-forms/' . rawurlencode($orderId) . '/invoices',
                [
                    'file' => ['name' => $invoice->fileName],
                    'invoiceNumber' => $invoice->invoiceNumber,
                ],
            );
        } catch (ApiException $e) {
            // 409: a rendelésnek már van eladói számlája.
            if ($e->status === 409) {
                return null;
            }

            throw $e;
        }

        $data = $response->json();
        $id = isset($data['id']) ? (string) $data['id'] : '';

        if ($id === '') {
            throw new RuntimeException("A számla-metaadat válaszából hiányzik az azonosító. Rendelés: {$orderId}");
        }

        return $id;
    }

    private function uploadFile(string $orderId, string $invoiceId, IssuedInvoice $invoice): void
    {
        try {
            $this->client->putBinary(
                '/order/checkout-forms/' . rawurlencode($orderId)
                . '/invoices/' . rawurlencode($invoiceId) . '/file',
                $invoice->pdfContents,
                'application/pdf',
            );
        } catch (ApiException $e) {
            // 409: ehhez a számlához már van feltöltött fájl.
            if ($e->status === 409) {
                $this->logger->info("A(z) {$invoiceId} számlához már van fájl – kihagyva.");

                return;
            }

            throw $e;
        }
    }
}
