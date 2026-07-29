#!/usr/bin/env php
<?php

declare(strict_types=1);

/**
 * Minimál tesztfuttató – szándékosan függőség nélkül, hogy a
 * `composer install` ne legyen előfeltétel.
 *
 * Használat: php tests/run.php
 */

$root = dirname(__DIR__);

spl_autoload_register(static function (string $class) use ($root): void {
    $prefix = 'AllegroSync\\';
    if (!str_starts_with($class, $prefix)) {
        return;
    }
    $path = $root . '/src/' . str_replace('\\', '/', substr($class, strlen($prefix))) . '.php';
    if (is_file($path)) {
        require $path;
    }
});

final class TestRunner
{
    private int $passed = 0;
    /** @var list<string> */
    private array $failures = [];
    private string $group = '';

    public function group(string $name): void
    {
        $this->group = $name;
        echo "\n" . $name . "\n" . str_repeat('-', strlen($name)) . "\n";
    }

    public function assert(bool $condition, string $description): void
    {
        if ($condition) {
            $this->passed++;
            echo "  ok    {$description}\n";

            return;
        }

        $this->failures[] = $this->group . ' :: ' . $description;
        echo "  FAIL  {$description}\n";
    }

    public function same(mixed $expected, mixed $actual, string $description): void
    {
        if ($expected === $actual) {
            $this->passed++;
            echo "  ok    {$description}\n";

            return;
        }

        $this->failures[] = sprintf(
            "%s :: %s\n        várt:   %s\n        kapott: %s",
            $this->group,
            $description,
            var_export($expected, true),
            var_export($actual, true),
        );
        echo "  FAIL  {$description}\n";
        echo '        várt:   ' . var_export($expected, true) . "\n";
        echo '        kapott: ' . var_export($actual, true) . "\n";
    }

    public function summary(): int
    {
        echo "\n";
        if ($this->failures === []) {
            echo "Mind a {$this->passed} teszt átment.\n";

            return 0;
        }

        echo count($this->failures) . " teszt elbukott (" . $this->passed . " átment):\n";
        foreach ($this->failures as $failure) {
            echo '  - ' . $failure . "\n";
        }

        return 1;
    }
}

$t = new TestRunner();

require __DIR__ . '/TitleBuilderTest.php';
require __DIR__ . '/CsvReaderTest.php';

exit($t->summary());
