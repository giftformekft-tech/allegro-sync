<?php

declare(strict_types=1);

namespace AllegroSync\Discover;

use AllegroSync\Api\ApiException;
use AllegroSync\Api\Client;
use AllegroSync\Support\Logger;

/**
 * A 0. fázis eszköze: eldönti, mely kategóriákban listázhatunk EAN nélkül.
 *
 * A projekt központi megkötése, hogy nincs és nem is lesz GTIN. Ez a
 * felderítő két kérdésre válaszol kategóriánként:
 *
 *   1. Kötelező-e a GTIN paraméter?           (ha igen, a kategória zárt)
 *   2. Javasolhatunk-e saját katalógusterméket? (ha nem, nincs mihez kötni)
 *
 * A kategória- és paraméter-erőforrások alkalmazás-tokennel is mennek, tehát
 * ez a felderítés felhasználói bejelentkezés nélkül lefuttatható.
 */
final class CategoryScanner
{
    /** @var array<string,array<string,mixed>> kategória-gyorsítótár */
    private array $categoryCache = [];

    public function __construct(
        private readonly Client $client,
        private readonly Logger $logger,
    ) {
    }

    /**
     * Kategória-javaslat kifejezésre. Ez csak felhasználói tokennel megy,
     * és saját, alacsonyabb kérésgyakorisági limitje van.
     *
     * @return list<array{id:string,name:string}>
     */
    public function suggest(string $phrase): array
    {
        $response = $this->client->get('/sale/matching-categories', ['name' => $phrase]);
        $data = $response->json();

        $out = [];
        foreach ($data['matchingCategories'] ?? [] as $category) {
            if (!is_array($category) || !isset($category['id'])) {
                continue;
            }
            $out[] = [
                'id' => (string) $category['id'],
                'name' => (string) ($category['name'] ?? ''),
            ];
        }

        return $out;
    }

    /**
     * A megadott kategória alatti összes levélkategória bejárása.
     *
     * @return list<CategoryVerdict>
     */
    public function scanTree(string $rootId, int $maxDepth = 4): array
    {
        $results = [];
        $this->walk($rootId, [], 0, $maxDepth, $results);

        return $results;
    }

    /**
     * Konkrét kategóriák ellenőrzése, bejárás nélkül.
     *
     * @param list<string> $ids
     *
     * @return list<CategoryVerdict>
     */
    public function scanIds(array $ids): array
    {
        $out = [];
        foreach ($ids as $id) {
            $out[] = $this->inspect($id, $this->pathOf($id));
        }

        return $out;
    }

    /** @param list<CategoryVerdict> $results */
    private function walk(string $id, array $trail, int $depth, int $maxDepth, array &$results): void
    {
        $category = $this->category($id);
        $name = (string) ($category['name'] ?? $id);
        $trail[] = $name;

        $isLeaf = (bool) ($category['leaf'] ?? false);

        if ($isLeaf) {
            $results[] = $this->inspect($id, implode(' / ', $trail), $category);

            return;
        }

        if ($depth >= $maxDepth) {
            $this->logger->debug("Mélységkorlát elérve: {$id} ({$name})");

            return;
        }

        foreach ($this->children($id) as $child) {
            $childId = (string) ($child['id'] ?? '');
            if ($childId === '') {
                continue;
            }
            $this->walk($childId, $trail, $depth + 1, $maxDepth, $results);
        }
    }

    /** @param array<string,mixed>|null $category */
    private function inspect(string $id, string $path, ?array $category = null): CategoryVerdict
    {
        $category ??= $this->category($id);
        $name = (string) ($category['name'] ?? $id);
        $options = is_array($category['options'] ?? null) ? $category['options'] : [];

        $productCreation = (bool) ($options['productCreationEnabled'] ?? false);
        $offersWithProduct = (bool) ($options['offersWithProductPublicationEnabled'] ?? false);

        try {
            $parameters = $this->parameters($id);
        } catch (ApiException $e) {
            return new CategoryVerdict(
                $id,
                $name,
                $path,
                $productCreation,
                $offersWithProduct,
                false,
                false,
                [],
                $e->getMessage(),
            );
        }

        $gtinPresent = false;
        $gtinRequired = false;
        $required = [];

        foreach ($parameters as $parameter) {
            if (!is_array($parameter)) {
                continue;
            }

            $paramName = (string) ($parameter['name'] ?? '');
            $isRequired = (bool) ($parameter['required'] ?? false);

            if ($isRequired && $paramName !== '') {
                $required[] = $paramName;
            }

            if ($this->isGtinParameter($parameter)) {
                $gtinPresent = true;
                if ($isRequired) {
                    $gtinRequired = true;
                }
            }
        }

        sort($required);

        return new CategoryVerdict(
            $id,
            $name,
            $path,
            $productCreation,
            $offersWithProduct,
            $gtinPresent,
            $gtinRequired,
            $required,
        );
    }

    /**
     * A GTIN-paraméter felismerése.
     *
     * Elsődlegesen az `options.isGTIN` jelzőre támaszkodunk, mert az Allegro
     * ezzel jelöli a GTIN szerepű paramétert. A névre illesztés csak
     * biztonsági háló arra az esetre, ha a jelző hiányozna – inkább jelezzünk
     * feleslegesen, mint hogy egy kötelező GTIN-t elnézzünk.
     *
     * @param array<string,mixed> $parameter
     */
    private function isGtinParameter(array $parameter): bool
    {
        $options = is_array($parameter['options'] ?? null) ? $parameter['options'] : [];
        if (($options['isGTIN'] ?? false) === true) {
            return true;
        }

        $name = mb_strtoupper((string) ($parameter['name'] ?? ''));

        return str_contains($name, 'GTIN') || str_contains($name, 'EAN');
    }

    /** @return array<string,mixed> */
    private function category(string $id): array
    {
        if (isset($this->categoryCache[$id])) {
            return $this->categoryCache[$id];
        }

        $data = $this->client->get('/sale/categories/' . rawurlencode($id))->json();
        $this->categoryCache[$id] = $data;

        return $data;
    }

    /** @return list<array<string,mixed>> */
    private function children(string $id): array
    {
        $data = $this->client->get('/sale/categories', ['parent.id' => $id])->json();
        $out = [];
        foreach ($data['categories'] ?? [] as $category) {
            if (is_array($category)) {
                $out[] = $category;
            }
        }

        return $out;
    }

    /** @return list<array<string,mixed>> */
    private function parameters(string $id): array
    {
        $data = $this->client->get('/sale/categories/' . rawurlencode($id) . '/parameters')->json();
        $out = [];
        foreach ($data['parameters'] ?? [] as $parameter) {
            if (is_array($parameter)) {
                $out[] = $parameter;
            }
        }

        return $out;
    }

    private function pathOf(string $id): string
    {
        $names = [];
        $current = $id;
        $guard = 0;

        while ($current !== '' && $guard++ < 10) {
            $category = $this->category($current);
            array_unshift($names, (string) ($category['name'] ?? $current));
            $parent = is_array($category['parent'] ?? null) ? $category['parent'] : null;
            $current = $parent === null ? '' : (string) ($parent['id'] ?? '');
        }

        return implode(' / ', $names);
    }
}
