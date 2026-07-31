from __future__ import annotations

import base64
from datetime import datetime, timedelta
import math
from pathlib import Path
import re
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .config import AppConfig
from .database import Database
from .express_one import ExpressOneClient, ExpressOneError
from .temu import TemuClient, TemuError


TEMU_ORDER_DETAIL = "bg.order.detail.v2.get"
TEMU_ORDER_SHIPPING = "bg.order.shippinginfo.v2.get"
TEMU_ORDER_DECRYPT_SHIPPING = "bg.order.decryptshippinginfo.get"
TEMU_LOGISTICS_COMPANIES = "bg.logistics.companies.get"
TEMU_SHIPMENT_CONFIRM = "bg.logistics.shipment.confirm"


class TemuShippingError(RuntimeError):
    pass


COUNTRY_CODES = {
    "magyarország": "HU", "hungary": "HU", "ungarn": "HU",
    "ausztria": "AT", "austria": "AT", "németország": "DE", "germany": "DE",
    "szlovákia": "SK", "slovakia": "SK", "románia": "RO", "romania": "RO",
    "csehország": "CZ", "czech republic": "CZ", "lengyelország": "PL", "poland": "PL",
    "horvátország": "HR", "croatia": "HR", "szlovénia": "SI", "slovenia": "SI",
}


