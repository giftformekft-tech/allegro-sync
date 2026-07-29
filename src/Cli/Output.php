<?php

declare(strict_types=1);

namespace AllegroSync\Cli;

final class Output
{
    private bool $colors;

    public function __construct(?bool $colors = null)
    {
        $this->colors = $colors ?? (function_exists('posix_isatty') && @posix_isatty(STDOUT));
    }

    public function write(string $text = ''): void
    {
        fwrite(STDOUT, $text . PHP_EOL);
    }

    public function error(string $text): void
    {
        fwrite(STDERR, $this->paint($text, '31') . PHP_EOL);
    }

    public function success(string $text): void
    {
        $this->write($this->paint($text, '32'));
    }

    public function warn(string $text): void
    {
        $this->write($this->paint($text, '33'));
    }

    public function dim(string $text): void
    {
        $this->write($this->paint($text, '90'));
    }

    public function heading(string $text): void
    {
        $this->write('');
        $this->write($this->paint($text, '1;36'));
        $this->write($this->paint(str_repeat('─', mb_strlen($text)), '90'));
    }

    public function paint(string $text, string $code): string
    {
        if (!$this->colors) {
            return $text;
        }

        return "\033[{$code}m{$text}\033[0m";
    }

    /**
     * Egyszerű oszlopos tábla. A szélességet a tartalom adja, hogy a
     * kimenet terminálban és fájlba mentve is olvasható legyen.
     *
     * @param list<string>       $headers
     * @param list<list<string>> $rows
     */
    public function table(array $headers, array $rows): void
    {
        $widths = [];
        foreach ($headers as $i => $header) {
            $widths[$i] = mb_strlen($header);
        }
        foreach ($rows as $row) {
            foreach ($row as $i => $cell) {
                $widths[$i] = max($widths[$i] ?? 0, mb_strlen($cell));
            }
        }

        $line = [];
        foreach ($headers as $i => $header) {
            $line[] = $this->pad($header, $widths[$i]);
        }
        $this->write($this->paint(implode('  ', $line), '1'));

        $sep = [];
        foreach ($widths as $width) {
            $sep[] = str_repeat('─', $width);
        }
        $this->write($this->paint(implode('  ', $sep), '90'));

        foreach ($rows as $row) {
            $line = [];
            foreach ($row as $i => $cell) {
                $line[] = $this->pad($cell, $widths[$i] ?? 0);
            }
            $this->write(rtrim(implode('  ', $line)));
        }
    }

    private function pad(string $text, int $width): string
    {
        $pad = $width - mb_strlen($text);

        return $pad > 0 ? $text . str_repeat(' ', $pad) : $text;
    }
}
