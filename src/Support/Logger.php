<?php

declare(strict_types=1);

namespace AllegroSync\Support;

/**
 * Kétcsatornás napló: az ember a terminálon látja a lényeget, a részletes
 * nyom (benne minden Trace-Id) fájlba megy, mert hibabejelentésnél az kell.
 */
final class Logger
{
    public const LEVELS = ['debug' => 10, 'info' => 20, 'warn' => 30, 'error' => 40];

    private mixed $fileHandle = null;

    public function __construct(
        private readonly string $consoleLevel = 'info',
        private readonly ?string $logFile = null,
    ) {
        if ($this->logFile !== null) {
            $dir = dirname($this->logFile);
            if (!is_dir($dir)) {
                @mkdir($dir, 0775, true);
            }
            $handle = @fopen($this->logFile, 'ab');
            $this->fileHandle = $handle === false ? null : $handle;
        }
    }

    public function debug(string $message): void
    {
        $this->log('debug', $message);
    }

    public function info(string $message): void
    {
        $this->log('info', $message);
    }

    public function warn(string $message): void
    {
        $this->log('warn', $message);
    }

    public function error(string $message): void
    {
        $this->log('error', $message);
    }

    private function log(string $level, string $message): void
    {
        $line = sprintf('[%s] %-5s %s', date('Y-m-d H:i:s'), strtoupper($level), $message);

        if ($this->fileHandle !== null) {
            fwrite($this->fileHandle, $line . PHP_EOL);
        }

        $threshold = self::LEVELS[$this->consoleLevel] ?? 20;
        if ((self::LEVELS[$level] ?? 20) < $threshold) {
            return;
        }

        // A figyelmeztetés és a hiba stderr-re megy, hogy a hasznos kimenetet
        // (pl. a felderítő tábláját) pipe-olni lehessen anélkül, hogy a zaj
        // belekeveredne.
        $stream = in_array($level, ['warn', 'error'], true) ? STDERR : STDOUT;
        fwrite($stream, $line . PHP_EOL);
    }
}
