<?php

declare(strict_types=1);

namespace AllegroSync\Cli;

interface Command
{
    public static function name(): string;

    public static function description(): string;

    /** @return int kilépési kód */
    public function run(Context $context, Arguments $args): int;
}
