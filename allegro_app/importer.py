from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import io
import re
from urllib.parse import urlparse


COLUMNS = {
    "sku": ("sku", "cikkszám", "cikkszam"),
    "parent_sku": ("parent_sku", "alap_sku", "fő sku", "fo_sku"),
    "name": ("name", "termék neve", "termek neve", "név", "nev"),
    "description": ("description", "leírás", "leiras"),
    "type": ("type", "típus", "tipus"),
    "type_label": ("type_label", "típus neve", "tipus neve", "típus megnevezés"),
    "color": ("color", "szín", "szin"),
    "size": ("size", "méret", "meret"),
    "price_huf": ("price_huf", "ár", "ar", "price"),
    "stock": ("stock", "készlet", "keszlet"),
    "image_url": ("image_url", "kép url", "kep url", "kép", "kep"),
    "weight_g": ("weight_g", "súly", "suly", "tömeg", "tomeg"),
    "brand": ("brand", "márka", "marka"),
    "material": ("material", "anyag"),
    "ai_content": ("ai_content", "ai"),
    "length_cm": ("length_cm", "hossz_cm", "hossz (cm)", "hosszúság", "hosszusag"),
    "width_cm": ("width_cm", "szelesseg_cm", "szélesség (cm)", "szélesség", "szelesseg"),
}
REQUIRED = ("sku", "name", "type", "color", "size", "price_huf", "stock", "image_url")


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def build_title(parts: list[str]) -> tuple[str, str | None]:
    clean: list[str] = []
    for raw in parts:
        part = re.sub(r"\s+", " ", raw).strip()
        if not part:
            continue
        accumulated = " ".join(clean).lower().split()
        if len(part) > 2 and part.lower() in accumulated:
            continue
        clean.append(part)
    if not clean:
        return "", "Nincs miből címet képezni."
    title = " ".join(clean)
    while len(title) > 75 and len(clean) > 1:
        clean.pop()
        title = " ".join(clean)
    if len(title) > 75:
        words: list[str] = []
        for word in title.split():
            candidate = " ".join([*words, word])
            if len(candidate) > 75:
                break
            words.append(word)
        title = " ".join(words) if words else title[:75]
    if len(title) < 12:
        return title, f"A cím {len(title)} karakter, a minimum 12."
    if len(title.split()) < 3:
        return title, f"A cím {len(title.split())} szóból áll, a minimum 3."
    return title, None


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _price(value: str) -> str:
    cleaned = re.sub(r"[^0-9.]", "", value.replace(" ", "").replace("\u00a0", "").replace(",", "."))
    if cleaned.count(".") > 1:
        first, *rest = cleaned.split(".")
        cleaned = first + "." + "".join(rest)
    return cleaned


def _measurement(value: str) -> str | None:
    value = value.strip().replace(",", ".")
    if not value:
        return ""
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if number <= 0 or number > 999:
        return None
    return format(number.normalize(), "f")


def parse_csv(content: str) -> list[dict]:
    content = content.lstrip("\ufeff")
    if not content.strip():
        raise ValueError("A CSV fájl üres.")
    first_line = content.splitlines()[0]
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise ValueError("A CSV fájl üres.") from exc
    normal_headers = [_normal(header) for header in headers]
    index: dict[str, int] = {}
    for field, aliases in COLUMNS.items():
        for alias in aliases:
            if _normal(alias) in normal_headers:
                index[field] = normal_headers.index(_normal(alias))
                break
    missing = [field for field in REQUIRED if field not in index]
    if missing:
        raise ValueError("Hiányzó kötelező oszlop(ok): " + ", ".join(missing))

    seen: set[str] = set()
    rows: list[dict] = []
    for line_number, values in enumerate(reader, start=2):
        if not any(value.strip() for value in values):
            continue

        def get(field: str) -> str:
            pos = index.get(field)
            return values[pos].strip() if pos is not None and pos < len(values) else ""

        sku = get("sku")
        problems: list[str] = []
        if not sku:
            sku = f"HIANYZO-SKU-{line_number}"
            problems.append("Hiányzó SKU.")
        elif sku in seen:
            problems.append("Ismétlődő SKU.")
        seen.add(sku)

        name, product_type = get("name"), get("type")
        title, title_problem = build_title([name, get("type_label") or product_type, get("color"), get("size")])
        price = _price(get("price_huf"))
        try:
            numeric_price = Decimal(price)
        except InvalidOperation:
            numeric_price = Decimal(0)
        try:
            stock = int(get("stock"))
        except ValueError:
            stock = 0
            problems.append("A készlet csak egész szám lehet.")
        image_url = get("image_url")

        if not name:
            problems.append("Hiányzó terméknév.")
        if not product_type:
            problems.append("Hiányzó terméktípus.")
        if not image_url:
            problems.append("Nincs kép.")
        elif not _valid_url(image_url):
            problems.append("Érvénytelen kép-URL.")
        if numeric_price <= 0:
            problems.append("Hiányzó vagy érvénytelen ár.")
        if stock <= 0:
            problems.append("A készletnek pozitívnak kell lennie.")
        if title_problem:
            problems.append("Cím: " + title_problem)
        description = get("description")
        if not description:
            problems.append("Hiányzó leírás.")
        elif len(description.encode("utf-8")) > 40000:
            problems.append("A leírás meghaladja a 40 000 bájtot.")
        length_cm = _measurement(get("length_cm"))
        width_cm = _measurement(get("width_cm"))
        if length_cm is None:
            problems.append("A póló hossza csak 0 és 999 közötti pozitív szám lehet.")
            length_cm = ""
        if width_cm is None:
            problems.append("A póló szélessége csak 0 és 999 közötti pozitív szám lehet.")
            width_cm = ""

        rows.append({
            "line": line_number,
            "sku": sku,
            "parent_sku": get("parent_sku") or sku,
            "name": name,
            "title": title,
            "description": description,
            "brand": get("brand"),
            "material": get("material"),
            "ai_content": _normal(get("ai_content")) in {"1", "igen", "yes", "true", "x"},
            "type": product_type,
            "color": get("color"),
            "size": get("size"),
            "price_huf": price,
            "stock": stock,
            "image_url": image_url,
            "length_cm": length_cm,
            "width_cm": width_cm,
            "problems": problems,
        })
    return rows
