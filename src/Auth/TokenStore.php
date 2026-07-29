<?php

declare(strict_types=1);

namespace AllegroSync\Auth;

use AllegroSync\State\Db;

/**
 * Tokenek tárolása és lejárat-figyelése.
 *
 * Az access token ~12 óráig, a refresh token ~3 hónapig él. A frissítést
 * automatikusan végezzük, de a lejáratot pufferrel nézzük, hogy egy hosszú
 * futású köteg közben ne járjon le a token a kérés és a válasz között.
 */
final class TokenStore
{
    private const EXPIRY_BUFFER_SECONDS = 120;

    public function __construct(private readonly Db $db)
    {
    }

    public function save(
        string $name,
        string $accessToken,
        ?string $refreshToken,
        int $expiresInSeconds,
        ?string $scope = null,
    ): void {
        $now = time();
        $stmt = $this->db->pdo()->prepare(
            'INSERT INTO tokens (name, access_token, refresh_token, expires_at, scope, updated_at)
             VALUES (?, ?, ?, ?, ?, ?)
             ON CONFLICT(name) DO UPDATE SET
                access_token  = excluded.access_token,
                refresh_token = COALESCE(excluded.refresh_token, tokens.refresh_token),
                expires_at    = excluded.expires_at,
                scope         = excluded.scope,
                updated_at    = excluded.updated_at'
        );
        $stmt->execute([
            $name,
            $accessToken,
            $refreshToken,
            $now + $expiresInSeconds,
            $scope,
            $now,
        ]);
    }

    /** @return array<string,mixed>|null */
    public function find(string $name): ?array
    {
        $stmt = $this->db->pdo()->prepare('SELECT * FROM tokens WHERE name = ?');
        $stmt->execute([$name]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    public function isExpired(string $name): bool
    {
        $row = $this->find($name);
        if ($row === null) {
            return true;
        }

        return (int) $row['expires_at'] - self::EXPIRY_BUFFER_SECONDS <= time();
    }

    public function accessToken(string $name): ?string
    {
        $row = $this->find($name);

        return $row === null ? null : (string) $row['access_token'];
    }

    public function refreshToken(string $name): ?string
    {
        $row = $this->find($name);
        if ($row === null || $row['refresh_token'] === null) {
            return null;
        }

        return (string) $row['refresh_token'];
    }

    public function forget(string $name): void
    {
        $stmt = $this->db->pdo()->prepare('DELETE FROM tokens WHERE name = ?');
        $stmt->execute([$name]);
    }
}
