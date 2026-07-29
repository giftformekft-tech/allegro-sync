<?php

declare(strict_types=1);

namespace AllegroSync\Auth;

use AllegroSync\Config\Config;
use AllegroSync\Support\Logger;
use RuntimeException;

/**
 * OAuth2 az Allegróhoz.
 *
 * Két tokentípust kezelünk:
 *
 *  - `app`  – client credentials. A kategória- és paraméter-erőforrásokhoz
 *             elég, tehát a felderítő (0. fázis) fut vele, felhasználói
 *             bejelentkezés NÉLKÜL.
 *  - `user` – device flow. Ez kell mindenhez, ami az eladó nevében történik:
 *             ajánlat, termékjavaslat, rendelés, számla.
 *
 * Az OAuth-végpontok nem verziózottak, és form-kódolt törzset várnak, ezért
 * nem a vendor-típusos Api\Client megy rájuk, hanem közvetlen cURL.
 */
final class Authenticator
{
    public const TOKEN_APP = 'app';
    public const TOKEN_USER = 'user';

    private const DEVICE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code';

    public function __construct(
        private readonly Config $config,
        private readonly TokenStore $store,
        private readonly Logger $logger,
    ) {
    }

    /**
     * Érvényes alkalmazás-token (client credentials). Lejáratkor csendben
     * újrakéri – itt nincs refresh token, egyszerűen új tokent kérünk.
     */
    public function appToken(): string
    {
        if (!$this->store->isExpired(self::TOKEN_APP)) {
            $token = $this->store->accessToken(self::TOKEN_APP);
            if ($token !== null) {
                return $token;
            }
        }

        $data = $this->form('/token', ['grant_type' => 'client_credentials']);

        $this->store->save(
            self::TOKEN_APP,
            (string) $data['access_token'],
            null,
            (int) ($data['expires_in'] ?? 3600),
            isset($data['scope']) ? (string) $data['scope'] : null,
        );

        return (string) $data['access_token'];
    }

    /**
     * Érvényes felhasználói token. Lejáratkor a refresh tokennel frissít;
     * ha az is lejárt, újra be kell jelentkezni.
     */
    public function userToken(): string
    {
        if (!$this->store->isExpired(self::TOKEN_USER)) {
            $token = $this->store->accessToken(self::TOKEN_USER);
            if ($token !== null) {
                return $token;
            }
        }

        $refresh = $this->store->refreshToken(self::TOKEN_USER);
        if ($refresh === null) {
            throw new RuntimeException(
                "Nincs érvényes felhasználói token. Jelentkezz be:\n  bin/allegro auth:login"
            );
        }

        $this->logger->debug('A felhasználói token lejárt, frissítés a refresh tokennel.');

        try {
            $data = $this->form('/token', [
                'grant_type' => 'refresh_token',
                'refresh_token' => $refresh,
            ]);
        } catch (RuntimeException $e) {
            $this->store->forget(self::TOKEN_USER);

            throw new RuntimeException(
                "A token frissítése nem sikerült ({$e->getMessage()}).\n"
                . "Jelentkezz be újra:\n  bin/allegro auth:login"
            );
        }

        $this->store->save(
            self::TOKEN_USER,
            (string) $data['access_token'],
            isset($data['refresh_token']) ? (string) $data['refresh_token'] : null,
            (int) ($data['expires_in'] ?? 43200),
            isset($data['scope']) ? (string) $data['scope'] : null,
        );

        return (string) $data['access_token'];
    }

    /**
     * Device flow indítása.
     *
     * @return array{device_code:string,user_code:string,verification_uri:string,verification_uri_complete:?string,interval:int,expires_in:int}
     */
    public function startDeviceFlow(): array
    {
        $data = $this->form('/device', ['client_id' => $this->config->clientId()]);

        foreach (['device_code', 'user_code', 'verification_uri'] as $key) {
            if (!isset($data[$key])) {
                throw new RuntimeException("A device flow válaszából hiányzik: {$key}");
            }
        }

        return [
            'device_code' => (string) $data['device_code'],
            'user_code' => (string) $data['user_code'],
            'verification_uri' => (string) $data['verification_uri'],
            'verification_uri_complete' => isset($data['verification_uri_complete'])
                ? (string) $data['verification_uri_complete']
                : null,
            'interval' => (int) ($data['interval'] ?? 5),
            'expires_in' => (int) ($data['expires_in'] ?? 600),
        ];
    }

    /**
     * A device flow lezárása: addig kérdezzük a tokent, amíg a felhasználó
     * jóvá nem hagyja a böngészőben.
     */
    public function pollDeviceToken(string $deviceCode, int $intervalSeconds, int $expiresInSeconds): void
    {
        $deadline = time() + $expiresInSeconds;
        $interval = max(1, $intervalSeconds);

        while (time() < $deadline) {
            sleep($interval);

            try {
                $data = $this->form('/token', [
                    'grant_type' => self::DEVICE_GRANT,
                    'device_code' => $deviceCode,
                ]);
            } catch (OAuthPendingException $e) {
                if ($e->slowDown) {
                    $interval++;
                }

                continue;
            }

            $this->store->save(
                self::TOKEN_USER,
                (string) $data['access_token'],
                isset($data['refresh_token']) ? (string) $data['refresh_token'] : null,
                (int) ($data['expires_in'] ?? 43200),
                isset($data['scope']) ? (string) $data['scope'] : null,
            );

            return;
        }

        throw new RuntimeException('A bejelentkezés lejárt, mielőtt jóváhagytad volna. Próbáld újra.');
    }

    /**
     * Form-kódolt POST az OAuth-végpontra, Basic auth-tal.
     *
     * @param array<string,string> $params
     *
     * @return array<string,mixed>
     */
    private function form(string $path, array $params): array
    {
        $url = $this->config->authBase() . $path;

        $handle = curl_init();
        if ($handle === false) {
            throw new RuntimeException('A cURL nem inicializálható.');
        }

        curl_setopt_array($handle, [
            CURLOPT_URL => $url,
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => http_build_query($params),
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_USERAGENT => $this->config->userAgent(),
            CURLOPT_USERPWD => $this->config->clientId() . ':' . $this->config->clientSecret(),
            CURLOPT_HTTPAUTH => CURLAUTH_BASIC,
            CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded'],
            CURLOPT_TIMEOUT => 60,
            CURLOPT_CONNECTTIMEOUT => 20,
        ]);

        $body = curl_exec($handle);
        $errno = curl_errno($handle);
        $error = curl_error($handle);
        $status = (int) curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
        curl_close($handle);

        if ($errno !== 0 || $body === false) {
            throw new RuntimeException("Hálózati hiba az OAuth hívásnál ({$errno}): {$error}");
        }

        $decoded = json_decode((string) $body, true);
        if (!is_array($decoded)) {
            throw new RuntimeException("Az OAuth válasz nem JSON (HTTP {$status}): " . mb_substr((string) $body, 0, 200));
        }

        if ($status >= 200 && $status < 300) {
            return $decoded;
        }

        $errorCode = isset($decoded['error']) ? (string) $decoded['error'] : 'unknown_error';

        // A device flow alatt ezek nem hibák, hanem "még nem hagyta jóvá".
        if ($errorCode === 'authorization_pending' || $errorCode === 'slow_down') {
            throw new OAuthPendingException($errorCode === 'slow_down');
        }

        $description = isset($decoded['error_description'])
            ? (string) $decoded['error_description']
            : '';

        throw new RuntimeException(trim("OAuth hiba ({$status}) {$errorCode}: {$description}"));
    }
}
