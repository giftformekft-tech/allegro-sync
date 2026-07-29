<?php

declare(strict_types=1);

namespace AllegroSync\Api;

use JsonException;

final class Response
{
    /** @param array<string,string> $headers kisbetűs kulcsokkal */
    public function __construct(
        public readonly int $status,
        public readonly string $body,
        public readonly array $headers = [],
    ) {
    }

    public function header(string $name): ?string
    {
        return $this->headers[strtolower($name)] ?? null;
    }

    /**
     * Minden Allegro-válasz tartalmaz Trace-Id-t, ami egyedileg azonosítja a
     * kérést. Hibabejelentésnél ezt kérik, ezért mindent ezzel naplózunk.
     */
    public function traceId(): ?string
    {
        return $this->header('trace-id');
    }

    /** A 201/202 válaszok itt adják vissza a létrehozott erőforrás helyét. */
    public function location(): ?string
    {
        return $this->header('location');
    }

    public function isSuccess(): bool
    {
        return $this->status >= 200 && $this->status < 300;
    }

    /** @return array<mixed> */
    public function json(): array
    {
        if (trim($this->body) === '') {
            return [];
        }

        try {
            $decoded = json_decode($this->body, true, 512, JSON_THROW_ON_ERROR);
        } catch (JsonException $e) {
            throw new ApiException(
                'A válasz nem érvényes JSON: ' . $e->getMessage(),
                $this->status,
                [],
                $this->traceId(),
                $this->body,
            );
        }

        return is_array($decoded) ? $decoded : [];
    }
}
