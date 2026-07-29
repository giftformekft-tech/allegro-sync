<?php

declare(strict_types=1);

namespace AllegroSync\Discover;

use AllegroSync\Api\ApiException;
use AllegroSync\Api\Client;

/**
 * Egzisztenciális kockázat figyelése.
 *
 * A vállalkozás soha nem fog GTIN-t használni, ezért az a nap, amikor a
 * használt kategóriánkban a GTIN kötelezővé válik, leállítja a feltöltést.
 * Az API viszont ad rá előrejelzést – ez az osztály ezt olvassa ki.
 *
 * Két forrásból dolgozunk:
 *
 *  - kategóriaszint: mely paraméter válik kötelezővé, legfeljebb 3 hónapra előre
 *  - ajánlatszint:   melyik MEGLÉVŐ ajánlatunkból hiányzik ilyen paraméter
 */
final class GtinWatchdog
{
    public function __construct(private readonly Client $client)
    {
    }

    /**
     * Tervezett paraméter-kötelezővé válások.
     *
     * Figyelem: ez az erőforrás CSAK `pl-PL` nyelvet fogad, ezért írjuk felül.
     *
     * @param list<string> $categoryIds ha üres, minden változást visszaad
     *
     * @return list<array{categoryId:string,categoryName:string,parameterName:string,scheduledFor:string,isGtin:bool}>
     */
    public function scheduledRequirementChanges(array $categoryIds = [], int $monthsAhead = 3): array
    {
        $client = $this->client->withLanguage('pl-PL');

        $query = [
            'type' => ['REQUIREMENT_CHANGE'],
            'scheduledFor.gte' => gmdate('Y-m-d\TH:i:s\Z'),
            'scheduledFor.lte' => gmdate('Y-m-d\TH:i:s\Z', strtotime("+{$monthsAhead} months") ?: time()),
            'limit' => 1000,
        ];

        $data = $client->get('/sale/category-parameters-scheduled-changes', $query)->json();

        $wanted = $categoryIds === [] ? null : array_flip($categoryIds);
        $out = [];

        foreach ($this->firstList($data) as $change) {
            if (!is_array($change)) {
                continue;
            }

            $category = is_array($change['category'] ?? null) ? $change['category'] : [];
            $parameter = is_array($change['parameter'] ?? null) ? $change['parameter'] : [];

            $categoryId = (string) ($category['id'] ?? '');
            if ($wanted !== null && $categoryId !== '' && !isset($wanted[$categoryId])) {
                continue;
            }

            $parameterName = (string) ($parameter['name'] ?? '');

            $out[] = [
                'categoryId' => $categoryId,
                'categoryName' => (string) ($category['name'] ?? ''),
                'parameterName' => $parameterName,
                'scheduledFor' => (string) ($change['scheduledFor'] ?? ''),
                'isGtin' => $this->looksLikeGtin($parameter, $parameterName),
            ];
        }

        return $out;
    }

    /**
     * Meglévő ajánlatok, amikből hiányzik kötelező vagy hamarosan kötelezővé
     * váló paraméter.
     *
     * @return list<array{offerId:string,offerName:string,parameters:list<string>,gtinAffected:bool}>
     */
    public function unfilledParameters(string $parameterType = 'REQUIREMENT_PLANNED'): array
    {
        $out = [];
        $offset = 0;
        $limit = 1000;

        while (true) {
            $data = $this->client->get('/sale/offers/unfilled-parameters', [
                'parameterType' => $parameterType,
                'offset' => $offset,
                'limit' => $limit,
            ])->json();

            $items = $this->firstList($data);
            if ($items === []) {
                break;
            }

            foreach ($items as $item) {
                if (!is_array($item)) {
                    continue;
                }

                $names = [];
                $gtinAffected = false;

                foreach ($item['parameters'] ?? [] as $parameter) {
                    if (!is_array($parameter)) {
                        continue;
                    }
                    $name = (string) ($parameter['name'] ?? '');
                    if ($name !== '') {
                        $names[] = $name;
                    }
                    if ($this->looksLikeGtin($parameter, $name)) {
                        $gtinAffected = true;
                    }
                }

                $offer = is_array($item['offer'] ?? null) ? $item['offer'] : $item;

                $out[] = [
                    'offerId' => (string) ($offer['id'] ?? ''),
                    'offerName' => (string) ($offer['name'] ?? ''),
                    'parameters' => $names,
                    'gtinAffected' => $gtinAffected,
                ];
            }

            if (count($items) < $limit) {
                break;
            }
            $offset += $limit;

            // Az erőforrás offset-korlátja miatt nem megyünk a végtelenbe.
            if ($offset > 10000) {
                break;
            }
        }

        return $out;
    }

    /**
     * A válaszok gyökérkulcsa erőforrásonként eltér; a séma pontos neve
     * helyett az első lista-értékű kulcsot vesszük, hogy egy elnevezésbeli
     * eltérés ne törje el a figyelést.
     *
     * @param array<mixed> $data
     *
     * @return list<mixed>
     */
    private function firstList(array $data): array
    {
        foreach ($data as $value) {
            if (is_array($value) && array_is_list($value)) {
                return $value;
            }
        }

        return [];
    }

    /** @param array<string,mixed> $parameter */
    private function looksLikeGtin(array $parameter, string $name): bool
    {
        $options = is_array($parameter['options'] ?? null) ? $parameter['options'] : [];
        if (($options['isGTIN'] ?? false) === true) {
            return true;
        }

        $upper = mb_strtoupper($name);

        return str_contains($upper, 'GTIN') || str_contains($upper, 'EAN');
    }

    /** Elérhető-e egyáltalán az erőforrás (jogosultság / verzió ellenőrzés). */
    public function selfTest(): ?string
    {
        try {
            $this->scheduledRequirementChanges([], 1);

            return null;
        } catch (ApiException $e) {
            return $e->getMessage();
        }
    }
}
