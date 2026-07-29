<?php

declare(strict_types=1);

use AllegroSync\Map\TitleBuilder;

/** @var TestRunner $t */

$t->group('TitleBuilder – az Allegro 12–75 karakter / min. 3 szó szabálya');

$builder = new TitleBuilder();

// --- alapeset ---------------------------------------------------------------
$result = $builder->build(['Vicces macskás minta', 'Póló', 'Fekete', 'L']);
$t->same('Vicces macskás minta Póló Fekete L', $result->title, 'Minden rész befér');
$t->assert($result->valid, 'Az alapeset érvényes');

// --- túl hosszú: hátulról dobálunk ------------------------------------------
$long = $builder->build([
    'Nagyon hosszú ajándék minta felirattal ami önmagában is majdnem kitölti a keretet',
    'Pulóver',
    'Sötétkék',
    'XXL',
]);
$t->assert(mb_strlen($long->title) <= TitleBuilder::MAX_LENGTH, 'A hosszú cím belefér 75 karakterbe');
$t->assert(!str_contains($long->title, 'XXL'), 'A legkevésbé fontos rész (méret) esett ki először');

// --- szóhatáron vág, nem szó közepén ----------------------------------------
$cut = $builder->build([
    'Antilopvadaszat naplementeben kulonlegesen hosszu megnevezes tovabbi szavakkal itt',
]);
$t->assert(mb_strlen($cut->title) <= TitleBuilder::MAX_LENGTH, 'A csonkolt cím belefér');
$t->assert(!str_ends_with($cut->title, ' '), 'Nem marad lógó szóköz a végén');
$t->assert(
    !preg_match('/\S$/u', $cut->title) || !str_contains(
        'Antilopvadaszat naplementeben kulonlegesen hosszu megnevezes tovabbi szavakkal itt',
        $cut->title . 'x'
    ),
    'A vágás szóhatáron történt',
);

// --- három szavas minimum ---------------------------------------------------
$short = $builder->build(['Bögre']);
$t->assert(!$short->valid, 'Egyetlen rövid szó nem érvényes cím');
$t->assert(
    $short->problem !== null && str_contains($short->problem, 'karakter'),
    'A hiba a hosszra hivatkozik',
);

$twoWords = $builder->build(['Piros nagybögre']);
$t->assert(!$twoWords->valid, 'Két szó nem elég (min. 3 szó)');

$threeWords = $builder->build(['Piros nagy bögre virággal']);
$t->assert($threeWords->valid, 'Négy szó, elég hosszú – érvényes');

// --- 12 karakteres alsó korlát ----------------------------------------------
$tiny = $builder->build(['A', 'B', 'C']);
$t->assert(!$tiny->valid, 'Három betű nem éri el a 12 karaktert');

// --- ismétlődő részek kiszűrése ---------------------------------------------
// A Temu-exportban a név már tartalmazza a típust, ezért ez valós eset.
$dup = $builder->build(['Cica Póló', 'Póló', 'Fekete']);
$t->same('Cica Póló Fekete', $dup->title, 'A névben már benne lévő típus nem kerül be újra');

// A rövid részeket viszont NEM szabad kiszűrni: egy "M" méret könnyen
// egybeesne a névben szereplő betűvel, és a méret elvesztése súlyosabb hiba.
$shortPart = $builder->build(['Vitamin M felirat', 'Póló', 'M']);
$t->assert(str_ends_with($shortPart->title, ' M'), 'Az egybetűs méret akkor is megmarad, ha a névben is szerepel');

// --- üres részek átugrása ---------------------------------------------------
$sparse = $builder->build(['Kutyás vicces minta', '', 'Fehér', '']);
$t->same('Kutyás vicces minta Fehér', $sparse->title, 'Az üres részek kimaradnak');

// --- utótaggal való ütközésfeloldás ------------------------------------------
$suffixed = $builder->withSuffix('Vicces macskás minta Póló Fekete', 'v2');
$t->assert($suffixed->valid, 'Az utótagos cím érvényes');
$t->assert(str_ends_with($suffixed->title, 'v2'), 'Az utótag a cím végén van');
$t->assert(mb_strlen($suffixed->title) <= TitleBuilder::MAX_LENGTH, 'Az utótagos cím is belefér');

$suffixedLong = $builder->withSuffix(
    'Ez egy nagyon hosszu cim ami majdnem pontosan kitolti a hetvenot karakteres keretet',
    'v2',
);
$t->assert(
    mb_strlen($suffixedLong->title) <= TitleBuilder::MAX_LENGTH,
    'Hosszú címnél az utótag helyet csinál magának',
);
$t->assert(str_ends_with($suffixedLong->title, 'v2'), 'Az utótag hosszú címnél is megmarad');

// --- nincs miből ------------------------------------------------------------
$empty = $builder->build([]);
$t->assert(!$empty->valid, 'Üres bemenetből nem lesz érvényes cím');
