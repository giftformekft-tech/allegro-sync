from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from .allegro import AllegroClient, AllegroError
from .config import AppConfig
from .database import Database


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(char for char in value if not unicodedata.combining(char)).casefold().strip()


def suggested_parameter_source(parameter: dict) -> str | None:
    name = _fold(str(parameter.get("name", "")))
    if any(word in name for word in ("marka", "brand")):
        return "brand"
    if any(word in name for word in ("kolor", "szin", "color")):
        return "color"
    if any(word in name for word in ("rozmiar", "meret", "size")):
        return "size"
    if any(word in name for word in ("material", "anyag")):
        return "material"
    if any(word in name for word in ("kod producenta", "gyartoi cikkszam", "manufacturer code")):
        return "sku"
    return None


def suggested_parameter_value(parameter: dict, product: dict) -> str:
    source = suggested_parameter_source(parameter)
    candidate = str(product.get(source, "")) if source else ""
    dictionary = parameter.get("dictionary") or []
    if dictionary and candidate:
        folded = _fold(candidate)
        for item in dictionary:
            if isinstance(item, dict) and _fold(str(item.get("value", ""))) == folded:
                return str(item.get("id", ""))
    return candidate


def serialize_parameter(parameter: dict, value: Any) -> dict | None:
    if value is None or str(value).strip() == "":
        return None
    parameter_id = str(parameter["id"])
    if parameter.get("type") == "dictionary":
        return {"id": parameter_id, "valuesIds": [str(value)]}
    if parameter.get("type") == "range":
        if isinstance(value, dict):
            return {"id": parameter_id, "rangeValue": value}
        parts = [part.strip() for part in str(value).split("-", 1)]
        return {"id": parameter_id, "rangeValue": {"from": parts[0], "to": parts[-1]}}
    return {"id": parameter_id, "values": [str(value).strip()]}


def _description(value: str) -> dict:
    content = value.strip()
    if not content:
        content = "<p>Termékadatok feltöltése folyamatban.</p>"
    elif not re.search(r"<(p|ul|ol|h1|h2)\b", content, re.IGNORECASE):
        content = f"<p>{content}</p>"
    return {"sections": [{"items": [{"type": "TEXT", "content": content}]}]}


def build_offer_payload(
    product: dict,
    category: dict,
    selections: dict[str, Any],
    *,
    currency: str = "HUF",
    language: str = "hu-HU",
    price_amount: str | None = None,
    stock_available: str | int | None = None,
) -> dict:
    if not product.get("image_url"):
        raise ValueError("A termékhez nincs kép URL, ezért nem tölthető fel.")
    if not category.get("leaf"):
        raise ValueError("Ajánlat csak levélkategóriában hozható létre.")
    if not category.get("offer_creation_enabled"):
        raise ValueError("Ebben a kategóriában nem engedélyezett a katalógustermékes ajánlat.")
    if not category.get("product_creation_enabled"):
        raise ValueError("Ebben a kategóriában nem engedélyezett saját katalógustermék létrehozása.")
    if category.get("gtin_required") and not selections.get("__gtin__"):
        raise ValueError("Ebben a kategóriában kötelező a GTIN/EAN, de a projekt nem használ EAN-t.")

    product_parameters: list[dict] = []
    offer_parameters: list[dict] = []
    missing: list[str] = []
    for parameter in category.get("parameters", []):
        value = selections.get(str(parameter["id"]))
        serialized = serialize_parameter(parameter, value)
        required = bool(parameter.get("required") or parameter.get("required_for_product"))
        if required and serialized is None and not parameter.get("is_gtin"):
            missing.append(str(parameter.get("name") or parameter["id"]))
            continue
        if serialized is None:
            continue
        if parameter.get("describes_product") or parameter.get("required_for_product"):
            product_parameters.append(serialized)
        else:
            offer_parameters.append(serialized)
    if missing:
        raise ValueError("Hiányzó kötelező paraméterek: " + ", ".join(missing))

    image = str(product["image_url"])
    price = (price_amount or str(product["price_huf"])).strip().replace(",", ".")
    if not price:
        raise ValueError(f"Adj meg árat {currency} pénznemben.")
    try:
        decimal_price = Decimal(price)
    except InvalidOperation as exc:
        raise ValueError(f"Az ár nem érvényes {currency} összeg.") from exc
    if decimal_price <= 0:
        raise ValueError("Az árnak nullánál nagyobbnak kell lennie.")
    price = format(decimal_price, "f")
    stock_raw = str(product["stock"] if stock_available in {None, ""} else stock_available).strip()
    try:
        stock = int(stock_raw)
    except ValueError as exc:
        raise ValueError("A készlet csak egész darabszám lehet.") from exc
    if stock < 0:
        raise ValueError("A készlet nem lehet negatív.")
    payload: dict[str, Any] = {
        "productSet": [{
            "product": {
                "name": str(product["title"])[:75],
                "category": {"id": str(category["id"])},
                "parameters": product_parameters,
                "images": [image],
            }
        }],
        "name": str(product["title"])[:75],
        "category": {"id": str(category["id"])},
        "parameters": offer_parameters,
        "sellingMode": {
            "format": "BUY_NOW",
            "price": {"amount": price, "currency": currency},
        },
        "stock": {"available": stock, "unit": "UNIT"},
        "publication": {"status": "INACTIVE"},
        "language": language,
        "images": [image],
        "description": _description(str(product.get("description", ""))),
        "external": {"id": str(product["sku"])},
        "payments": {"invoice": "VAT"},
    }
    return payload


