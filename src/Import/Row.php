<?php

declare(strict_types=1);

namespace AllegroSync\Import;

/**
 * Egy termékvariáns a forme.hu exportjából.
 */
final class Row
{
    /** @param list<string> $imageUrls */
    public function __construct(
        public readonly int $lineNumber,
        public readonly string $sku,
        public readonly string $parentSku,
        public readonly string $name,
        public readonly string $description,
        public readonly string $type,
        /** Olvasható megnevezés a címhez ("Póló"), szemben a slug-gal ("polo"). */
        public readonly string $typeLabel,
        public readonly string $color,
        public readonly string $size,
        public readonly string $priceHuf,
        public readonly int $stock,
        public readonly array $imageUrls,
        public readonly ?int $weightGrams,
        public readonly string $brand,
        public readonly string $material,
        public readonly bool $aiContent,
    ) {
    }

    public function primaryImage(): ?string
    {
        return $this->imageUrls[0] ?? null;
    }
}
