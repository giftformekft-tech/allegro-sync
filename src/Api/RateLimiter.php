<?php

declare(strict_types=1);

namespace AllegroSync\Api;

/**
 * Csúszóablakos kérésszámláló.
 *
 * Az Allegro főlimitje 9000 kérés/perc Client ID-nként, és túllépésnél
 * EGY PERCRE blokkolja a Client ID-t. Egy perc teljes leállás sokkal
 * drágább, mint néhány ezredmásodperc várakozás, ezért itt inkább
 * konzervatívan fékezünk.
 *
 * Ez a mechanizmus a folyamaton belüli forgalmat szabályozza. Ha több
 * példány fut párhuzamosan, a limitet közöttük el kell osztani – ezért
 * konfigurálható, és alapból a valós limit fele.
 */
final class RateLimiter
{
    /** @var list<float> a kérések időbélyegei az elmúlt ablakban */
    private array $timestamps = [];

    public function __construct(
        private readonly int $maxPerMinute,
        private readonly float $windowSeconds = 60.0,
    ) {
    }

    /** Blokkol, amíg a következő kérés belefér az ablakba. */
    public function acquire(): void
    {
        $now = microtime(true);
        $this->prune($now);

        if (count($this->timestamps) < $this->maxPerMinute) {
            $this->timestamps[] = $now;

            return;
        }

        // Meg kell várni, amíg a legrégebbi kérés kicsúszik az ablakból.
        $oldest = $this->timestamps[0];
        $waitSeconds = ($oldest + $this->windowSeconds) - $now;

        if ($waitSeconds > 0) {
            usleep((int) ceil($waitSeconds * 1_000_000));
        }

        $now = microtime(true);
        $this->prune($now);
        $this->timestamps[] = $now;
    }

    private function prune(float $now): void
    {
        $cutoff = $now - $this->windowSeconds;
        while ($this->timestamps !== [] && $this->timestamps[0] <= $cutoff) {
            array_shift($this->timestamps);
        }
    }
}
