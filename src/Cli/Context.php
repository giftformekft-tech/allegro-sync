<?php

declare(strict_types=1);

namespace AllegroSync\Cli;

use AllegroSync\Api\Client;
use AllegroSync\Api\RateLimiter;
use AllegroSync\Auth\Authenticator;
use AllegroSync\Auth\TokenStore;
use AllegroSync\Config\Config;
use AllegroSync\State\Db;
use AllegroSync\Support\Logger;

/**
 * A parancsok közös függőségei, lustán példányosítva.
 *
 * Szándékosan nincs benne DI-konténer: a program kicsi, és az explicit
 * összekötés itt olvashatóbb, mint egy konfigurációs réteg.
 */
final class Context
{
    private ?Db $db = null;
    private ?TokenStore $tokenStore = null;
    private ?Authenticator $auth = null;
    private ?RateLimiter $rateLimiter = null;

    public function __construct(
        public readonly Config $config,
        public readonly Logger $logger,
        public readonly Output $output,
    ) {
    }

    public function db(): Db
    {
        return $this->db ??= new Db($this->config->statePath());
    }

    public function tokenStore(): TokenStore
    {
        return $this->tokenStore ??= new TokenStore($this->db());
    }

    public function auth(): Authenticator
    {
        return $this->auth ??= new Authenticator($this->config, $this->tokenStore(), $this->logger);
    }

    private function rateLimiter(): RateLimiter
    {
        return $this->rateLimiter ??= new RateLimiter($this->config->rateLimitPerMinute());
    }

    /** Kliens alkalmazás-tokennel – kategória- és paraméter-lekérdezésekhez. */
    public function appClient(): Client
    {
        $auth = $this->auth();

        return new Client(
            $this->config,
            $this->logger,
            $this->rateLimiter(),
            static fn (): string => $auth->appToken(),
        );
    }

    /** Kliens felhasználói tokennel – minden, ami az eladó nevében történik. */
    public function userClient(): Client
    {
        $auth = $this->auth();

        return new Client(
            $this->config,
            $this->logger,
            $this->rateLimiter(),
            static fn (): string => $auth->userToken(),
        );
    }
}
