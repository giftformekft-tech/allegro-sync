from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re
import secrets
from urllib.parse import quote, urlparse

from .config import AppConfig
from .database import Database
from .invoices import InvoiceError, SzamlazzClient
from .temu import TemuClient, TemuError


TEMU_ORDER_LIST = "bg.order.list.v2.get"
TEMU_ORDER_SHIPPING = "bg.order.shippinginfo.v2.get"
TEMU_INVOICE_DETAIL = "temu.pay.tax.invoice.detail.query"
TEMU_INVOICE_UPLOAD = "temu.pay.tax.merchant.upload.invoice"
ORDER_STATUS = {
    1: "Függőben",
    2: "Feladásra vár",
    3: "Törölve",
    4: "Feladva",
    41: "Részben feladva",
    5: "Kézbesítve",
    51: "Részben kézbesítve",
}


def _minor(value: object) -> Decimal:
    """Temu tax money fields are integer minor units (two decimal places)."""
    try:
        return (Decimal(str(value or 0)) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvoiceError(f"Érvénytelen Temu pénzösszeg: {value}") from exc


def _vat_rate(row: dict, net: Decimal, gross: Decimal) -> str:
    try:
        rate = Decimal(str(row.get("vatRate", 0) or 0))
        base = Decimal(str(row.get("vatRateBase", 0) or 0))
        if base:
            return format((rate / base * 100).quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".")
    except (InvalidOperation, TypeError, ValueError):
        pass
    if net:
        return format(((gross - net) / net * 100).quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".")
    return "0"


def _timestamp_date(value: object) -> str:
    try:
        milliseconds = int(value or 0)
    except (TypeError, ValueError):
        milliseconds = 0
    if not milliseconds:
        return datetime.now(timezone.utc).date().isoformat()
    if milliseconds < 10_000_000_000:
        milliseconds *= 1000
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).date().isoformat()


def _platform_address_parts(value: object) -> dict[str, str]:
    """Create conservative structured suggestions from Temu's one-line address."""
    raw = str(value or "").strip()
    parts = [part.strip() for part in re.split(r"[,;\n]+", raw) if part.strip()]
    result = {"country": "", "zip": "", "city": "", "street": ""}
    if len(parts) < 2:
        result["street"] = raw
        return result

    result["country"] = parts[-1]
    middle = parts[1:-1]
    result["street"] = parts[0]
    postal_city = re.compile(r"^([A-Z]{1,2}-?\d{3,6}|\d{4,6}|[A-Z]\d[A-Z][ -]?\d[A-Z]\d)\s+(.+)$", re.I)
    if middle:
        match = postal_city.match(middle[-1])
        if match:
            result["zip"], result["city"] = match.group(1), match.group(2)
            if len(middle) > 1:
                result["street"] = ", ".join(parts[:1] + middle[:-1])
        elif len(middle) >= 2:
            postcode = middle[-1]
            if re.fullmatch(r"[A-Z0-9][A-Z0-9 -]{2,9}", postcode, re.I) and any(char.isdigit() for char in postcode):
                result["zip"] = postcode
                result["city"] = middle[-2]
                result["street"] = ", ".join(parts[:1] + middle[:-2]) or parts[0]
            else:
                result["city"] = middle[-1]
                result["street"] = ", ".join(parts[:1] + middle[:-1]) or parts[0]
        else:
            result["city"] = middle[0]
    return result


