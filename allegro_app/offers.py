from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .allegro import AllegroClient, AllegroError
from .config import AppConfig
from .database import Database


EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
    "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
    "RO", "SK", "SI", "ES", "SE",
}


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


def parameter_is_required(parameter: dict, selections: dict[str, Any]) -> bool:
    required = bool(parameter.get("required") or parameter.get("required_for_product"))
    condition = parameter.get("required_if")
    if not required or not isinstance(condition, dict):
        return required
    with_values = condition.get("parametersWithValue")
    if not isinstance(with_values, list):
        with_values = []
    without_values = condition.get("parametersWithoutValue")
    if not isinstance(without_values, list):
        without_values = []
    for dependency in with_values:
        if not isinstance(dependency, dict):
            return False
        selected = str(selections.get(str(dependency.get("id", "")), ""))
        allowed = {str(value) for value in dependency.get("oneOfValueIds", [])}
        if selected not in allowed:
            return False
    for dependency in without_values:
        if not isinstance(dependency, dict):
            return False
        if str(selections.get(str(dependency.get("id", "")), "")).strip():
            return False
    return True


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
    shipping_rate_id: str | None = None,
    handling_time: str = "PT24H",
    shipment_date: str | None = None,
    responsible_producer_id: str | None = None,
    responsible_person_id: str | None = None,
    safety_information: str | None = None,
) -> dict:
    if not product.get("image_url"):
        raise ValueError("A termékhez nincs kép URL, ezért nem tölthető fel.")
    if not category.get("leaf"):
        raise ValueError("Ajánlat csak levélkategóriában hozható létre.")
    if not category.get("offer_creation_enabled"):
        raise ValueError("Ebben a kategóriában nem engedélyezett a katalógustermékes ajánlat.")
    if not category.get("product_creation_enabled"):
        raise ValueError("Ebben a kategóriában nem engedélyezett saját katalógustermék létrehozása.")
    gtin_parameters = [parameter for parameter in category.get("parameters", []) if parameter.get("is_gtin")]
    provided_gtin = any(str(selections.get(str(parameter.get("id")), "")).strip() for parameter in gtin_parameters)
    gtin_required = any(parameter_is_required(parameter, selections) for parameter in gtin_parameters)
    if gtin_required and not provided_gtin:
        raise ValueError("Ebben a kategóriában új termékhez kötelező a GTIN/EAN.")

    product_parameters: list[dict] = []
    offer_parameters: list[dict] = []
    missing: list[str] = []
    for parameter in category.get("parameters", []):
        value = selections.get(str(parameter["id"]))
        serialized = serialize_parameter(parameter, value)
        required = parameter_is_required(parameter, selections)
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
    shipping_rate_id = (shipping_rate_id or "").strip()
    if not shipping_rate_id:
        raise ValueError("Válassz szállítási árlistát.")
    handling_time = handling_time.strip()
    if not re.fullmatch(r"P(?:\d+D|T\d+H)", handling_time):
        raise ValueError("Érvénytelen feladási idő.")
    producer_id = (responsible_producer_id or "").strip()
    if not producer_id:
        raise ValueError("Válaszd ki a termék gyártójának GPSR-adatait.")
    safety_text = (safety_information or "").strip()
    if not 1 <= len(safety_text) <= 5000:
        raise ValueError("A biztonsági információ 1–5000 karakter lehet.")
    delivery: dict[str, Any] = {
        "shippingRates": {"id": shipping_rate_id},
        "handlingTime": handling_time,
    }
    if shipment_date:
        normalized_date = shipment_date.strip()
        try:
            parsed_date = datetime.fromisoformat(normalized_date.replace("Z", "+00:00"))
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            if parsed_date <= datetime.now(timezone.utc):
                raise ValueError
        except ValueError as exc:
            raise ValueError("Az előrendelés várható feladási ideje jövőbeli dátum legyen.") from exc
        delivery["shipmentDate"] = normalized_date
    product_set_item: dict[str, Any] = {
        "product": {
            "name": str(product["title"])[:75],
            "category": {"id": str(category["id"])},
            "parameters": product_parameters,
            "images": [image],
        },
        "responsibleProducer": {"type": "ID", "id": producer_id},
        "safetyInformation": {"type": "TEXT", "description": safety_text},
        "marketedBeforeGPSRObligation": False,
    }
    person_id = (responsible_person_id or "").strip()
    if person_id:
        product_set_item["responsiblePerson"] = {"id": person_id}
    payload: dict[str, Any] = {
        "productSet": [product_set_item],
        "name": str(product["title"])[:75],
        "category": {"id": str(category["id"])},
        "parameters": offer_parameters,
        "sellingMode": {
            "format": "BUY_NOW",
            "price": {"amount": price, "currency": currency},
        },
        "stock": {"available": stock, "unit": "UNIT"},
        "delivery": delivery,
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

    def shipping_rates(self, marketplace_id: str | None = None) -> list[dict]:
        marketplace_id = marketplace_id or self.marketplace()["id"]
        body = self.client.request(
            "GET", "/sale/shipping-rates", query={"marketplace": marketplace_id}
        )["body"]
        return [item for item in body.get("shippingRates", []) if isinstance(item, dict)]

    def responsible_producers(self) -> list[dict]:
        body = self.client.request(
            "GET", "/sale/responsible-producers", query={"limit": "1000", "offset": "0"}
        )["body"]
        return [item for item in body.get("responsibleProducers", []) if isinstance(item, dict)]

    def responsible_persons(self) -> list[dict]:
        body = self.client.request(
            "GET", "/sale/responsible-persons", query={"limit": "1000", "offset": "0"}
        )["body"]
        return [item for item in body.get("responsiblePersons", []) if isinstance(item, dict)]

    def upload_options(self) -> dict:
        marketplace = self.marketplace()
        return {
            "marketplace": marketplace,
            "shipping_rates": self.shipping_rates(marketplace["id"]),
            "responsible_producers": self.responsible_producers(),
            "responsible_persons": self.responsible_persons(),
        }

    def _validate_account_choices(
        self,
        marketplace_id: str,
        shipping_rate_id: str,
        responsible_producer_id: str,
        responsible_person_id: str,
    ) -> None:
        rates = self.shipping_rates(marketplace_id)
        if not any(str(item.get("id")) == shipping_rate_id for item in rates):
            raise ValueError("A kiválasztott szállítási árlista nem használható ezen a piacon.")
        producers = self.responsible_producers()
        producer = next(
            (item for item in producers if str(item.get("id")) == responsible_producer_id), None
        )
        if producer is None:
            raise ValueError("A kiválasztott gyártói GPSR-rekord nem található a fiókban.")
        producer_data = producer.get("producerData") if isinstance(producer.get("producerData"), dict) else {}
        address = producer_data.get("address") if isinstance(producer_data.get("address"), dict) else {}
        country_code = str(address.get("countryCode", "")).upper()
        if country_code and country_code not in EU_COUNTRY_CODES and not responsible_person_id:
            raise ValueError("EU-n kívüli gyártóhoz válassz EU-s felelős személyt.")
        if responsible_person_id:
            persons = self.responsible_persons()
            if not any(str(item.get("id")) == responsible_person_id for item in persons):
                raise ValueError("A kiválasztott felelős személy nem található a fiókban.")

    def preview(
        self,
        product_id: int,
        category: dict,
        selections: dict[str, Any],
        price_amount: str | None = None,
        stock_available: str | int | None = None,
        shipping_rate_id: str = "",
        handling_time: str = "PT24H",
        shipment_date: str = "",
        responsible_producer_id: str = "",
        responsible_person_id: str = "",
        safety_information: str = "",
    ) -> dict:
        product = self.database.get_product(product_id)
        marketplace = self.marketplace()
        if marketplace["currency"] != "HUF" and not (price_amount or "").strip():
            raise ValueError(
                f"A fiók alappénzneme {marketplace['currency']}, ezért adj meg külön tesztárat ebben a pénznemben."
            )
        self._validate_account_choices(
            marketplace["id"], shipping_rate_id, responsible_producer_id, responsible_person_id
        )
        payload = build_offer_payload(
            product,
            category,
            selections,
            currency=marketplace["currency"],
            language=marketplace["language"],
            price_amount=price_amount,
            stock_available=stock_available,
            shipping_rate_id=shipping_rate_id,
            handling_time=handling_time,
            shipment_date=shipment_date or None,
            responsible_producer_id=responsible_producer_id,
            responsible_person_id=responsible_person_id,
            safety_information=safety_information,
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
        shipping_rate_id: str = "",
        handling_time: str = "PT24H",
        shipment_date: str = "",
        responsible_producer_id: str = "",
        responsible_person_id: str = "",
        safety_information: str = "",
    ) -> dict:
        if confirmation.strip().upper() != "FELTÖLTÉS":
            raise ValueError("A létrehozáshoz írd be pontosan: FELTÖLTÉS")
        preview = self.preview(
            product_id, category, selections, price_amount, stock_available,
            shipping_rate_id, handling_time, shipment_date, responsible_producer_id,
            responsible_person_id, safety_information,
        )
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
