<?php

declare(strict_types=1);

namespace AllegroSync\Api;

use RuntimeException;

/**
 * Az Allegro hibamodellje köré húzott kivétel.
 *
 * Két hibaformátum létezik: az általános `errors[]` tömb, és az OAuth2
 * `error` / `error_description` páros (csak 401-nél). Mindkettőt itt
 * olvassuk ki, hogy a hívó oldalon egységes legyen a kezelés.
 *
 * A `path` mező azért fontos, mert megmondja, MELYIK mező hibás – ezt
 * vezetjük vissza a CSV sorára a riportban.
 */
final class ApiException extends RuntimeException
{
    /** @param array<int,array<string,mixed>> $errors */
    public function __construct(
        string $message,
        public readonly int $status,
        public readonly array $errors = [],
        public readonly ?string $traceId = null,
        public readonly ?string $rawBody = null,
    ) {
        parent::__construct($message, $status);
    }

    public static function fromResponse(Response $response): self
    {
        $body = $response->body;
        $decoded = json_decode($body, true);
        $errors = [];
        $message = 'HTTP ' . $response->status;

        if (is_array($decoded)) {
            if (isset($decoded['errors']) && is_array($decoded['errors'])) {
                $errors = $decoded['errors'];
                $parts = [];
                foreach ($errors as $error) {
                    $parts[] = self::formatError($error);
                }
                if ($parts !== []) {
                    $message = implode(' | ', $parts);
                }
            } elseif (isset($decoded['error'])) {
                // OAuth2 formátum
                $message = (string) $decoded['error'];
                if (isset($decoded['error_description'])) {
                    $message .= ': ' . (string) $decoded['error_description'];
                }
                $errors = [$decoded];
            }
        }

        if ($message === 'HTTP ' . $response->status && $body !== '') {
            $message .= ' – ' . mb_substr($body, 0, 300);
        }

        return new self($message, $response->status, $errors, $response->traceId(), $body);
    }

    /** @param array<string,mixed> $error */
    private static function formatError(array $error): string
    {
        $code = isset($error['code']) ? (string) $error['code'] : '?';

        // A userMessage a felhasználónak szánt, olvasható szöveg; ha nincs,
        // a fejlesztői message-re esünk vissza.
        $text = '';
        foreach (['userMessage', 'message'] as $key) {
            if (isset($error[$key]) && is_string($error[$key]) && $error[$key] !== '') {
                $text = $error[$key];
                break;
            }
        }

        $out = $code . ': ' . $text;

        if (isset($error['path']) && is_string($error['path']) && $error['path'] !== '') {
            $out .= ' [' . $error['path'] . ']';
        }

        return $out;
    }

    /** Az első hibakód – ezen szoktunk elágazni. */
    public function code(): ?string
    {
        $first = $this->errors[0] ?? null;
        if (is_array($first) && isset($first['code']) && is_string($first['code'])) {
            return $first['code'];
        }

        return null;
    }

    public function hasCode(string $code): bool
    {
        foreach ($this->errors as $error) {
            if (isset($error['code']) && $error['code'] === $code) {
                return true;
            }
        }

        return false;
    }
}
