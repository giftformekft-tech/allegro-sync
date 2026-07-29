<?php

declare(strict_types=1);

namespace AllegroSync\Cli;

/**
 * Minimál argumentumfeldolgozó: `--kulcs=ertek`, `--kapcsolo` és pozicionális.
 */
final class Arguments
{
    /** @var array<string,string|bool> */
    private array $options = [];

    /** @var list<string> */
    private array $positional = [];

    /** @param list<string> $argv a parancsnév UTÁNI elemek */
    public function __construct(array $argv)
    {
        foreach ($argv as $arg) {
            if (!str_starts_with($arg, '--')) {
                $this->positional[] = $arg;

                continue;
            }

            $arg = substr($arg, 2);
            $eq = strpos($arg, '=');

            if ($eq === false) {
                $this->options[$arg] = true;

                continue;
            }

            $this->options[substr($arg, 0, $eq)] = substr($arg, $eq + 1);
        }
    }

    public function option(string $name, ?string $default = null): ?string
    {
        $value = $this->options[$name] ?? null;
        if ($value === null || $value === true) {
            return $value === true ? '' : $default;
        }

        return $value;
    }

    public function flag(string $name): bool
    {
        return isset($this->options[$name]);
    }

    public function positional(int $index, ?string $default = null): ?string
    {
        return $this->positional[$index] ?? $default;
    }

    /** @return list<string> */
    public function all(): array
    {
        return $this->positional;
    }
}
