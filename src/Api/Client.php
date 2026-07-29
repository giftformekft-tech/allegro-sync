<?php

declare(strict_types=1);

namespace AllegroSync\Api;

use AllegroSync\Config\Config;
use AllegroSync\Support\Logger;
use Closure;
use RuntimeException;

/**
 * Az Allegro REST API kliense.
 *
 * Itt lakik minden kötelező viselkedés, hogy egyetlen hívási hely se
 * felejthesse el:
 *
 *  - User-Agent (a Szabályzat 3.4(c) szerint kötelező, hiánya IP-blokkot vonhat)
 *  - erőforrás-verzió az Accept és Content-Type fejlécben
 *  - Accept-Language
 *  - kéréskorlát-fékezés és 429-kezelés
 *  - Trace-Id naplózása minden válaszból
 *  - egységes hibamodell
 */
final class Client
{
    public const VENDOR_PUBLIC = 'application/vnd.allegro.public.v1+json';
    public const VENDOR_BETA = 'application/vnd.allegro.beta.v1+json';

    private const MAX_RETRIES = 4;

    /** @var Closure():?string */
    private Closure $tokenProvider;

    private ?string $languageOverride = null;

    public function __construct(
        private readonly Config $config,
        private readonly Logger $logger,
        private readonly RateLimiter $rateLimiter,
        ?callable $tokenProvider = null,
    ) {
        $this->tokenProvider = $tokenProvider !== null
            ? Closure::fromCallable($tokenProvider)
            : static fn (): ?string => null;
    }

    public function withToken(callable $tokenProvider): self
    {
        $clone = clone $this;
        $clone->tokenProvider = Closure::fromCallable($tokenProvider);

        return $clone;
    }

    /**
     * Nyelv felülbírálása erre a kliensre.
     *
     * Nem minden erőforrás fogad minden nyelvet – a
     * `/sale/category-parameters-scheduled-changes` például CSAK `pl-PL`-t,
     * és rossz értékre 406-ot ad.
     */
    public function withLanguage(string $language): self
    {
        $clone = clone $this;
        $clone->languageOverride = $language;

        return $clone;
    }

    /** @param array<string,scalar|array<int,scalar>> $query */
    public function get(string $path, array $query = [], string $accept = self::VENDOR_PUBLIC): Response
    {
        return $this->request('GET', $path, $query, null, $accept);
    }

    /** @param array<string,mixed> $body */
    public function post(string $path, array $body, string $accept = self::VENDOR_PUBLIC): Response
    {
        return $this->request('POST', $path, [], $body, $accept);
    }

    /** @param array<string,mixed> $body */
    public function put(string $path, array $body, string $accept = self::VENDOR_PUBLIC): Response
    {
        return $this->request('PUT', $path, [], $body, $accept);
    }

    /** @param array<string,mixed> $body */
    public function patch(string $path, array $body, string $accept = self::VENDOR_PUBLIC): Response
    {
        return $this->request('PATCH', $path, [], $body, $accept);
    }

    /**
     * Bináris feltöltés (pl. számla PDF). Külön metódus, mert itt a
     * Content-Type nem a vendor-típus, hanem a fájlé.
     */
    public function putBinary(string $path, string $contents, string $contentType): Response
    {
        return $this->send('PUT', $this->url($path, []), [
            'Content-Type: ' . $contentType,
            'Accept: ' . self::VENDOR_PUBLIC,
        ], $contents);
    }

    /**
     * @param array<string,scalar|array<int,scalar>> $query
     * @param array<string,mixed>|null               $body
     */
    public function request(
        string $method,
        string $path,
        array $query = [],
        ?array $body = null,
        string $accept = self::VENDOR_PUBLIC,
    ): Response {
        $headers = ['Accept: ' . $accept];

        $payload = null;
        if ($body !== null) {
            $payload = json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
            if ($payload === false) {
                throw new RuntimeException('A kérés törzse nem kódolható JSON-ba.');
            }
            $headers[] = 'Content-Type: ' . $accept;
        }

        return $this->send($method, $this->url($path, $query), $headers, $payload);
    }

    /** @param array<string,scalar|array<int,scalar>> $query */
    private function url(string $path, array $query): string
    {
        $url = str_starts_with($path, 'http')
            ? $path
            : $this->config->apiBase() . '/' . ltrim($path, '/');

        if ($query !== []) {
            $url .= (str_contains($url, '?') ? '&' : '?') . $this->buildQuery($query);
        }

        return $url;
    }

