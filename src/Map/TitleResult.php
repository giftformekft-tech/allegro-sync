<?php

declare(strict_types=1);

namespace AllegroSync\Map;

final class TitleResult
{
    public function __construct(
        public readonly string $title,
        public readonly bool $valid,
        public readonly ?string $problem,
    ) {
    }
}
