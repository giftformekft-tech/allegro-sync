<?php

declare(strict_types=1);

namespace AllegroSync\State;

use PDO;

/**
 * SQLite állapottár.
 *
 * Ez a modul teszi a szinkront újrafuttathatóvá: minden külső azonosítót
 * (offerId, productId, kép-URL, számlaszám) itt kötünk a saját SKU-nkhoz,
 * hogy egy megismételt futás ne hozzon létre duplikátumot.
 *
 * Környezetenként külön fájl – lásd Config::statePath().
 */
final class Db
{
    private PDO $pdo;

    public function __construct(string $path)
    {
        $this->pdo = new PDO('sqlite:' . $path, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $this->pdo->exec('PRAGMA journal_mode = WAL');
        $this->pdo->exec('PRAGMA foreign_keys = ON');
        $this->migrate();
    }

    public function pdo(): PDO
    {
        return $this->pdo;
    }

    private function migrate(): void
    {
        $this->pdo->exec(<<<'SQL'
            CREATE TABLE IF NOT EXISTS tokens (
                name          TEXT PRIMARY KEY,
                access_token  TEXT NOT NULL,
                refresh_token TEXT,
                expires_at    INTEGER NOT NULL,
                scope         TEXT,
                updated_at    INTEGER NOT NULL
            );

            -- Feltöltött képek: a mockup URL-jét kötjük az Allegro CDN-URL-hez.
            -- A sandboxban 7 nap után törlik a képeket, ezért van lejárat.
            CREATE TABLE IF NOT EXISTS images (
                source_url   TEXT PRIMARY KEY,
                allegro_url  TEXT NOT NULL,
                expires_at   INTEGER,
                created_at   INTEGER NOT NULL
            );

            -- Saját javasolt katalógustermékek. A 409-es "már létezik" válaszból
            -- kiolvasott productId is ide kerül, ezért van külön status.
            CREATE TABLE IF NOT EXISTS products (
                sku          TEXT PRIMARY KEY,
                product_id   TEXT,
                status       TEXT NOT NULL,
                payload_hash TEXT,
                last_error   TEXT,
                created_at   INTEGER NOT NULL,
                updated_at   INTEGER NOT NULL
            );

            -- Ajánlatok. Az external_id a mi SKU-nk; ez az idempotencia kulcsa.
            CREATE TABLE IF NOT EXISTS offers (
                sku           TEXT PRIMARY KEY,
                offer_id      TEXT,
                operation_id  TEXT,
                status        TEXT NOT NULL,
                publication   TEXT,
                payload_hash  TEXT,
                last_error    TEXT,
                created_at    INTEGER NOT NULL,
                updated_at    INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS offers_status_idx ON offers(status);

            -- Rendelések és a hozzájuk tartozó számla. A számlázás egyelőre
            -- nincs bekötve, de a tábla már itt van, hogy a bekötés ne igényeljen
            -- sémaváltást.
            CREATE TABLE IF NOT EXISTS orders (
                order_id           TEXT PRIMARY KEY,
                status             TEXT NOT NULL,
                total_amount       TEXT,
                currency           TEXT,
                invoice_number     TEXT,
                allegro_invoice_id TEXT,
                invoice_state      TEXT NOT NULL DEFAULT 'none',
                payload            TEXT,
                created_at         INTEGER NOT NULL,
                updated_at         INTEGER NOT NULL
            );

            -- Kurzorok: hol tartunk az eseményfolyamokban.
            CREATE TABLE IF NOT EXISTS cursors (
                name       TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
        SQL);
    }

    // ------------------------------------------------------------ kurzorok

    public function getCursor(string $name): ?string
    {
        $stmt = $this->pdo->prepare('SELECT value FROM cursors WHERE name = ?');
        $stmt->execute([$name]);
        $row = $stmt->fetch();

        return $row === false ? null : (string) $row['value'];
    }

    public function setCursor(string $name, string $value): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO cursors (name, value, updated_at) VALUES (?, ?, ?)
             ON CONFLICT(name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at'
        );
        $stmt->execute([$name, $value, time()]);
    }

    // -------------------------------------------------------------- képek

    public function findImage(string $sourceUrl): ?string
    {
        $stmt = $this->pdo->prepare(
            'SELECT allegro_url, expires_at FROM images WHERE source_url = ?'
        );
        $stmt->execute([$sourceUrl]);
        $row = $stmt->fetch();

        if ($row === false) {
            return null;
        }

        // Lejárt bejegyzés nem használható – újra fel kell tölteni.
        if ($row['expires_at'] !== null && (int) $row['expires_at'] < time()) {
            return null;
        }

        return (string) $row['allegro_url'];
    }

    public function saveImage(string $sourceUrl, string $allegroUrl, ?int $expiresAt): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO images (source_url, allegro_url, expires_at, created_at) VALUES (?, ?, ?, ?)
             ON CONFLICT(source_url) DO UPDATE SET
                allegro_url = excluded.allegro_url,
                expires_at  = excluded.expires_at'
        );
        $stmt->execute([$sourceUrl, $allegroUrl, $expiresAt, time()]);
    }

    // ---------------------------------------------------------- termékek

    /** @return array<string,mixed>|null */
    public function findProduct(string $sku): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM products WHERE sku = ?');
        $stmt->execute([$sku]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    public function saveProduct(string $sku, ?string $productId, string $status, ?string $error = null): void
    {
        $now = time();
        $stmt = $this->pdo->prepare(
            'INSERT INTO products (sku, product_id, status, last_error, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?)
             ON CONFLICT(sku) DO UPDATE SET
                product_id = excluded.product_id,
                status     = excluded.status,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at'
        );
        $stmt->execute([$sku, $productId, $status, $error, $now, $now]);
    }

    // ---------------------------------------------------------- ajánlatok

    /** @return array<string,mixed>|null */
    public function findOffer(string $sku): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM offers WHERE sku = ?');
        $stmt->execute([$sku]);
        $row = $stmt->fetch();

        return $row === false ? null : $row;
    }

    public function saveOffer(
        string $sku,
        ?string $offerId,
        string $status,
        ?string $operationId = null,
        ?string $publication = null,
        ?string $error = null,
    ): void {
        $now = time();
        $stmt = $this->pdo->prepare(
            'INSERT INTO offers (sku, offer_id, operation_id, status, publication, last_error, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(sku) DO UPDATE SET
                offer_id     = COALESCE(excluded.offer_id, offers.offer_id),
                operation_id = excluded.operation_id,
                status       = excluded.status,
                publication  = COALESCE(excluded.publication, offers.publication),
                last_error   = excluded.last_error,
                updated_at   = excluded.updated_at'
        );
        $stmt->execute([$sku, $offerId, $operationId, $status, $publication, $error, $now, $now]);
    }

    /** @return list<array<string,mixed>> */
    public function offersByStatus(string $status, int $limit = 1000): array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM offers WHERE status = ? LIMIT ?');
        $stmt->execute([$status, $limit]);

        return $stmt->fetchAll();
    }

    /** @return array<string,int> */
    public function offerStatusCounts(): array
    {
        $rows = $this->pdo->query('SELECT status, COUNT(*) AS n FROM offers GROUP BY status');
        $out = [];
        foreach ($rows === false ? [] : $rows->fetchAll() as $row) {
            $out[(string) $row['status']] = (int) $row['n'];
        }

        return $out;
    }
}