class OfferService:
    def __init__(self, config: AppConfig, database: Database, client: AllegroClient):
        self.config = config
        self.database = database
        self.client = client

    def marketplace(self) -> dict:
        me = self.client.request("GET", "/me")["body"]
        base = me.get("baseMarketplace") if isinstance(me.get("baseMarketplace"), dict) else {}
        marketplace_id = str(base.get("id", ""))
        if not marketplace_id:
            raise AllegroError("Az Allegro nem adta vissza a fiók alappiacát.")
        marketplaces = self.client.request("GET", "/marketplaces")["body"].get("marketplaces", [])
        marketplace = next(
            (item for item in marketplaces if isinstance(item, dict) and item.get("id") == marketplace_id), None
        )
        if marketplace is None:
            raise AllegroError(f"Az alappiac nem található a piacterek között: {marketplace_id}")
        currencies = marketplace.get("currencies") if isinstance(marketplace.get("currencies"), dict) else {}
        base_currency = currencies.get("base") if isinstance(currencies.get("base"), dict) else {}
        currency = str(base_currency.get("code", ""))
        languages = marketplace.get("languages") if isinstance(marketplace.get("languages"), dict) else {}
        creation = languages.get("offerCreation") if isinstance(languages.get("offerCreation"), list) else []
        codes = [str(item.get("code")) for item in creation if isinstance(item, dict) and item.get("code")]
        configured = self.config.values.get("ALLEGRO_LANGUAGE", "hu-HU")
        language = configured if configured in codes else (codes[0] if codes else configured)
        if not currency:
            raise AllegroError(f"Az Allegro nem adott meg alappénznemet ehhez: {marketplace_id}")
        return {"id": marketplace_id, "currency": currency, "language": language, "languages": codes}

    def preview(
        self,
        product_id: int,
        category: dict,
        selections: dict[str, Any],
        price_amount: str | None = None,
        stock_available: str | int | None = None,
    ) -> dict:
        product = self.database.get_product(product_id)
        marketplace = self.marketplace()
        if marketplace["currency"] != "HUF" and not (price_amount or "").strip():
            raise ValueError(
                f"A fiók alappénzneme {marketplace['currency']}, ezért adj meg külön tesztárat ebben a pénznemben."
            )
        payload = build_offer_payload(
            product,
            category,
            selections,
            currency=marketplace["currency"],
            language=marketplace["language"],
            price_amount=price_amount,
            stock_available=stock_available,
        )
        return {"payload": payload, "marketplace": marketplace}

    def create(
        self,
        product_id: int,
        category: dict,
        selections: dict[str, Any],
        confirmation: str,
        price_amount: str | None = None,
        stock_available: str | int | None = None,
    ) -> dict:
        if confirmation.strip().upper() != "FELTÖLTÉS":
            raise ValueError("A létrehozáshoz írd be pontosan: FELTÖLTÉS")
        preview = self.preview(product_id, category, selections, price_amount, stock_available)
        response = self.client.request("POST", "/sale/product-offers", body=preview["payload"])
        body = response["body"] if isinstance(response["body"], dict) else {}
        offer_id = str(body.get("id", "")) or None
        if not offer_id:
            location = response["headers"].get("location", "")
            match = re.search(r"/product-offers/([^/]+)", location)
            offer_id = match.group(1) if match else None
        self.database.mark_offer_created(product_id, str(category["id"]), offer_id)
        return {
            "ok": True,
            "status": response["status"],
            "offer_id": offer_id,
            "publication": "INACTIVE",
            "operation": response["headers"].get("location"),
            "marketplace": preview["marketplace"],
        }