def _walk_dicts(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_recursive(value: object, keys: tuple[str, ...]) -> object | None:
    for row in _walk_dicts(value):
        for key in keys:
            if row.get(key) not in (None, "", []):
                return row[key]
    return None


def _without_label_data(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: ("[PDF címke eltávolítva a naplóból]" if key == "data" and len(str(item)) > 500 else _without_label_data(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_without_label_data(item) for item in value]
    return value


class TemuShippingService:
    def __init__(self, config: AppConfig, database: Database, temu: TemuClient):
        self.config = config
        self.database = database
        self.temu = temu
        self.express_one = ExpressOneClient(config)

    @staticmethod
    def _order_id(value: str) -> str:
        order_id = value.strip()
        if not re.fullmatch(r"PO-[A-Za-z0-9-]{3,80}", order_id):
            raise TemuShippingError("Érvénytelen Temu rendelésazonosító.")
        return order_id

    def check_connection(self) -> dict[str, Any]:
        result = self.express_one.check_connection()
        self.database.add_activity("connection", "Az Express One API-kapcsolat sikeresen ellenőrizve.")
        return {"ok": True, "response": _without_label_data(result)}

    def _order(self, order_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        result = self.temu._result(self.temu.request(
            TEMU_ORDER_DETAIL, {"request": {"parentOrderSn": order_id}}
        ))
        parent = result.get("parentOrderMap") if isinstance(result.get("parentOrderMap"), dict) else {}
        rows = result.get("orderList") if isinstance(result.get("orderList"), list) else []
        if not parent and isinstance(result.get("parentOrder"), dict):
            parent = result["parentOrder"]
        if not rows and isinstance(result.get("orders"), list):
            rows = result["orders"]
        rows = [row for row in rows if isinstance(row, dict) and int(row.get("quantity", 0) or 0) > 0]
        if not rows:
            raise TemuShippingError("A Temu rendelésben nincs feladható terméksor.")
        return parent, rows

    def _shipping(self, order_id: str) -> dict[str, Any]:
        result = self.temu._result(self.temu.request(
            TEMU_ORDER_SHIPPING, {"request": {"parentOrderSn": order_id}}
        ))
        if isinstance(result.get("shippingInfo"), dict):
            result = {**result, **result["shippingInfo"]}
        required = (result.get("receiptName"), result.get("postCode"), result.get("addressLineAll"))
        masked = any("*" in str(value or "") for value in result.values())
        if not all(str(value or "").strip() for value in required) or masked:
            decrypted = self.temu._result(self.temu.request(
                TEMU_ORDER_DECRYPT_SHIPPING, {"request": {"parentOrderSn": order_id}}
            ))
            if isinstance(decrypted.get("shippingInfo"), dict):
                decrypted = {**decrypted, **decrypted["shippingInfo"]}
            result = {**result, **{key: value for key, value in decrypted.items() if value not in (None, "")}}
        return result

    @staticmethod
    def _country(shipping: dict[str, Any]) -> str:
        for key in ("regionCode1", "countryCode", "country", "regionId1"):
            value = str(shipping.get(key, "")).strip().upper()
            if re.fullmatch(r"[A-Z]{2}", value):
                return value
        name = str(shipping.get("regionName1", "")).strip().casefold()
        code = COUNTRY_CODES.get(name, "")
        if not code:
            raise TemuShippingError(
                f"Az Express One címkéhez nem tudom kétbetűs országkóddá alakítani: {shipping.get('regionName1', 'nincs ország')}."
            )
        return code

    @staticmethod
    def _phone(shipping: dict[str, Any]) -> str:
        raw = next((str(shipping.get(key, "")).strip() for key in (
            "mobile", "phone", "receiptPhoneNumber", "phoneNumber"
        ) if str(shipping.get(key, "")).strip()), "")
        phone = re.sub(r"[^0-9+]", "", raw)
        if phone.startswith("06"):
            phone = "+36" + phone[2:]
        elif phone.startswith("36"):
            phone = "+" + phone
        return phone[:20]

    @staticmethod
    def _city(shipping: dict[str, Any]) -> str:
        return next((str(shipping.get(key, "")).strip() for key in (
            "regionName4", "regionName3", "regionName2", "city"
        ) if str(shipping.get(key, "")).strip()), "")

    def _delivery(self, order_id: str, shipping: dict[str, Any], weight_kg: float) -> dict[str, Any]:
        name = str(shipping.get("receiptName", "")).strip()
        city = self._city(shipping)
        street = str(shipping.get("addressLineAll", "")).strip() or " ".join(
            str(shipping.get(key, "")).strip() for key in ("addressLine1", "addressLine2", "addressLine3")
            if str(shipping.get(key, "")).strip()
        )
        postcode = str(shipping.get("postCode", "")).strip()
        if not all((name, city, street, postcode)):
            raise TemuShippingError("A Temu nem adott teljes nevet, települést, címet és irányítószámot.")
        phone = self._phone(shipping)
        email = str(shipping.get("mail", "")).strip()
        consig: dict[str, Any] = {
            "name": name[:100], "contact_name": name[:100], "city": city[:25],
            "street": street[:100], "country": self._country(shipping), "post_code": postcode[:10],
        }
        if phone:
            consig["phone"] = phone
        services: dict[str, Any] = {"delivery_type": "24H"}
        notification: dict[str, str] = {}
        if email:
            notification["email"] = email[:100]
        if phone:
            notification["sms"] = phone
        if notification:
            services["notification"] = notification
        invoice = self.database.list_temu_order_invoices().get(order_id, [])
        invoice_number = next((str(row.get("invoice_number")) for row in invoice if row.get("invoice_number")), "")
        post_date = datetime.now(ZoneInfo("Europe/Budapest")).date()
        while post_date.weekday() >= 5:
            post_date += timedelta(days=1)
        delivery: dict[str, Any] = {
            "post_date": post_date.isoformat(),
            "consig": consig,
            "parcels": {"type": 0, "qty": 1, "weight": max(1, math.ceil(weight_kg)),
                        "weight_in_gramm": int(round(weight_kg * 1000)), "parcel_name": order_id[:100]},
            "services": services,
            "note": "Temu rendelés",
            "ref_number": order_id[:50],
        }
        if invoice_number:
            delivery["invoice_number"] = invoice_number[:15]
        return delivery

    def _carrier_id(self, region_id: int) -> str:
        configured = self.config.values.get("TEMU_EXPRESS_ONE_CARRIER_ID", "").strip()
        if configured:
            if not configured.isdigit():
                raise TemuShippingError("A Temu Express One carrier ID csak számokat tartalmazhat.")
            return configured
        result = self.temu._result(self.temu.request(
            TEMU_LOGISTICS_COMPANIES, {"regionId": region_id}
        ))
        for row in _walk_dicts(result):
            name = next((str(row.get(key, "")).strip() for key in (
                "shipCompanyName", "carrierName", "companyName", "name"
            ) if str(row.get(key, "")).strip()), "")
            normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
            if "expressone" not in normalized:
                continue
            identifier = next((row.get(key) for key in (
                "shipCompanyId", "carrierId", "companyId", "id"
            ) if row.get(key) not in (None, "")), None)
            if identifier is not None:
                return str(identifier)
        raise TemuShippingError(
            "A Temu fuvarozólistájában nem találtam Express One-t. Add meg kézzel a Temu carrier ID-t a Beállításokban."
        )

    @staticmethod
    def _extract_label(response: dict[str, Any]) -> tuple[str, bytes]:
        parcel_value = _first_recursive(response, ("parcel_numbers", "parcelNumbers", "parcel_number", "parcelNumber"))
        if isinstance(parcel_value, list):
            parcel_value = parcel_value[0] if parcel_value else ""
        if isinstance(parcel_value, dict):
            parcel_value = next(iter(parcel_value.values()), "")
        parcel_number = str(parcel_value or "").strip()
        encoded: object | None = None
        for row in _walk_dicts(response):
            labels = row.get("labels")
            if isinstance(labels, dict) and isinstance(labels.get("data"), str):
                encoded = labels["data"]
                break
            for key in ("labelData", "label_data"):
                if isinstance(row.get(key), str):
                    encoded = row[key]
                    break
            if encoded is not None:
                break
        if not parcel_number or not isinstance(encoded, str):
            message = _first_recursive(response, ("message", "error_messages", "error_message"))
            raise ExpressOneError(
                f"Az Express One válaszából hiányzik a csomagszám vagy a PDF-címke. {message or ''}".strip()
            )
        try:
            label = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
        except (ValueError, TypeError) as exc:
            raise ExpressOneError("Az Express One hibás Base64 PDF-címkét adott vissza.") from exc
        if not label.startswith(b"%PDF"):
            raise ExpressOneError("Az Express One válaszában kapott címke nem PDF.")
        return parcel_number, label

    @staticmethod
    def _confirm_payload(order_id: str, rows: list[dict[str, Any]], carrier_id: str, tracking: str) -> dict[str, Any]:
        items = []
        for row in rows:
            item = {
                "quantity": int(row.get("quantity", 0) or 0), "orderSn": str(row.get("orderSn", "")),
                "parentOrderSn": order_id, "goodsId": int(row.get("goodsId", 0) or 0),
                "skuId": int(row.get("skuId", 0) or 0),
            }
            if not item["orderSn"] or not item["goodsId"] or not item["skuId"]:
                raise TemuShippingError("A Temu rendelés egyik soránál hiányzik az orderSn, goodsId vagy skuId.")
            items.append(item)
        return {"sendType": 0, "sendRequestList": [{
            "orderSendInfoList": items, "carrierId": int(carrier_id), "trackingNumber": tracking,
        }]}

    def preview(self, parent_order_sn: str, weight_kg: object | None = None) -> dict[str, Any]:
        order_id = self._order_id(parent_order_sn)
        parent, rows = self._order(order_id)
        shipping = self._shipping(order_id)
        weight = self._weight(weight_kg)
        carrier_id = self._carrier_id(int(parent.get("regionId", 0) or 0))
        delivery = self._delivery(order_id, shipping, weight)
        return {
            "parent_order_sn": order_id, "carrier_id": carrier_id, "weight_kg": weight,
            "item_count": sum(int(row.get("quantity", 0) or 0) for row in rows),
            "recipient": delivery["consig"], "delivery": delivery,
            "existing": self.database.get_temu_shipment(order_id),
        }

    def _weight(self, value: object | None) -> float:
        raw = str(value if value not in (None, "") else self.config.values.get("EXPRESS_ONE_DEFAULT_WEIGHT_KG", "1"))
        try:
            weight = float(raw.replace(",", "."))
        except ValueError as exc:
            raise TemuShippingError("A csomag tömege szám legyen.") from exc
        if weight <= 0 or weight > 40:
            raise TemuShippingError("A csomag tömege 0 és 40 kg között legyen.")
        return weight

    def create(self, parent_order_sn: str, weight_kg: object, confirmation: str) -> dict[str, Any]:
        order_id = self._order_id(parent_order_sn)
        if confirmation.strip().upper() != "FELADÁS":
            raise TemuShippingError("A feladáshoz írd be pontosan: FELADÁS")
        existing = self.database.get_temu_shipment(order_id)
        if existing and existing.get("status") == "temu_confirmed":
            return existing

        if existing and existing.get("status") in {"label_created", "temu_failed"}:
            confirm_payload = existing.get("temu_request")
            if not isinstance(confirm_payload, dict):
                raise TemuShippingError("A korábbi címkéhez nem található Temu feladási kérés.")
            parcel_number = str(existing.get("parcel_number", ""))
            carrier_id = str(existing.get("carrier_id", ""))
        else:
            parent, rows = self._order(order_id)
            shipping = self._shipping(order_id)
            carrier_id = self._carrier_id(int(parent.get("regionId", 0) or 0))
            delivery = self._delivery(order_id, shipping, self._weight(weight_kg))
            express_response = self.express_one.create_labels([delivery])
            parcel_number, label = self._extract_label(express_response)
            label_dir = self.config.root / "var" / "labels" / "temu"
            label_dir.mkdir(parents=True, exist_ok=True)
            label_path = label_dir / f"{re.sub(r'[^A-Za-z0-9._-]+', '-', order_id)}.pdf"
            label_path.write_bytes(label)
            confirm_payload = self._confirm_payload(order_id, rows, carrier_id, parcel_number)
            existing = self.database.save_temu_shipment(
                order_id, status="label_created", parcel_number=parcel_number,
                carrier_id=carrier_id, label_path=str(label_path), temu_request=confirm_payload,
                express_response=_without_label_data(express_response), error=None,
            )

        try:
            temu_response = self.temu.request(TEMU_SHIPMENT_CONFIRM, confirm_payload)
            inner = self.temu._result(temu_response)
            if inner.get("success") is False:
                raise TemuError(str(inner.get("errorMsg") or "A Temu elutasította a feladást."))
            saved = self.database.save_temu_shipment(
                order_id, status="temu_confirmed", parcel_number=parcel_number,
                carrier_id=carrier_id, temu_response=temu_response, error=None,
            )
        except Exception as exc:
            self.database.save_temu_shipment(
                order_id, status="temu_failed", parcel_number=parcel_number,
                carrier_id=carrier_id, error=str(exc)[:2000],
            )
            raise
        self.database.add_activity("shipping", f"Temu rendelés feladva Express One-nal: {order_id} · {parcel_number}")
        return saved

    def refresh_tracking(self, parent_order_sn: str) -> dict[str, Any]:
        order_id = self._order_id(parent_order_sn)
        shipment = self.database.get_temu_shipment(order_id)
        if not shipment or not shipment.get("parcel_number"):
            raise TemuShippingError("Ehhez a rendeléshez még nincs Express One csomagszám.")
        return {"parent_order_sn": order_id, "parcel_number": shipment["parcel_number"],
                "tracking": self.express_one.parcel_status(str(shipment["parcel_number"]))}
