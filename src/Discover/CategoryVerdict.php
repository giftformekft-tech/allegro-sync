<?php

declare(strict_types=1);

namespace AllegroSync\Discover;

/**
 * Egy kategória alkalmassági ítélete EAN nélküli listázásra.
 */
final class CategoryVerdict
{
    public const OK = 'ok';
    public const BLOCKED = 'blocked';
    public const RISKY = 'risky';

    /**
     * @param list<string> $requiredParameters
     */
    public function __construct(
        public readonly string $id,
        public readonly string $name,
        public readonly string $path,
        public readonly bool $productCreationEnabled,
        public readonly bool $offersWithProductPublicationEnabled,
        public readonly bool $gtinPresent,
        public readonly bool $gtinRequired,
        public readonly array $requiredParameters = [],
        public readonly ?string $error = null,
    ) {
    }

    public function verdict(): string
    {
        if ($this->error !== null) {
            return self::RISKY;
        }

        // A GTIN kötelezősége az abszolút kizáró ok: nincs és nem is lesz EAN.
        if ($this->gtinRequired) {
            return self::BLOCKED;
        }

        // Saját katalógustermék nélkül nem tudunk mihez kötni ajánlatot,
        // ha a kategória katalógushoz kötést vár.
        if (!$this->productCreationEnabled) {
            return self::BLOCKED;
        }

        if (!$this->offersWithProductPublicationEnabled) {
            return self::RISKY;
        }

        // A GTIN létezik paraméterként, csak épp nem kötelező. Ez ma működik,
        // de pont ez az a kategória, amit a GTIN-őrszemnek figyelnie kell.
        if ($this->gtinPresent) {
            return self::RISKY;
        }

        return self::OK;
    }

    public function verdictLabel(): string
    {
        return match ($this->verdict()) {
            self::OK => 'OK – EAN nélkül listázható',
            self::RISKY => 'FIGYELNI – működik, de van GTIN-paraméter',
            self::BLOCKED => 'ZÁRT – nem járható EAN nélkül',
            default => '?',
        };
    }

    public function reason(): string
    {
        if ($this->error !== null) {
            return 'Nem ellenőrizhető: ' . $this->error;
        }
        if ($this->gtinRequired) {
            return 'A GTIN kötelező paraméter.';
        }
        if (!$this->productCreationEnabled) {
            return 'Nem javasolható saját termék (productCreationEnabled=false).';
        }
        if (!$this->offersWithProductPublicationEnabled) {
            return 'Termékhez kötött ajánlat nem publikálható.';
        }
        if ($this->gtinPresent) {
            return 'A GTIN létezik, de nem kötelező – kötelezővé válhat.';
        }

        return 'Nincs GTIN-követelmény, saját termék javasolható.';
    }
}
