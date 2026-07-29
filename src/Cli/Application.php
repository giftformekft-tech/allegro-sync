<?php

declare(strict_types=1);

namespace AllegroSync\Cli;

use AllegroSync\Api\ApiException;
use AllegroSync\Cli\Commands\AuthLoginCommand;
use AllegroSync\Cli\Commands\AuthStatusCommand;
use AllegroSync\Cli\Commands\CategoriesScanCommand;
use AllegroSync\Cli\Commands\CategoriesSuggestCommand;
use AllegroSync\Cli\Commands\GtinWatchCommand;
use AllegroSync\Cli\Commands\ImportValidateCommand;
use AllegroSync\Cli\Commands\StatusCommand;
use AllegroSync\Config\Config;
use AllegroSync\Support\Logger;
use Throwable;

final class Application
{
    /** @var list<class-string<Command>> */
    private const COMMANDS = [
        AuthLoginCommand::class,
        AuthStatusCommand::class,
        CategoriesSuggestCommand::class,
        CategoriesScanCommand::class,
        GtinWatchCommand::class,
        ImportValidateCommand::class,
        StatusCommand::class,
    ];

    public function __construct(private readonly string $rootDir)
    {
    }

    /** @param list<string> $argv */
    public function run(array $argv): int
    {
        $output = new Output();
        $commandName = $argv[1] ?? null;

        if ($commandName === null || in_array($commandName, ['-h', '--help', 'help'], true)) {
            $this->printHelp($output);

            return $commandName === null ? 1 : 0;
        }

        $args = new Arguments(array_slice($argv, 2));

        $class = $this->resolve($commandName);
        if ($class === null) {
            $output->error("Ismeretlen parancs: {$commandName}");
            $this->printHelp($output);

            return 1;
        }

        try {
            $config = Config::load($this->rootDir);
            $logger = new Logger(
                $args->flag('verbose') ? 'debug' : 'info',
                $config->varDir() . '/allegro-sync.log',
            );
            $context = new Context($config, $logger, $output);

            /** @var Command $command */
            $command = new $class();

            return $command->run($context, $args);
        } catch (ApiException $e) {
            $output->error('API hiba (HTTP ' . $e->status . '): ' . $e->getMessage());
            if ($e->traceId !== null) {
                $output->dim('Trace-Id: ' . $e->traceId . '  – hibabejelentésnél ezt add meg.');
            }

            return 1;
        } catch (Throwable $e) {
            $output->error($e->getMessage());
            if ($args->flag('verbose')) {
                $output->dim($e->getTraceAsString());
            }

            return 1;
        }
    }

    /** @return class-string<Command>|null */
    private function resolve(string $name): ?string
    {
        foreach (self::COMMANDS as $class) {
            if ($class::name() === $name) {
                return $class;
            }
        }

        return null;
    }

    private function printHelp(Output $output): void
    {
        $output->write();
        $output->write($output->paint('allegro-sync', '1;36') . ' – Allegro-integráció a forme.hu-hoz');
        $output->write();
        $output->write('Használat: bin/allegro <parancs> [kapcsolók]');
        $output->write();
        $output->write($output->paint('Parancsok', '1'));

        $rows = [];
        foreach (self::COMMANDS as $class) {
            $rows[] = ['  ' . $class::name(), $class::description()];
        }
        $output->table(['Parancs', 'Leírás'], $rows);

        $output->write();
        $output->write($output->paint('Közös kapcsolók', '1'));
        $output->write('  --verbose      Részletes napló (minden HTTP-hívás és Trace-Id)');
        $output->write();
    }
}