class TemuInvoiceService:
    def __init__(self, config: AppConfig, database: Database, temu: TemuClient):
        self.config = config
        self.database = database
        self.temu = temu
        self.szamlazz = SzamlazzClient(config)

    @staticmethod
    def _order_id(value: str) -> str:
        order_id = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{3,80}", order_id):
            raise InvoiceError("Érvénytelen Temu rendelésazonosító.")
        return order_id

    def list_orders(self) -> list[dict]:
        response = self.temu.request(TEMU_ORDER_LIST, {
            "request": {"pageNumber": 1, "pageSize": 100, "parentOrderStatus": 0}
        })
        result = self.temu._result(response)
        page_items = result.get("pageItems") if isinstance(result.get("pageItems"), list) else []
        local = self.database.list_temu_order_invoices()
        rows: list[dict] = []
        for entry in page_items:
            if not isinstance(entry, dict):
                continue
            parent = entry.get("parentOrderMap") if isinstance(entry.get("parentOrderMap"), dict) else {}
            order_id = str(parent.get("parentOrderSn", ""))
            if not order_id:
                continue
            lines = entry.get("orderList") if isinstance(entry.get("orderList"), list) else []
            invoices = local.get(order_id, [])
            status = "none"
            if invoices and all(row.get("status") == "uploaded" for row in invoices):
                status = "uploaded"
            elif any(row.get("status") == "upload_failed" for row in invoices):
                status = "upload_failed"
            elif invoices:
                status = "created"
            rows.append({
                "id": order_id,
                "status": int(parent.get("parentOrderStatus", 0) or 0),
                "status_label": ORDER_STATUS.get(int(parent.get("parentOrderStatus", 0) or 0), "Ismeretlen"),
                "created_at": int(parent.get("parentOrderTime", 0) or 0) * 1000,
                "updated_at": int(parent.get("updateTime", parent.get("parentOrderTime", 0)) or 0) * 1000,
                "item_count": sum(int(line.get("quantity", 0) or 0) for line in lines if isinstance(line, dict)),
                "product_names": [str(line.get("originalGoodsName") or line.get("goodsName") or "Temu termék") for line in lines[:3] if isinstance(line, dict)],
                "invoice_status": status,
                "invoice_numbers": [str(row.get("invoice_number", "")) for row in invoices if row.get("invoice_number")],
                "invoice_error": next((str(row.get("error")) for row in invoices if row.get("error")), ""),
            })
        return rows

    def preview(self, parent_order_sn: str) -> dict:
        order_id = self._order_id(parent_order_sn)
        details = self.temu._result(self.temu.request(
            TEMU_INVOICE_DETAIL, {"request": {"parentOrderSn": order_id}}
        ))
        shipping = self.temu._result(self.temu.request(
            TEMU_ORDER_SHIPPING, {"request": {"parentOrderSn": order_id}}
        ))
        raw_documents = details.get("invoiceDetailInfoList")
        if not isinstance(raw_documents, list) or not raw_documents:
            raise InvoiceError("A Temu még nem adott számlázható részleteket ehhez a rendeléshez.")
        drafts = [self._draft(order_id, index, row, shipping) for index, row in enumerate(raw_documents) if isinstance(row, dict)]
        if not drafts:
            raise InvoiceError("A Temu számlarészletei üresek.")
        existing = self.database.list_temu_order_invoices().get(order_id, [])
        by_key = {str(row.get("document_key")): row for row in existing}
        for draft in drafts:
            saved = by_key.get(str(draft["document_key"]))
            draft["status"] = str(saved.get("status", "none")) if saved else "none"
            draft["invoice_number"] = str(saved.get("invoice_number", "")) if saved else ""
            draft["ready"] = not draft["problems"] and draft["invoice_direction"] == 1
        return {"parent_order_sn": order_id, "documents": drafts}

    def _consumer(self, shipping: dict) -> dict[str, str]:
        regions = [str(shipping.get(key, "")).strip() for key in ("regionName4", "regionName3", "regionName2")]
        street = str(shipping.get("addressLineAll", "")).strip() or " ".join(
            str(shipping.get(key, "")).strip() for key in ("addressLine1", "addressLine2", "addressLine3")
            if str(shipping.get(key, "")).strip()
        )
        return {
            "name": str(shipping.get("receiptName", "")).strip(),
            "country": str(shipping.get("regionName1", "")).strip(),
            "zip": str(shipping.get("postCode", "")).strip(),
            "city": next((value for value in regions if value), ""),
            "street": street,
            "tax_id": "",
            "email": str(shipping.get("mail", "")).strip(),
        }

    def _platform(self, info: dict) -> dict[str, object]:
        platform = info.get("platformInfo") if isinstance(info.get("platformInfo"), dict) else {}
        raw_address = str(platform.get("platformAddress", "")).strip()
        suggested = _platform_address_parts(raw_address)
        return {
            "name": str(platform.get("platformName") or self.config.values.get("TEMU_PLATFORM_NAME", "")).strip(),
            "country": self.config.values.get("TEMU_PLATFORM_COUNTRY", "").strip() or suggested["country"],
            "zip": self.config.values.get("TEMU_PLATFORM_ZIP", "").strip() or suggested["zip"],
            "city": self.config.values.get("TEMU_PLATFORM_CITY", "").strip() or suggested["city"],
            "street": self.config.values.get("TEMU_PLATFORM_STREET", "").strip() or suggested["street"],
            "tax_id": self.config.values.get("TEMU_PLATFORM_TAX_ID", "").strip(),
            "email": self.config.values.get("TEMU_PLATFORM_EMAIL", "").strip(),
            "api_address": raw_address,
            "api_address_approved": bool(raw_address) and raw_address == self.config.values.get("TEMU_PLATFORM_APPROVED_ADDRESS", "").strip(),
        }

    def approve_platform_address(self, parent_order_sn: str) -> dict:
        order_id = self._order_id(parent_order_sn)
        details = self.temu._result(self.temu.request(
            TEMU_INVOICE_DETAIL, {"request": {"parentOrderSn": order_id}}
        ))
        rows = details.get("invoiceDetailInfoList") if isinstance(details.get("invoiceDetailInfoList"), list) else []
        addresses: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            platform = row.get("platformInfo") if isinstance(row.get("platformInfo"), dict) else {}
            address = str(platform.get("platformAddress", "")).strip()
            if address and address not in addresses:
                addresses.append(address)
        if len(addresses) != 1:
            raise InvoiceError("A Temu nem adott egyértelműen jóváhagyható platformcímet ehhez a rendeléshez.")
        self.config.save({"TEMU_PLATFORM_APPROVED_ADDRESS": addresses[0]})
        self.database.add_activity("settings", f"Temu platformcím jóváhagyva: {order_id}")
        return {"ok": True, "parent_order_sn": order_id, "suggested": _platform_address_parts(addresses[0])}

    @staticmethod
    def _row_item(row: dict, fallback_name: str) -> dict:
        quantity = Decimal(str(int(row.get("quantity", 1) or 1)))
        net = _minor(row.get("unitPriceExcludeVAT")) * quantity
        gross = _minor(row.get("totalGoodsAmount"))
        if not gross:
            gross = _minor(row.get("unitPriceWithVAT")) * quantity
        vat = gross - net
        name = str(row.get("description") or fallback_name).strip()
        spec = str(row.get("skuSpec", "")).strip()
        return {
            "name": name,
            "quantity": format(quantity, "f"),
            "unit": "db",
            "net": format(net, "f"),
            "vat": format(vat, "f"),
            "gross": format(gross, "f"),
            "vat_rate": _vat_rate(row, net, gross),
            "note": spec,
        }

    def _draft(self, order_id: str, index: int, info: dict, shipping: dict) -> dict:
        try:
            recipient_type = int(info.get("invoiceDetailType", 0) or 0)
        except (TypeError, ValueError):
            recipient_type = 0
        meta = info.get("orderMetaInfo") if isinstance(info.get("orderMetaInfo"), dict) else {}
        direction = 2 if meta.get("refundTimeMillis") else 1
        currency = str(info.get("currency", "HUF") or "HUF").upper()
        buyer = self._consumer(shipping) if recipient_type == 1 else self._platform(info)
        problems: list[str] = []
        if recipient_type not in {1, 2}:
            problems.append(f"Ismeretlen Temu számlacímzett-típus: {recipient_type}.")
        for key, label in (("name", "név"), ("country", "ország"), ("zip", "irányítószám"),
                           ("city", "település"), ("street", "cím")):
            if not buyer.get(key):
                problems.append(f"Hiányzik a címzett {label} mezője.")
        if recipient_type == 2 and not buyer.get("tax_id"):
            problems.append("Hiányzik a Temu platform adószáma a beállításokból.")
        if recipient_type == 2 and not buyer.get("api_address_approved"):
            problems.append("A Temu API platformcímét egyszer ellenőrizni és jóváhagyni kell.")
        if direction == 2:
            problems.append("A jóváíró számla automatikus kiállítása még nincs engedélyezve.")
        if currency != "HUF":
            problems.append("A nem HUF-os Temu-számla MNB árfolyamkezelése még nincs engedélyezve.")

        items: list[dict] = []
        for row in info.get("goodsInfoList") or []:
            if isinstance(row, dict):
                items.append(self._row_item(row, "Temu termék"))
        for row in info.get("shippingInfoList") or []:
            if isinstance(row, dict):
                items.append(self._row_item(row, "Szállítási díj"))
        shipping_fee = info.get("shippingFee") if isinstance(info.get("shippingFee"), dict) else {}
        if not (info.get("shippingInfoList") or []) and shipping_fee:
            net = _minor(shipping_fee.get("shippingAmountExcludeTax"))
            gross = _minor(shipping_fee.get("shippingAmountWithTax"))
            if gross or net:
                items.append({"name": "Szállítási díj", "quantity": "1", "unit": "db",
                              "net": format(net, "f"), "vat": format(gross - net, "f"),
                              "gross": format(gross, "f"), "vat_rate": _vat_rate({}, net, gross), "note": ""})
        promotion = info.get("promotionInfo") if isinstance(info.get("promotionInfo"), dict) else {}
        promo_net = _minor(promotion.get("promotionAmountExcludeTax"))
        promo_gross = _minor(promotion.get("promotionAmountWithTax"))
        if promo_net or promo_gross:
            items.append({
                "name": f"Temu által finanszírozott promóciós kedvezmény megtérítése – {order_id}",
                "quantity": "1", "unit": "db", "net": format(promo_net, "f"),
                "vat": format(promo_gross - promo_net, "f"), "gross": format(promo_gross, "f"),
                "vat_rate": _vat_rate({}, promo_net, promo_gross), "note": "Temu promotion",
            })
        for row in info.get("addOrderInfoList") or []:
            if not isinstance(row, dict):
                continue
            net = _minor(row.get("amountExcludeTax")); gross = _minor(row.get("amountWithTax"))
            if net or gross:
                items.append({
                    "name": f"Temu kiegészítő rendelési tétel ({row.get('addOrderDetailType', '')})",
                    "quantity": "1", "unit": "db", "net": format(net, "f"),
                    "vat": format(gross - net, "f"), "gross": format(gross, "f"),
                    "vat_rate": _vat_rate({}, net, gross), "note": "",
                })
        if not items:
            problems.append("A Temu nem adott számlázható tételt.")
        document_key = f"{index + 1}-{recipient_type}-{direction}"
        total = sum((Decimal(str(item["gross"])) for item in items), Decimal("0"))
        return {
            "document_key": document_key,
            "recipient_type": recipient_type,
            "recipient_label": "Vevő" if recipient_type == 1 else "Temu platform" if recipient_type == 2 else "Ismeretlen",
            "invoice_direction": direction,
            "currency": currency,
            "date": _timestamp_date(meta.get("refundTimeMillis") or meta.get("orderTimeMillis")),
            "buyer": buyer,
            "items": items,
            "total": format(total, "f"),
            "problems": problems,
        }

    def _public_base(self) -> str:
        base = self.config.values.get("TEMU_INVOICE_PUBLIC_BASE_URL", "").strip().rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme != "https" or not parsed.netloc or parsed.hostname in {"localhost", "127.0.0.1"}:
            raise InvoiceError(
                "A Temu PDF-feltöltéshez adj meg nyilvánosan elérhető HTTPS alapcímet a Beállításokban."
            )
        return base

    def create_and_upload(self, parent_order_sn: str) -> dict:
        if self.config.values.get("INVOICE_DRIVER") != "szamlazz" or not self.config.values.get("SZAMLAZZ_AGENT_KEY", ""):
            raise InvoiceError("Kapcsold be a Számla Agent modult és add meg az Agent kulcsot.")
        public_base = self._public_base()
        preview = self.preview(parent_order_sn)
        if any(not document.get("ready") for document in preview["documents"]):
            problems = [problem for document in preview["documents"] for problem in document.get("problems", [])]
            raise InvoiceError("A Temu-számlák még nem állíthatók ki: " + " ".join(problems))

        results = []
        order_id = str(preview["parent_order_sn"])
        invoice_dir = self.config.root / "var" / "invoices" / "temu"
        invoice_dir.mkdir(parents=True, exist_ok=True)
        prefix = self.config.values.get("SZAMLAZZ_TEMU_INVOICE_PREFIX", "")
        for document in preview["documents"]:
            key = str(document["document_key"])
            current = self.database.get_temu_order_invoice(order_id, key)
            if current and current.get("status") == "uploaded":
                results.append(current)
                continue
            pdf_path = Path(str(current.get("pdf_path", ""))) if current and current.get("pdf_path") else None
            if current and current.get("invoice_number") and pdf_path and pdf_path.is_file():
                invoice_number = str(current["invoice_number"])
                file_token = str(current.get("file_token") or secrets.token_urlsafe(24))
            else:
                invoice_payload = {
                    **document,
                    "external_id": f"temu-{order_id}-{key}",
                    "order_number": order_id,
                    "note": f"Temu rendelés: {order_id} · {document['recipient_label']}",
                    "payment_method": "Online fizetés",
                }
                invoice_number, pdf, buyer_email = self.szamlazz.create_custom_invoice(invoice_payload, prefix)
                file_token = secrets.token_urlsafe(24)
                pdf_path = invoice_dir / f"{file_token}.pdf"
                pdf_path.write_bytes(pdf)
                current = self.database.save_temu_order_invoice(
                    order_id, key, recipient_type=int(document["recipient_type"]),
                    invoice_direction=int(document["invoice_direction"]), status="created",
                    invoice_number=invoice_number, buyer_email=buyer_email,
                    file_token=file_token, pdf_path=str(pdf_path),
                )
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice_number).strip("-") or "invoice"
            file_url = f"{public_base}/api/temu/invoice-files/{quote(file_token)}.pdf"
            try:
                response = self.temu.request(TEMU_INVOICE_UPLOAD, {"request": {
                    "parentOrderSn": order_id,
                    "invoiceDirection": int(document["invoice_direction"]),
                    "invoiceName": f"{safe_name}.pdf",
                    "recipientType": int(document["recipient_type"]),
                    "fileUrl": file_url,
                }})
                upload_result = self.temu._result(response)
                if upload_result.get("success") is not True:
                    raise TemuError("A Temu nem igazolta vissza a számla feltöltését.")
                saved = self.database.save_temu_order_invoice(
                    order_id, key, recipient_type=int(document["recipient_type"]),
                    invoice_direction=int(document["invoice_direction"]), status="uploaded",
                    invoice_number=invoice_number, file_token=file_token, pdf_path=str(pdf_path), error=None,
                )
                results.append(saved)
            except Exception as exc:
                self.database.save_temu_order_invoice(
                    order_id, key, recipient_type=int(document["recipient_type"]),
                    invoice_direction=int(document["invoice_direction"]), status="upload_failed",
                    invoice_number=invoice_number, file_token=file_token, pdf_path=str(pdf_path), error=str(exc),
                )
                raise
        self.database.add_activity("invoice", f"Temu-számla elkészült és feltöltve: {order_id}")
        return {"ok": True, "parent_order_sn": order_id, "invoices": results}
