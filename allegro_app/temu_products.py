from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any
from urllib.parse import urlparse

from .database import Database
from .temu import TemuClient, TemuError


TEMU_V3_ADD = "temu.local.goods.v3.add"
TEMU_PUBLISH_STATUS = "bg.local.goods.publish.status.get"


def _text(value: object, maximum: int) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:maximum]


def _https_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and bool(parsed.netloc) else ""


def _unique(values: list[str], maximum: int) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
        if len(result) >= maximum:
            break
    return result


def _positive_number(value: object, fallback: str, label: str) -> str:
    raw = str(value or fallback).strip().replace(",", ".")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"A(z) {label} csak szám lehet.") from exc
    if number <= 0:
        raise ValueError(f"A(z) {label} legyen nagyobb nullánál.")
    normalized = format(number.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _price(value: object, currency: str) -> str:
    raw = str(value or "").strip().replace(" ", "").replace(",", ".")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Minden Temu SKU-hoz érvényes ár szükséges.") from exc
    if number <= 0:
        raise ValueError("Minden Temu SKU ára legyen nagyobb nullánál.")
    if currency in {"HUF", "JPY", "KRW"}:
        if number != number.to_integral_value():
            raise ValueError(f"A {currency} ár csak egész szám lehet.")
        return str(int(number))
    return f"{number.quantize(Decimal('0.01')):.2f}"


def _option(options: dict[str, Any], name: str, default: object = "") -> object:
    value = options.get(name, default)
    return default if value is None or value == "" else value


def build_temu_v3_payload(products: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
    """Build and validate a Product Publishing API V3 request body."""
    if not products:
        raise ValueError("Válassz legalább egy termékváltozatot.")
    if len(products) > 500:
        raise ValueError("Egy Temu-termék legfeljebb 500 SKU-t tartalmazhat.")
    if any(str(row.get("marketplace", "allegro")) != "temu_api_v3" for row in products):
        raise ValueError("A Temu API-ba csak a külön Temu API exportból importált termék tölthető fel.")

    parent_ids = {str(row.get("parent_sku") or row.get("name") or "").strip() for row in products}
    if len(parent_ids) != 1:
        raise ValueError("Egy feltöltésben csak egy WooCommerce termékcsalád szerepelhet.")

    external_goods_id = _text(_option(options, "external_goods_id", next(iter(parent_ids))), 128)
    goods_name = _text(_option(options, "goods_name", products[0].get("name", "")), 500)
    ext_cat_name = _text(_option(options, "category_name", products[0].get("type", "")), 500)
    if not external_goods_id:
        raise ValueError("Hiányzik a külső termékazonosító.")
    if not goods_name:
        raise ValueError("Hiányzik a Temu-terméknév.")
    if not ext_cat_name:
        raise ValueError("Add meg a Temu számára értelmezhető kategórianevet.")

    currency = _text(_option(options, "currency", "HUF"), 3).upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("A pénznem hárombetűs ISO-kód legyen, például HUF.")
    language = _text(_option(options, "language", "hu"), 16)
    product_type = int(_option(options, "product_type", 1))
    if product_type not in {1, 2, 3, 4}:
        raise ValueError("A Temu terméktípus csak 1, 2, 3 vagy 4 lehet.")
    shipment_days = int(_option(options, "shipment_limit_day", 2))
    if shipment_days < 1 or shipment_days > 30:
        raise ValueError("A feladási idő 1–30 nap legyen.")

    default_weight = _positive_number(_option(options, "weight_g", 180), "180", "csomagsúly")
    package_length = _positive_number(_option(options, "length_cm", 30), "30", "csomaghossz")
    package_width = _positive_number(_option(options, "width_cm", 25), "25", "csomagszélesség")
    package_height = _positive_number(_option(options, "height_cm", 3), "3", "csomagmagasság")

    sku_list: list[dict[str, Any]] = []
    sku_ids: set[str] = set()
    variation_keys: set[tuple[tuple[str, str], ...]] = set()
    variant_images: list[str] = []
    for product in products:
        external_sku = _text(product.get("sku", ""), 128)
        if not external_sku:
            raise ValueError("Minden változathoz szükséges SKU.")
        if external_sku in sku_ids:
            raise ValueError(f"Ismétlődő SKU a feltöltésben: {external_sku}")
        sku_ids.add(external_sku)

        image = _https_url(product.get("image_url"))
        if not image:
            raise ValueError(f"A(z) {external_sku} SKU-hoz nyilvános HTTPS-kép szükséges.")
        variant_images.append(image)

        variations = []
        for name, field in (("Type", "type"), ("Color", "color"), ("Size", "size")):
            value = _text(product.get(field, ""), 128)
            if value:
                variations.append({"name": name, "value": value})
        if not variations:
            raise ValueError(f"A(z) {external_sku} SKU-hoz legalább egy variáció szükséges.")
        variation_key = tuple((row["name"], row["value"]) for row in variations)
        if variation_key in variation_keys:
            raise ValueError(f"Ismétlődő Temu-variáció: {external_sku}")
        variation_keys.add(variation_key)

        stock = int(product.get("stock", 0))
        if stock < 0:
            raise ValueError(f"A(z) {external_sku} készlete nem lehet negatív.")
        weight = _positive_number(product.get("weight_g") or default_weight, default_weight, "csomagsúly")
        sku_list.append({
            "externalSkuId": external_sku,
            "images": [image],
            "price": {"basePrice": {"amount": _price(product.get("price_huf"), currency), "currency": currency}},
            "quantity": stock,
            "packageInfo": {
                "weight": weight,
                "length": package_length,
                "width": package_width,
                "height": package_height,
            },
            "variations": variations,
        })

    common_images = _unique([
        _https_url(row.get("common_image_url")) for row in products
    ], 10)
    carousel = _unique(common_images + variant_images, 10)

    attributes: list[dict[str, Any]] = []
    defaults = (
        ("Brand", products[0].get("brand")),
        ("Material", products[0].get("material")),
        ("Country/Region of Origin", options.get("origin_country")),
        ("Manufacturer", options.get("manufacturer")),
    )
    for name, value in defaults:
        normalized = _text(value, 128)
        if normalized:
            attributes.append({"name": name, "value": [normalized]})
    for row in options.get("attributes") or []:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("name"), 128)
        raw_values = row.get("value") if isinstance(row.get("value"), list) else [row.get("value")]
        values = _unique([_text(value, 128) for value in raw_values], 1000)
        if name and values and not any(item["name"].casefold() == name.casefold() for item in attributes):
            attributes.append({"name": name, "value": values})
        if len(attributes) >= 200:
            break

    goods_basic: dict[str, Any] = {
        "externalGoodsId": external_goods_id,
        "goodsName": goods_name,
        "extCatName": ext_cat_name,
        "goodsDesc": str(_option(options, "goods_description", products[0].get("description", "")))[:10_000],
        "goodsCarouselImage": carousel,
        "productType": product_type,
        "shipmentLimitDay": shipment_days,
    }
    if common_images:
        goods_basic["detailImage"] = common_images[:50]

    payload: dict[str, Any] = {"language": language, "goodsBasic": goods_basic, "skuList": sku_list}
    if attributes:
        payload["attributes"] = attributes
    return payload


class TemuProductService:
    def __init__(self, database: Database, client: TemuClient):
        self.database = database
        self.client = client

    def preview(self, product_ids: list[int], options: dict[str, Any]) -> dict[str, Any]:
        products = self.database.get_products(product_ids)
        payload = build_temu_v3_payload(products, options)
        return {
            "api_method": TEMU_V3_ADD,
            "ready_to_publish": True,
            "payload": payload,
            "summary": {
                "external_goods_id": payload["goodsBasic"]["externalGoodsId"],
                "sku_count": len(payload["skuList"]),
                "stock": sum(int(row["quantity"]) for row in payload["skuList"]),
                "carousel_images": len(payload["goodsBasic"]["goodsCarouselImage"]),
                "image_count": len({
                    image for row in payload["skuList"] for image in row["images"]
                } | set(payload["goodsBasic"]["goodsCarouselImage"])),
            },
        }

    def create(self, product_ids: list[int], options: dict[str, Any], confirmation: str) -> dict[str, Any]:
        if confirmation.strip().upper() != "FELTÖLTÉS":
            raise ValueError('A tényleges Temu-feltöltéshez írd be: FELTÖLTÉS')
        preview = self.preview(product_ids, options)
        payload = preview["payload"]
        try:
            response = self.client.request(TEMU_V3_ADD, payload)
        except Exception as exc:
            self.database.record_temu_upload(payload, None, "error", str(exc))
            raise
        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        goods_id = str(result.get("goodsId", ""))
        if not goods_id:
            message = "A Temu sikeres választ adott, de nem küldött goodsId azonosítót."
            self.database.record_temu_upload(payload, response, "error", message)
            raise TemuError(message)
        upload = self.database.record_temu_upload(payload, response, "created", "")
        self.database.mark_temu_created(product_ids, goods_id, "created")
        self.database.add_activity("upload", f"Temu V3 termék létrehozva: {goods_id}")
        return {"ok": True, "goods_id": goods_id, "request_id": response.get("requestId", ""), "upload": upload}

    def refresh_status(self, upload_id: int) -> dict[str, Any]:
        upload = self.database.get_temu_upload(upload_id)
        goods_id = str(upload.get("goods_id", ""))
        if not goods_id:
            raise ValueError("Ehhez a feltöltéshez nincs Temu goodsId.")
        response = self.client.request(TEMU_PUBLISH_STATUS, {"goodsIdList": [int(goods_id)]})
        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        statuses = result.get("goodsPublishStatusList") if isinstance(result.get("goodsPublishStatusList"), list) else []
        status_row = statuses[0] if statuses and isinstance(statuses[0], dict) else {}
        status = str(status_row.get("status", "unknown"))
        sub_status = str(status_row.get("subStatus", ""))
        label = f"status={status}" + (f", subStatus={sub_status}" if sub_status else "")
        updated = self.database.update_temu_upload_status(upload_id, label, response)
        self.database.update_temu_product_status(goods_id, label)
        return {"ok": True, "status": status, "sub_status": sub_status, "upload": updated}