    /**
     * Az Allegro a tömbös szűrőket ismételt kulccsal várja
     * (pl. `type=BOUGHT&type=FILLED_IN`), nem `type[]=` alakban.
     *
     * @param array<string,scalar|array<int,scalar>> $query
     */
    private function buildQuery(array $query): string
    {
        $parts = [];
        foreach ($query as $key => $value) {
            if (is_array($value)) {
                foreach ($value as $item) {
                    $parts[] = rawurlencode($key) . '=' . rawurlencode((string) $item);
                }
                continue;
            }
            if (is_bool($value)) {
                $value = $value ? 'true' : 'false';
            }
            $parts[] = rawurlencode($key) . '=' . rawurlencode((string) $value);
        }

        return implode('&', $parts);
    }

    /** @param list<string> $headers */
    private function send(string $method, string $url, array $headers, ?string $payload): Response
    {
        $attempt = 0;

        while (true) {
            $attempt++;
            $this->rateLimiter->acquire();

            $response = $this->execute($method, $url, $headers, $payload);

            $this->logger->debug(sprintf(
                '%s %s -> %d%s',
                $method,
                $this->redact($url),
                $response->status,
                $response->traceId() !== null ? ' trace=' . $response->traceId() : '',
            ));

            if ($response->isSuccess()) {
                return $response;
            }

            if ($this->shouldRetry($response->status) && $attempt <= self::MAX_RETRIES) {
                $delay = $this->retryDelaySeconds($response, $attempt);
                $this->logger->warn(sprintf(
                    'HTTP %d a(z) %s hívásnál – újrapróbálás %.1fs múlva (%d/%d), trace=%s',
                    $response->status,
                    $this->redact($url),
                    $delay,
                    $attempt,
                    self::MAX_RETRIES,
                    $response->traceId() ?? '-',
                ));
                usleep((int) ceil($delay * 1_000_000));

                continue;
            }

            throw ApiException::fromResponse($response);
        }
    }

    private function shouldRetry(int $status): bool
    {
        // 429: kéréskorlát. 5xx: átmeneti szerverhiba.
        // A 4xx többi tagja a mi hibánk – újrapróbálni értelmetlen.
        return $status === 429 || $status === 503 || ($status >= 500 && $status < 600);
    }

    private function retryDelaySeconds(Response $response, int $attempt): float
    {
        $retryAfter = $response->header('retry-after');
        if ($retryAfter !== null && is_numeric($retryAfter)) {
            return max(1.0, (float) $retryAfter);
        }

        // Exponenciális backoff enyhe szórással, hogy a párhuzamos futások
        // ne egyszerre próbálkozzanak újra.
        $base = 2 ** $attempt;
        $jitter = random_int(0, 500) / 1000;

        return min(60.0, $base + $jitter);
    }

    /** @param list<string> $headers */
    private function execute(string $method, string $url, array $headers, ?string $payload): Response
    {
        $handle = curl_init();
        if ($handle === false) {
            throw new RuntimeException('A cURL nem inicializálható.');
        }

        $allHeaders = array_merge($headers, [
            'Accept-Language: ' . ($this->languageOverride ?? $this->config->language()),
        ]);

        $token = ($this->tokenProvider)();
        if ($token !== null && $token !== '') {
            $allHeaders[] = 'Authorization: Bearer ' . $token;
        }

        $responseHeaders = [];

        curl_setopt_array($handle, [
            CURLOPT_URL => $url,
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => $allHeaders,
            // A User-Agent kötelező és kötött formátumú – a Config validálja.
            CURLOPT_USERAGENT => $this->config->userAgent(),
            CURLOPT_TIMEOUT => 120,
            CURLOPT_CONNECTTIMEOUT => 20,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_HEADERFUNCTION => function ($_, string $line) use (&$responseHeaders): int {
                $len = strlen($line);
                $colon = strpos($line, ':');
                if ($colon !== false) {
                    $name = strtolower(trim(substr($line, 0, $colon)));
                    $responseHeaders[$name] = trim(substr($line, $colon + 1));
                }

                return $len;
            },
        ]);

        if ($payload !== null) {
            curl_setopt($handle, CURLOPT_POSTFIELDS, $payload);
        }

        $body = curl_exec($handle);
        $errno = curl_errno($handle);
        $error = curl_error($handle);
        $status = (int) curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
        curl_close($handle);

        if ($errno !== 0 || $body === false) {
            throw new RuntimeException("Hálózati hiba ({$errno}): {$error}");
        }

        return new Response($status, (string) $body, $responseHeaders);
    }

    /** A naplóból kimaradnak a query-ben utazó azonosítók hosszú farkai. */
    private function redact(string $url): string
    {
        return preg_replace('#^https?://[^/]+#', '', $url) ?? $url;
    }
}
