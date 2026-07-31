from __future__ import annotations

import html
from html.parser import HTMLParser
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .allegro import AllegroClient, AllegroError
from .config import AppConfig
from .database import Database


EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
    "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
    "RO", "SK", "SI", "ES", "SE",
}

# Verified live against the Allegro.hu T-shirt categories on 2026-07-30.
# Adult categories 87913/76104 share the first pair; child category 89528
# uses the second pair. Width means the laid-flat armpit-to-armpit width.
MEASUREMENT_PARAMETER_SOURCES = {
    "201033": "length_cm",  # Teljes hosszúság (adult)
    "201041": "width_cm",   # Szélesség hónalj alatt (adult)
    "202517": "length_cm",  # Teljes hosszúság (child)
    "202513": "width_cm",   # Szélesség a hónaljnál (child)
}

# Category-specific dictionary defaults verified live on 2026-07-30.
DEFAULT_PARAMETER_VALUES = {
    "3766": "3766_218065",       # Adult Fő minta: mintás (nyomatos)
    "202497": "202497_680829",   # Child Fő minta: nyomott mintás
    "249926": "249926_1783211",  # Nyomtatási terület: elülső
}


class _AllegroDescriptionParser(HTMLParser):
    """Convert ordinary WooCommerce HTML to Allegro's restricted HTML."""

    BLOCK_TAGS = {"h1", "h2", "p", "ul", "ol", "li"}
    TAG_MAP = {"strong": "b", "h3": "h2", "h4": "h2", "h5": "h2", "h6": "h2"}
    BOUNDARY_TAGS = {
        "address", "article", "aside", "blockquote", "div", "footer", "header",
        "main", "nav", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def _close(self, tag: str) -> None:
        if tag not in self.stack:
            return
        while self.stack:
            current = self.stack.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break

    def _close_text_block(self) -> None:
        for tag in reversed(self.stack):
            if tag in {"p", "h1", "h2"}:
                self._close(tag)
                return
            if tag in {"li", "ul", "ol"}:
                return

    def _inside(self, *tags: str) -> bool:
        return any(tag in self.stack for tag in tags)

    def _open_text_container(self) -> None:
        if self._inside("p", "h1", "h2", "li"):
            return
        if self._inside("ul", "ol"):
            self.parts.append("<li>")
            self.stack.append("li")
        else:
            self.parts.append("<p>")
            self.stack.append("p")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = self.TAG_MAP.get(tag.lower(), tag.lower())
        if tag in {"script", "style"}:
            self.stack.append(f"__skip_{tag}")
            return
        if any(item.startswith("__skip_") for item in self.stack):
            return
        if tag in {"h1", "h2", "p"}:
            self._close_text_block()
            self.parts.append(f"<{tag}>")
            self.stack.append(tag)
        elif tag in {"ul", "ol"}:
            self._close_text_block()
            self.parts.append(f"<{tag}>")
            self.stack.append(tag)
        elif tag == "li":
            self._close("li")
            if not self._inside("ul", "ol"):
                self.parts.append("<ul>")
                self.stack.append("ul")
            self.parts.append("<li>")
            self.stack.append("li")
        elif tag == "b":
            if self._inside("h1", "h2"):
                return
            self._open_text_container()
            if not self._inside("b"):
                self.parts.append("<b>")
                self.stack.append("b")
        elif tag == "br":
            self.parts.append(" ")
        elif tag in self.BOUNDARY_TAGS:
            self._close_text_block()

    def handle_endtag(self, tag: str) -> None:
        raw_tag = tag.lower()
        skip_tag = f"__skip_{raw_tag}"
        if skip_tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                if current == skip_tag:
                    break
            return
        if any(item.startswith("__skip_") for item in self.stack):
            return
        tag = self.TAG_MAP.get(raw_tag, raw_tag)
        if tag in self.BLOCK_TAGS or tag == "b":
            self._close(tag)
        elif tag in self.BOUNDARY_TAGS:
            self._close_text_block()

    def handle_data(self, data: str) -> None:
        if any(item.startswith("__skip_") for item in self.stack):
            return
        if not data.strip() and not self._inside("p", "h1", "h2", "li", "b"):
            return
        self._open_text_container()
        self.parts.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            current = self.stack.pop()
            if not current.startswith("__skip_"):
                self.parts.append(f"</{current}>")
        return "".join(self.parts).strip()


def sanitize_description_html(value: str) -> str:
    parser = _AllegroDescriptionParser()
    parser.feed(value)
    parser.close()
    return parser.result()


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(char for char in value if not unicodedata.combining(char)).casefold().strip()


def suggested_parameter_source(parameter: dict) -> str | None:
    parameter_id = str(parameter.get("id", ""))
    if parameter_id in MEASUREMENT_PARAMETER_SOURCES:
        return MEASUREMENT_PARAMETER_SOURCES[parameter_id]
    if parameter_id in DEFAULT_PARAMETER_VALUES:
        return "allegro_default"
    name = _fold(str(parameter.get("name", "")))
    if name in {"model", "modell"}:
        return "model"
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


def product_model_name(product: dict, max_length: int = 50) -> str:
    name = re.sub(r"\s+", " ", str(product.get("name", ""))).strip()
    type_label = re.sub(
        r"\s+", " ", str(product.get("type_label") or product.get("type", "")).replace("-", " ").replace("_", " ")
    ).strip()
    color = re.sub(r"\s+", " ", str(product.get("color", ""))).strip()
    extras: list[str] = []
    comparison = _fold(name)
    for part in (type_label, color):
        if part and _fold(part) not in comparison:
            extras.append(part)
            comparison = _fold(" ".join([name, *extras]))
    suffix = " ".join(extras)
    if suffix:
        available = max_length - len(suffix) - 1
        if available <= 0:
            return suffix[:max_length].rstrip()
        if len(name) > available:
            shortened = name[:available]
            if not shortened.endswith(" ") and not name[available].isspace() and " " in shortened:
                shortened = shortened.rsplit(" ", 1)[0]
            name = shortened.rstrip() or name[:available].rstrip()
    model = " ".join(part for part in (name, suffix) if part)
    return model[:max_length].rstrip()


def suggested_parameter_value(parameter: dict, product: dict) -> str:
    default = DEFAULT_PARAMETER_VALUES.get(str(parameter.get("id", "")))
    if default:
        dictionary_ids = {
            str(item.get("id", ""))
            for item in (parameter.get("dictionary") or [])
            if isinstance(item, dict)
        }
        return default if not dictionary_ids or default in dictionary_ids else ""
    source = suggested_parameter_source(parameter)
    if source == "model":
        restrictions = parameter.get("restrictions") if isinstance(parameter.get("restrictions"), dict) else {}
        candidate = product_model_name(product, int(restrictions.get("maxLength") or 50))
    else:
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
    content = sanitize_description_html(value.strip())
    if not content:
        content = "<p>Termékadatok feltöltése folyamatban.</p>"
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
    tax_setting: dict[str, str] | None = None,
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
    if tax_setting:
        tax_settings: dict[str, Any] = {
            "rates": [{
                "rate": str(tax_setting["rate"]),
                "countryCode": str(tax_setting["country_code"]),
            }],
            "subject": str(tax_setting["subject"]),
        }
        exemption = str(tax_setting.get("exemption", "")).strip()
        if exemption:
            tax_settings["exemption"] = exemption
        payload["taxSettings"] = tax_settings
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

    @staticmethod
    def _tax_value(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("id") or value.get("value") or value.get("name") or "")
        return str(value or "")

    def tax_settings(self, category_id: str, country_code: str = "HU") -> list[dict]:
        category_id = category_id.strip()
        country_code = country_code.strip().upper() or "HU"
        if not category_id:
            raise ValueError("Az áfakulcsok lekéréséhez hiányzik a kategória.")
        body = self.client.request(
            "GET",
            "/sale/tax-settings",
            query={"category.id": category_id, "countryCode": country_code},
        )["body"]
        result: list[dict] = []
        for setting in body.get("settings", []):
            if not isinstance(setting, dict) or not setting.get("id"):
                continue
            rate = self._tax_value(setting.get("rate"))
            subject = self._tax_value(setting.get("subject"))
            exemption = self._tax_value(setting.get("exemption"))
            setting_country = str(setting.get("countryCode") or country_code).upper()
            result.append({
                "id": str(setting["id"]),
                "country_code": setting_country,
                "rate": rate,
                "subject": subject,
                "exemption": exemption,
                "label": (
                    f"{setting_country} · {rate}% · "
                    f"{'termék' if subject.upper() == 'GOODS' else subject.lower()}"
                    + (f" · {exemption}" if exemption else "")
                ),
            })
        return result

    @staticmethod
    def default_tax_setting_id(settings: list[dict]) -> str:
        for setting in settings:
            rate = str(setting.get("rate", "")).replace("%", "").strip()
            if (
                rate in {"27", "27.0", "27.00"}
                and str(setting.get("subject", "")).upper() == "GOODS"
                and not str(setting.get("exemption", "")).strip()
            ):
                return str(setting.get("id", ""))
        return ""

    def resolve_tax_setting_id(
        self, category_id: str, selected_id: str = "", country_code: str = "HU"
    ) -> tuple[str, list[dict]]:
        settings = self.tax_settings(category_id, country_code)
        selected_id = selected_id.strip()
        if selected_id:
            if not any(setting["id"] == selected_id for setting in settings):
                raise ValueError("A sablonban mentett áfakulcs már nem használható ebben a kategóriában.")
            return selected_id, settings
        default_id = self.default_tax_setting_id(settings)
        if not default_id:
            raise ValueError("Ehhez a kategóriához nem található magyar 27%-os termék-áfakulcs.")
        return default_id, settings

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
        tax_setting_id: str = "",
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
        resolved_tax_setting_id, tax_settings = self.resolve_tax_setting_id(
            str(category["id"]), tax_setting_id, "HU"
        )
        resolved_tax_setting = next(
            setting for setting in tax_settings if setting["id"] == resolved_tax_setting_id
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
            tax_setting=resolved_tax_setting,
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
        tax_setting_id: str = "",
    ) -> dict:
        if confirmation.strip().upper() != "FELTÖLTÉS":
            raise ValueError("A létrehozáshoz írd be pontosan: FELTÖLTÉS")
        preview = self.preview(
            product_id, category, selections, price_amount, stock_available,
            shipping_rate_id, handling_time, shipment_date, responsible_producer_id,
            responsible_person_id, safety_information, tax_setting_id,
        )
        response = self.client.request("POST", "/sale/product-offers", body=preview["payload"])
        offer_id = self._offer_id(response)
        self.database.mark_offer_created(product_id, str(category["id"]), offer_id)
        return {
            "ok": True,
            "status": response["status"],
            "offer_id": offer_id,
            "publication": "INACTIVE",
            "operation": response["headers"].get("location"),
            "marketplace": preview["marketplace"],
        }

    @staticmethod
    def _offer_id(response: dict) -> str | None:
        body = response["body"] if isinstance(response["body"], dict) else {}
        offer_id = str(body.get("id", "")) or None
        if not offer_id:
            location = response["headers"].get("location", "")
            match = re.search(r"/product-offers/([^/]+)", location)
            offer_id = match.group(1) if match else None
        return offer_id

    @staticmethod
    def _bulk_result(product: dict, state: str, message: str = "") -> dict:
        return {
            "product_id": int(product["id"]),
            "sku": str(product["sku"]),
            "title": str(product["title"]),
            "type": str(product["type"]),
            "color": str(product["color"]),
            "size": str(product["size"]),
            "state": state,
            "message": message,
        }

    def _prepare_bulk(
        self,
        import_id: int,
        template_assignments: dict[str, Any],
        category_lookup: Callable[[str], dict],
    ) -> tuple[dict, list[dict]]:
        products = self.database.get_import_batch_products(import_id, "allegro")
        product_types = sorted({str(product["type"]) for product in products})
        missing_types = [item for item in product_types if not template_assignments.get(item)]
        if missing_types:
            raise ValueError("Nincs sablon hozzárendelve ezekhez a típusokhoz: " + ", ".join(missing_types))

        marketplace = self.marketplace()

        contexts: dict[str, tuple[dict, dict, dict[str, dict[str, str]], dict[str, str]]] = {}
        validated_choices: set[tuple[str, str, str]] = set()
        tax_settings_cache: dict[str, list[dict]] = {}
        for product_type in product_types:
            try:
                template_id = int(template_assignments[product_type])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Érvénytelen sablonazonosító ehhez: {product_type}") from exc
            template = self.database.get_offer_template(template_id)
            category = category_lookup(str(template["category_id"]))
            rules = {
                str(rule.get("parameter_id")): rule
                for rule in template.get("rules", [])
                if isinstance(rule, dict) and rule.get("parameter_id")
            }
            category_id = str(category["id"])
            if category_id not in tax_settings_cache:
                tax_settings_cache[category_id] = self.tax_settings(category_id, "HU")
            selected_tax_id = str(rules.get("__tax_setting__", {}).get("value", "")).strip()
            available_tax_settings = tax_settings_cache[category_id]
            if selected_tax_id:
                if not any(setting["id"] == selected_tax_id for setting in available_tax_settings):
                    raise ValueError(
                        f"A(z) {template['name']} sablonban mentett áfakulcs már nem használható."
                    )
            else:
                selected_tax_id = self.default_tax_setting_id(available_tax_settings)
            if not selected_tax_id:
                raise ValueError(
                    f"A(z) {template['name']} kategóriájában nem található magyar 27%-os termék-áfakulcs."
                )
            resolved_tax_setting = next(
                setting for setting in available_tax_settings if setting["id"] == selected_tax_id
            )
            preorder = rules.get("__preorder__", {}).get("value", "false").lower() == "true"
            if preorder:
                raise ValueError(
                    f"A(z) {template['name']} sablon előrendelést kér, de nincs benne feladási dátum. "
                    "Ehhez használd az egyedi feltöltést."
                )
            price_rule = rules.get("__price__", {})
            if price_rule.get("mode") == "fixed" and not str(price_rule.get("value", "")).strip():
                raise ValueError(f"A(z) {template['name']} sablonban nincs megadva a fix ár.")
            shipping_rate_id = str(rules.get("__shipping_rate__", {}).get("value", ""))
            producer_id = str(rules.get("__producer__", {}).get("value", ""))
            person_id = str(rules.get("__responsible_person__", {}).get("value", ""))
            choice = (shipping_rate_id, producer_id, person_id)
            if choice not in validated_choices:
                self._validate_account_choices(marketplace["id"], *choice)
                validated_choices.add(choice)
            contexts[product_type] = (template, category, rules, resolved_tax_setting)

        if marketplace["currency"] != "HUF":
            product_price_types = [
                product_type for product_type, (_, _, rules, _) in contexts.items()
                if rules.get("__price__", {}).get("mode") != "fixed"
            ]
            if product_price_types:
                raise ValueError(
                    f"A fiók alappénzneme {marketplace['currency']}. Adj meg fix árat a sablonban ezekhez: "
                    + ", ".join(product_price_types)
                )

        rows: list[dict] = []
        for product in products:
            if product.get("allegro_offer_id") or product.get("status") == "inactive":
                row = self._bulk_result(product, "skipped", "Már fel lett töltve; kihagyva.")
                row["offer_id"] = product.get("allegro_offer_id")
                rows.append(row)
                continue
            template, category, rules, tax_setting = contexts[str(product["type"])]
            try:
                selections: dict[str, Any] = {}
                for parameter in category.get("parameters", []):
                    parameter_id = str(parameter.get("id", ""))
                    rule = rules.get(parameter_id)
                    if rule and rule.get("mode") == "fixed":
                        value = rule.get("value", "")
                    elif rule and rule.get("mode") == "product":
                        value = suggested_parameter_value(parameter, product)
                    elif suggested_parameter_source(parameter):
                        value = suggested_parameter_value(parameter, product)
                    else:
                        value = ""
                    if str(value).strip():
                        selections[parameter_id] = value

                stock_rule = rules.get("__stock__", {})
                stock_available = (
                    str(stock_rule.get("value", ""))
                    if stock_rule.get("mode") == "fixed"
                    else None
                )
                price_rule = rules.get("__price__", {})
                price_amount = (
                    str(price_rule.get("value", ""))
                    if price_rule.get("mode") == "fixed"
                    else None
                )
                payload = build_offer_payload(
                    product,
                    category,
                    selections,
                    currency=marketplace["currency"],
                    language=marketplace["language"],
                    price_amount=price_amount,
                    stock_available=stock_available,
                    shipping_rate_id=str(rules.get("__shipping_rate__", {}).get("value", "")),
                    handling_time=str(rules.get("__handling_time__", {}).get("value", "PT24H")),
                    responsible_producer_id=str(rules.get("__producer__", {}).get("value", "")),
                    responsible_person_id=str(rules.get("__responsible_person__", {}).get("value", "")),
                    safety_information=str(rules.get("__safety_information__", {}).get("value", "")),
                    tax_setting=tax_setting,
                )
                row = self._bulk_result(product, "ready")
                row.update({"category_id": str(category["id"]), "template_name": template["name"]})
                row["_payload"] = payload
                rows.append(row)
            except Exception as exc:
                row = self._bulk_result(product, "error", str(exc))
                row.update({"category_id": str(category["id"]), "template_name": template["name"]})
                rows.append(row)
        return marketplace, rows

    @staticmethod
    def _bulk_summary(rows: list[dict]) -> dict:
        return {
            "total": len(rows),
            "ready": sum(1 for row in rows if row["state"] == "ready"),
            "created": sum(1 for row in rows if row["state"] == "created"),
            "skipped": sum(1 for row in rows if row["state"] == "skipped"),
            "errors": sum(1 for row in rows if row["state"] == "error"),
        }

    def preview_bulk(
        self,
        import_id: int,
        template_assignments: dict[str, Any],
        category_lookup: Callable[[str], dict],
    ) -> dict:
        marketplace, rows = self._prepare_bulk(import_id, template_assignments, category_lookup)
        public_rows = [{key: value for key, value in row.items() if key != "_payload"} for row in rows]
        return {
            "ok": True,
            "import_id": import_id,
            "marketplace": marketplace,
            "summary": self._bulk_summary(public_rows),
            "rows": public_rows,
        }

    def create_bulk(
        self,
        import_id: int,
        template_assignments: dict[str, Any],
        category_lookup: Callable[[str], dict],
        confirmation: str,
    ) -> dict:
        if confirmation.strip().upper() != "FELTÖLTÉS":
            raise ValueError("A tömeges létrehozáshoz írd be pontosan: FELTÖLTÉS")
        marketplace, rows = self._prepare_bulk(import_id, template_assignments, category_lookup)
        for row in rows:
            if row["state"] != "ready":
                continue
            payload = row.pop("_payload")
            try:
                response = self.client.request("POST", "/sale/product-offers", body=payload)
                offer_id = self._offer_id(response)
                self.database.mark_offer_created(row["product_id"], row["category_id"], offer_id)
                row.update({
                    "state": "created",
                    "message": "Inaktív ajánlat létrehozva.",
                    "offer_id": offer_id,
                    "http_status": response["status"],
                })
            except Exception as exc:
                row.update({"state": "error", "message": str(exc)})
        return {
            "ok": True,
            "import_id": import_id,
            "marketplace": marketplace,
            "summary": self._bulk_summary(rows),
            "rows": rows,
        }
