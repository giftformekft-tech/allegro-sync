<?php

declare(strict_types=1);

namespace AllegroSync\Map;

/**
 * Ajánlatcím képzése az Allegro szabályai szerint.
 *
 * A `name` mező kötött: 12–75 karakter (szóközökkel együtt), és LEGALÁBB
 * HÁROM SZÓ. Ezt könnyű elrontani – a naiv csonkolás szó közepén vág, a
 * rövid mintanevek pedig a három szavas minimumon buknak el. Ezért van
 * külön modul, saját tesztekkel: itt a csendes hiba több ezer hibás
 * ajánlatot jelentene.
 *
 * A képzés prioritási sorrendben épít, és túlcsordulásnál a legkevésbé
 * fontos részt dobja el először.
 */
final class TitleBuilder
{
    public const MIN_LENGTH = 12;
    public const MAX_LENGTH = 75;
    public const MIN_WORDS = 3;

    /**
     * @param list<string> $parts prioritási sorrendben (a legfontosabb elöl)
     */
    public function build(array $parts): TitleResult
    {
        $parts = $this->clean($parts);

        if ($parts === []) {
            return new TitleResult('', false, 'Nincs miből címet képezni.');
        }

        // 1. Minden rész belefér?
        $full = implode(' ', $parts);
        if ($this->length($full) <= self::MAX_LENGTH) {
            return $this->finalise($full);
        }

        // 2. Hátulról dobálunk el részeket, amíg befér.
        $kept = $parts;
        while (count($kept) > 1) {
            array_pop($kept);
            $candidate = implode(' ', $kept);
            if ($this->length($candidate) <= self::MAX_LENGTH) {
                return $this->finalise($candidate);
            }
        }

        // 3. Már csak az első rész van, és az is hosszú – szóhatáron vágunk.
        return $this->finalise($this->truncateAtWord($kept[0], self::MAX_LENGTH));
    }

    /**
     * Ütközésfeloldás: ha két variáns azonos címet kapna, a megkülönböztető
     * utótagot úgy fűzzük hozzá, hogy a hossz-korlát ne sérüljön.
     */
    public function withSuffix(string $title, string $suffix): TitleResult
    {
        $suffix = trim($suffix);
        if ($suffix === '') {
            return $this->finalise($title);
        }

        $room = self::MAX_LENGTH - $this->length($suffix) - 1;
        if ($room < 1) {
            return new TitleResult($title, false, 'Az utótag önmagában hosszabb a korlátnál.');
        }

        $base = $this->length($title) <= $room
            ? $title
            : $this->truncateAtWord($title, $room);

        return $this->finalise($base . ' ' . $suffix);
    }

    private function finalise(string $title): TitleResult
    {
        $title = $this->collapse($title);
        $length = $this->length($title);
        $words = $this->wordCount($title);

        if ($length > self::MAX_LENGTH) {
            return new TitleResult($title, false, "A cím {$length} karakter, a korlát " . self::MAX_LENGTH . '.');
        }

        if ($length < self::MIN_LENGTH) {
            return new TitleResult(
                $title,
                false,
                "A cím {$length} karakter, a minimum " . self::MIN_LENGTH . '. Bővítsd a terméknevet.',
            );
        }

        if ($words < self::MIN_WORDS) {
            return new TitleResult(
                $title,
                false,
                "A cím {$words} szóból áll, a minimum " . self::MIN_WORDS . '. Bővítsd a terméknevet.',
            );
        }

        return new TitleResult($title, true, null);
    }

    /**
     * Szóhatáron vágás. Ha az első szó önmagában hosszabb a keretnél, akkor
     * kénytelenek vagyunk karakteren vágni – de ez a ritka eset.
     */
    private function truncateAtWord(string $text, int $max): string
    {
        if ($this->length($text) <= $max) {
            return $text;
        }

        $words = preg_split('/\s+/u', trim($text)) ?: [];
        $out = '';

        foreach ($words as $word) {
            $candidate = $out === '' ? $word : $out . ' ' . $word;
            if ($this->length($candidate) > $max) {
                break;
            }
            $out = $candidate;
        }

        if ($out === '') {
            return mb_substr($text, 0, $max);
        }

        return $out;
    }

    /**
     * @param list<string> $parts
     *
     * @return list<string>
     */
    private function clean(array $parts): array
    {
        $out = [];

        foreach ($parts as $part) {
            $part = $this->collapse($part);
            if ($part === '') {
                continue;
            }

            // Ismétlődő rész (pl. a mintanévben már benne van a típus) csak
            // hosszabbítana, értelmet nem adna hozzá. Nem elég a részeket
            // egymással összevetni: a "Cica Póló" névben a "Póló" típus már
            // BENNE van, tehát a már összegyűjtött szövegben kell keresni.
            if ($out !== [] && $this->isRedundant($part, implode(' ', $out))) {
                continue;
            }

            $out[] = $part;
        }

        return $out;
    }

    /**
     * Benne van-e a rész önálló szóként a már összegyűjtött szövegben?
     *
     * A rövid (1–2 karakteres) részeket szándékosan kihagyjuk az
     * ellenőrzésből: egy "M" méret könnyen egybeesne a névben szereplő
     * betűvel, és a méret elhagyása sokkal károsabb, mint egy ismétlés.
     */
    private function isRedundant(string $part, string $accumulated): bool
    {
        if ($this->length($part) <= 2) {
            return false;
        }

        $pattern = '/(?<!\S)' . preg_quote(mb_strtolower($part), '/') . '(?!\S)/u';

        return preg_match($pattern, mb_strtolower($accumulated)) === 1;
    }

    private function collapse(string $text): string
    {
        $text = preg_replace('/\s+/u', ' ', $text) ?? $text;

        return trim($text);
    }

    private function length(string $text): int
    {
        return mb_strlen($text);
    }

    private function wordCount(string $text): int
    {
        $words = preg_split('/\s+/u', trim($text), -1, PREG_SPLIT_NO_EMPTY);

        return $words === false ? 0 : count($words);
    }
}
